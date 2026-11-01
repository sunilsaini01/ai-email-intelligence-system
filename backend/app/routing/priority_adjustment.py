"""
Post-model priority adjustment (FR-31, FR-17's "sender history" and
"body sentiment" inputs).

The priority model itself is a TF-IDF classifier over subject/body/
metadata -- it never sees the Sentiment module's output or anything about
the sender's past emails. FR-31 ("Negative or Very Negative sentiment on
non-spam emails shall increase priority score") and FR-17's sender-history
input are therefore applied here, as a deterministic, explainable step
after both models have run, rather than by retraining priority on features
it was never trained with.

Bounded on purpose:
  - Never applied to spam (FR-31 says "non-spam" explicitly).
  - Plain "Negative" can raise priority at most to High -- mild negativity
    alone is not evidence of a Critical issue. "Very Negative" may reach
    Critical.
  - Sender history adds at most one further level, also capped at High:
    a sender's past negativity says "pay attention", not "drop everything".

Thresholds are engineering defaults, not learned values (same RULE 14
discipline as app/routing/rules.py).
"""

from dataclasses import dataclass

PRIORITY_LEVELS = ("Low", "Medium", "High", "Critical")

PRIORITY_ADJUSTMENT_VERSION = "priority_adjustment_v1"

# FR-17/FR-32: how many negative emails from the same sender inside the
# trailing window count as a worsening relationship worth escalating.
SENDER_NEGATIVE_HISTORY_THRESHOLD = 3
SENDER_HISTORY_WINDOW_DAYS = 30


@dataclass(frozen=True)
class PriorityAdjustment:
    model_priority: str | None
    adjusted_priority: str | None
    reasons: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.model_priority != self.adjusted_priority

    def as_dict(self) -> dict:
        return {
            "model_priority": self.model_priority,
            "adjusted_priority": self.adjusted_priority,
            "changed": self.changed,
            "reasons": list(self.reasons),
            "version": PRIORITY_ADJUSTMENT_VERSION,
        }


def _raise(priority: str, cap: str) -> str:
    idx = PRIORITY_LEVELS.index(priority)
    cap_idx = PRIORITY_LEVELS.index(cap)
    if idx >= cap_idx:
        return priority
    return PRIORITY_LEVELS[idx + 1]


def adjust_priority(
    priority: str | None,
    sentiment: str | None,
    is_spam: bool | None,
    sender_negative_count: int = 0,
) -> PriorityAdjustment:
    if priority not in PRIORITY_LEVELS or is_spam:
        return PriorityAdjustment(priority, priority, ())

    adjusted = priority
    reasons: list[str] = []

    if sentiment == "Very Negative":
        new = _raise(adjusted, "Critical")
        if new != adjusted:
            reasons.append(f"Very Negative sentiment raised priority {adjusted} -> {new} (FR-31).")
            adjusted = new
    elif sentiment == "Negative":
        new = _raise(adjusted, "High")
        if new != adjusted:
            reasons.append(f"Negative sentiment raised priority {adjusted} -> {new} (FR-31).")
            adjusted = new

    if sender_negative_count >= SENDER_NEGATIVE_HISTORY_THRESHOLD:
        new = _raise(adjusted, "High")
        if new != adjusted:
            reasons.append(
                f"Sender sent {sender_negative_count} negative emails in the last "
                f"{SENDER_HISTORY_WINDOW_DAYS} days; priority raised {adjusted} -> {new} (FR-17/FR-32)."
            )
            adjusted = new

    return PriorityAdjustment(priority, adjusted, tuple(reasons))
