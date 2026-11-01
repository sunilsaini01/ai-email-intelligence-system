"""
Model drift monitoring (FR-72 "alert on model accuracy drift"; PRD SS14.4).

Two signals per module, both computed from data this system already
records -- there is no labelled production ground truth to measure true
accuracy against:

  - Prediction drift (SS14.4 "concept drift"): Population Stability Index
    between the predicted-label distribution of the last CURRENT_WINDOW_DAYS
    and the BASELINE_WINDOW_DAYS before that. Standard reading: < 0.10
    stable, 0.10-0.25 moderate, > 0.25 significant.
  - Performance drift (SS14.4 "alert if rolling 7-day model accuracy
    drops > 5% from baseline"): the feedback correction rate -- the PRD's
    own accuracy proxy (FR-62) -- over the same two windows. A rise of more
    than CORRECTION_RATE_ALERT_DELTA (5 points) counts as drift.

Input-feature drift (KL / Kolmogorov-Smirnov on raw features) is NOT
computed: raw email text is not retained in a feature-store form this
could test against, and prediction PSI is the standard cheap proxy for
it. Stated here rather than implied.
"""

import math
from collections import Counter
from dataclasses import dataclass

CURRENT_WINDOW_DAYS = 7
BASELINE_WINDOW_DAYS = 28
MIN_SAMPLES = 30
PSI_MODERATE = 0.10
PSI_SIGNIFICANT = 0.25
CORRECTION_RATE_ALERT_DELTA = 0.05
MIN_REVIEWED_FOR_PERFORMANCE = 20

STATUS_STABLE = "stable"
STATUS_MODERATE = "moderate"
STATUS_SIGNIFICANT = "significant"
STATUS_INSUFFICIENT_DATA = "insufficient_data"

_EPSILON = 1e-4


def population_stability_index(baseline: Counter, current: Counter) -> float:
    labels = set(baseline) | set(current)
    base_total = sum(baseline.values())
    curr_total = sum(current.values())
    if not labels or base_total == 0 or curr_total == 0:
        return 0.0
    psi = 0.0
    for label in labels:
        expected = max(baseline.get(label, 0) / base_total, _EPSILON)
        actual = max(current.get(label, 0) / curr_total, _EPSILON)
        psi += (actual - expected) * math.log(actual / expected)
    return round(psi, 4)


def classify_psi(psi: float) -> str:
    if psi >= PSI_SIGNIFICANT:
        return STATUS_SIGNIFICANT
    if psi >= PSI_MODERATE:
        return STATUS_MODERATE
    return STATUS_STABLE


@dataclass(frozen=True)
class ModuleDrift:
    module: str
    psi: float | None
    prediction_status: str
    baseline_count: int
    current_count: int
    baseline_correction_rate: float | None
    current_correction_rate: float | None
    performance_drift: bool
    baseline_distribution: dict
    current_distribution: dict

    @property
    def alert(self) -> bool:
        return self.prediction_status == STATUS_SIGNIFICANT or self.performance_drift

    def as_dict(self) -> dict:
        return {
            "module": self.module,
            "psi": self.psi,
            "prediction_status": self.prediction_status,
            "baseline_count": self.baseline_count,
            "current_count": self.current_count,
            "baseline_correction_rate": self.baseline_correction_rate,
            "current_correction_rate": self.current_correction_rate,
            "performance_drift": self.performance_drift,
            "alert": self.alert,
            "baseline_distribution": self.baseline_distribution,
            "current_distribution": self.current_distribution,
        }


def _rate(corrected: int, reviewed: int) -> float | None:
    return round(corrected / reviewed, 4) if reviewed else None


def evaluate_module(
    module: str,
    baseline_labels: Counter,
    current_labels: Counter,
    baseline_feedback: tuple[int, int] = (0, 0),
    current_feedback: tuple[int, int] = (0, 0),
) -> ModuleDrift:
    """`*_labels` count predicted labels (multi-label modules count every
    assigned label, so totals may exceed the email count); `*_feedback` is
    (reviewed, corrected)."""
    baseline_n = sum(baseline_labels.values())
    current_n = sum(current_labels.values())
    if baseline_n >= MIN_SAMPLES and current_n >= MIN_SAMPLES:
        psi = population_stability_index(baseline_labels, current_labels)
        prediction_status = classify_psi(psi)
    else:
        psi, prediction_status = None, STATUS_INSUFFICIENT_DATA

    baseline_rate = _rate(baseline_feedback[1], baseline_feedback[0])
    current_rate = _rate(current_feedback[1], current_feedback[0])
    performance_drift = (
        baseline_rate is not None
        and current_rate is not None
        and baseline_feedback[0] >= MIN_REVIEWED_FOR_PERFORMANCE
        and current_feedback[0] >= MIN_REVIEWED_FOR_PERFORMANCE
        and current_rate - baseline_rate > CORRECTION_RATE_ALERT_DELTA
    )

    return ModuleDrift(
        module=module,
        psi=psi,
        prediction_status=prediction_status,
        baseline_count=baseline_n,
        current_count=current_n,
        baseline_correction_rate=baseline_rate,
        current_correction_rate=current_rate,
        performance_drift=performance_drift,
        baseline_distribution=dict(baseline_labels),
        current_distribution=dict(current_labels),
    )
