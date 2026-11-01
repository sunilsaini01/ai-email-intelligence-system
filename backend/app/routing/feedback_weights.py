"""
Learning per-department auto-route thresholds from routing feedback
(FR-41: "System shall detect routing errors via human feedback and adjust
rule weights").

The one "weight" in app/routing/rules.py that routing feedback can
meaningfully inform is CATEGORY_AUTO_ROUTE_THRESHOLD -- the confidence
above which an email is routed without a human looking at it. If reviewers
keep correcting emails auto-routed to Sales, Sales' threshold should rise
(more of them go to review); if a department's routing is almost never
corrected, its threshold can relax slightly. Nothing else moves: rule
precedence, the spam gate and the HR/Legal/Billing mandatory review stay
exactly as written.

Pure function; the DB side lives in app/services/routing_feedback_service.py.
Bounded and conservative by construction -- a handful of corrections
can't swing routing wildly:
  - no adjustment until MIN_SAMPLES reviewed decisions exist for a department;
  - the move is proportional to how far the correction rate is from
    TARGET_CORRECTION_RATE (the PRD SS14.3 north-star of < 8%);
  - the result is clamped to [THRESHOLD_FLOOR, THRESHOLD_CAP].
"""

from dataclasses import dataclass

from app.routing.rules import CATEGORY_AUTO_ROUTE_THRESHOLD

MIN_SAMPLES = 10
TARGET_CORRECTION_RATE = 0.08
GAIN = 0.5
THRESHOLD_FLOOR = 0.50
THRESHOLD_CAP = 0.85
FEEDBACK_WINDOW_DAYS = 90


@dataclass(frozen=True)
class DepartmentFeedback:
    reviewed: int
    corrected: int

    @property
    def correction_rate(self) -> float:
        return self.corrected / self.reviewed if self.reviewed else 0.0


def compute_department_thresholds(stats: dict[str, DepartmentFeedback]) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for department, feedback in stats.items():
        if feedback.reviewed < MIN_SAMPLES:
            continue
        raw = CATEGORY_AUTO_ROUTE_THRESHOLD + (feedback.correction_rate - TARGET_CORRECTION_RATE) * GAIN
        threshold = round(min(max(raw, THRESHOLD_FLOOR), THRESHOLD_CAP), 2)
        if threshold != CATEGORY_AUTO_ROUTE_THRESHOLD:
            thresholds[department] = threshold
    return thresholds
