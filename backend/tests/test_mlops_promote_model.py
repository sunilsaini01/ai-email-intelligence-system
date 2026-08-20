"""
Tests for scripts/mlops/promote_model.py's pure decision logic (Phase 15A
/ FR-71): promotion-criteria evaluation and regression detection.

Deliberately does NOT touch app.mlops.mlflow_client or a live MLflow
server -- promote()'s end-to-end flow (download/sanity-check/deploy) is
covered by real infrastructure testing instead (see
docs/architecture/mlflow_architecture.md and this phase's own manual
verification), not mocked here. What IS unit-testable, and matters most
to get right, is the pass/fail arithmetic itself: a regression must never
be silently missed, and a metric missing from a candidate's logged
metrics must fail closed, not be skipped.
"""

import pytest

from scripts.mlops.promote_model import PROMOTION_CRITERIA, _check_regression, _evaluate_criteria
from app.mlops.model_metadata import REGISTRABLE_MODULES


def test_every_registrable_module_has_promotion_criteria():
    for module in REGISTRABLE_MODULES:
        assert module in PROMOTION_CRITERIA
        assert PROMOTION_CRITERIA[module]


def test_spam_candidate_passing_all_floors_is_accepted():
    ok, failures = _evaluate_criteria(
        "spam", {"recall_at_threshold": 0.95, "precision_at_threshold": 0.80}
    )
    assert ok is True
    assert failures == []


def test_spam_candidate_below_recall_floor_is_rejected():
    ok, failures = _evaluate_criteria(
        "spam", {"recall_at_threshold": 0.50, "precision_at_threshold": 0.80}
    )
    assert ok is False
    assert any("recall_at_threshold" in f for f in failures)


def test_spam_candidate_missing_a_required_metric_fails_closed():
    """A candidate whose logged run is missing a required metric must be
    rejected, not silently treated as passing (missing != None-is-fine)."""
    ok, failures = _evaluate_criteria("spam", {"recall_at_threshold": 0.95})
    assert ok is False
    assert any("precision_at_threshold" in f for f in failures)


def test_category_hamming_loss_uses_lower_is_better_direction():
    # hamming_loss floor is "<=" -- a value ABOVE the floor must fail.
    ok, failures = _evaluate_criteria(
        "category", {"f1_micro": 0.90, "hamming_loss": 0.50}
    )
    assert ok is False
    assert any("hamming_loss" in f for f in failures)

    ok, failures = _evaluate_criteria(
        "category", {"f1_micro": 0.90, "hamming_loss": 0.05}
    )
    assert ok is True


def test_check_regression_flags_a_lower_is_better_metric_getting_worse():
    # hamming_loss: candidate WORSE than production means candidate > production.
    # Warning text uses PROMOTION_CRITERIA's human description, not the raw
    # metric key -- see _check_regression's f-string.
    warnings = _check_regression(
        "category",
        candidate_metrics={"f1_micro": 0.90, "hamming_loss": 0.30},
        production_metrics={"f1_micro": 0.85, "hamming_loss": 0.10},
    )
    assert len(warnings) == 1
    assert "Hamming loss" in warnings[0]


def test_check_regression_flags_a_higher_is_better_metric_getting_worse():
    warnings = _check_regression(
        "spam",
        candidate_metrics={"recall_at_threshold": 0.80, "precision_at_threshold": 0.90},
        production_metrics={"recall_at_threshold": 0.98, "precision_at_threshold": 0.83},
    )
    assert len(warnings) == 1
    assert "recall" in warnings[0]


def test_check_regression_no_warnings_when_candidate_strictly_better():
    warnings = _check_regression(
        "spam",
        candidate_metrics={"recall_at_threshold": 0.99, "precision_at_threshold": 0.90},
        production_metrics={"recall_at_threshold": 0.98, "precision_at_threshold": 0.83},
    )
    assert warnings == []


def test_check_regression_skips_metrics_absent_from_either_side():
    """A metric absent from production's older logged run (e.g. added to
    PROMOTION_CRITERIA after that version was promoted) must not crash or
    be treated as a regression by default."""
    warnings = _check_regression(
        "spam",
        candidate_metrics={"recall_at_threshold": 0.99},
        production_metrics={},
    )
    assert warnings == []


@pytest.mark.parametrize("module", list(PROMOTION_CRITERIA.keys()))
def test_every_criterion_uses_a_valid_comparison_operator(module):
    for metric_key, (cmp_op, floor, _desc) in PROMOTION_CRITERIA[module].items():
        assert cmp_op in (">=", "<=")
        assert isinstance(floor, int | float)
