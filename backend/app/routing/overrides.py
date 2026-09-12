"""
Admin-configurable routing override evaluation (Phase 21, FR-39).

Pure, DB-free function -- same "signals in, decision out, independently
testable" shape app/routing/rules.py's own resolve_routing() already
established, applied one layer further out: this takes the DICT
resolve_routing()/RoutingService.route() already produced (not the
RoutingSignals dataclass, which is internal to that module) and returns a
possibly-adjusted copy of it. Kept entirely separate from rules.py rather
than folded into it: rules.py is the carefully-tuned, error-analysis-
backed base engine (see its own module docstring); this file is a much
simpler, later, additive pass over that engine's output, and mixing the
two would blur which logic is which when someone is debugging a decision.

Supported condition fields (all read from the base decision dict's
`supporting_signals`, or from the raw request for the last three):
    category              -- top predicted category label
    priority              -- predicted priority label
    sentiment             -- predicted sentiment label
    is_spam               -- boolean
    intent                -- one label from the predicted intent list
    sender_domain_type    -- "internal" | "external" | "freemail" | "unknown"
    sender_email_domain   -- exact domain of the sender's email address
    subject_contains      -- substring match against the raw subject
    body_contains         -- substring match against the raw body

Supported operators: "eq" (exact match), "in" (value is one of a list),
"contains" (substring match for text fields; membership check for the
list-valued `intent` field).

Only ONE override applies per decision -- the FIRST whose conditions all
match, evaluated in ascending priority_order (the order the repository
already returns them in). This mirrors how a firewall/routing rule list
conventionally works, and matches FR-39's literal "priority ordering"
wording: a condition set that needs to express "OR" is just two separate
override rules at the same priority_order, not a feature this evaluator
itself needs to support.

Non-negotiable safety net, re-applied AFTER every override: if the
resulting department (whether chosen by the base engine or forced by the
override) is one of app.routing.department_taxonomy.HIGH_IMPACT_DEPARTMENTS,
requires_human_review is forced True regardless of what the override
said. An override can silence review for a department that never needed
it in the first place, but it can never turn off the review guarantee
app/routing/rules.py:R-HIGH-IMPACT-DEPARTMENT-REVIEW already established
for HR/Legal/Billing -- that guarantee exists because of real,
PRD-stated business risk (harassment complaints, legal notices, financial
action), not a numeric confidence policy an admin should be able to
override via a UI toggle.
"""

from dataclasses import dataclass

from app.routing.department_taxonomy import HIGH_IMPACT_DEPARTMENTS

CONDITION_FIELDS: tuple[str, ...] = (
    "category",
    "priority",
    "sentiment",
    "is_spam",
    "intent",
    "sender_domain_type",
    "sender_email_domain",
    "subject_contains",
    "body_contains",
)
CONDITION_OPERATORS: tuple[str, ...] = ("eq", "in", "contains")

_TEXT_CONTAINS_FIELDS = frozenset({"subject_contains", "body_contains", "sender_email_domain", "category", "priority", "sentiment", "sender_domain_type"})


@dataclass(frozen=True)
class OverrideCondition:
    field: str
    operator: str
    value: object  # str | bool | list[str], depending on field/operator


@dataclass(frozen=True)
class OverrideRule:
    id: str
    name: str
    conditions: tuple[OverrideCondition, ...]
    override_department: str | None
    override_action: str | None
    override_requires_human_review: bool | None


def _extract_field(field: str, decision: dict, subject: str, body: str, sender_email: str):
    signals = decision.get("supporting_signals") or {}
    if field == "category":
        return (signals.get("category") or {}).get("top")
    if field == "priority":
        return (signals.get("priority") or {}).get("label")
    if field == "sentiment":
        return (signals.get("sentiment") or {}).get("label")
    if field == "is_spam":
        return (signals.get("spam") or {}).get("is_spam")
    if field == "intent":
        return (signals.get("intent") or {}).get("labels") or []
    if field == "sender_domain_type":
        return (signals.get("sender_domain") or {}).get("type")
    if field == "sender_email_domain":
        return sender_email.rsplit("@", 1)[-1].lower() if "@" in sender_email else ""
    if field == "subject_contains":
        return subject or ""
    if field == "body_contains":
        return body or ""
    return None


def _condition_matches(condition: OverrideCondition, decision: dict, subject: str, body: str, sender_email: str) -> bool:
    actual = _extract_field(condition.field, decision, subject, body, sender_email)

    if condition.operator == "eq":
        return actual == condition.value
    if condition.operator == "in":
        return actual in (condition.value or [])
    if condition.operator == "contains":
        if condition.field == "intent":
            return condition.value in actual  # actual is the list of intent labels
        if condition.field in _TEXT_CONTAINS_FIELDS and isinstance(actual, str) and isinstance(condition.value, str):
            return condition.value.lower() in actual.lower()
        return False
    return False


def apply_overrides(decision: dict, subject: str, body: str, sender_email: str, overrides: list[OverrideRule]) -> dict:
    """Returns a NEW dict -- never mutates `decision` in place, same
    "don't hand callers a mutated copy of something they still hold a
    reference to" discipline as everywhere else results get threaded
    through this pipeline."""
    for override in overrides:
        if not override.conditions:
            continue  # defensive only -- the API layer itself requires at least one condition at creation time
        if not all(_condition_matches(c, decision, subject, body, sender_email) for c in override.conditions):
            continue

        result = dict(decision)
        matched_rules = [*decision.get("matched_rules", []), f"OVERRIDE:{override.id}:{override.name}"]
        reason_parts = [decision.get("reason", "")]

        if override.override_department is not None:
            result["department"] = override.override_department
            reason_parts.append(f"Admin override '{override.name}' set department to '{override.override_department}'.")
        if override.override_action is not None:
            result["action"] = override.override_action
            reason_parts.append(f"Admin override '{override.name}' set action to '{override.override_action}'.")
        if override.override_requires_human_review is not None:
            result["requires_human_review"] = override.override_requires_human_review
            reason_parts.append(
                f"Admin override '{override.name}' set requires_human_review to {override.override_requires_human_review}."
            )

        # Safety net -- see module docstring. Re-checked unconditionally,
        # not just when override_requires_human_review was False, so a
        # department forced BY THIS OVERRIDE into a high-impact one is
        # covered too, not just a pre-existing high-impact decision.
        if result["department"] in HIGH_IMPACT_DEPARTMENTS and not result["requires_human_review"]:
            result["requires_human_review"] = True
            matched_rules.append("R-HIGH-IMPACT-DEPARTMENT-REVIEW")
            reason_parts.append(
                f"'{result['department']}' is a high-impact department -- mandatory human review "
                "cannot be overridden."
            )

        result["matched_rules"] = matched_rules
        result["reason"] = " ".join(p for p in reason_parts if p)
        return result

    return decision
