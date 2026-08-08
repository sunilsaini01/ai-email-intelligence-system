"""
Unit tests for CategoryMLPipeline (Module 4) — fast, self-contained, no
dependency on the real trained artifact or the synthetic dataset files.
Mirrors test_priority_pipeline.py's structure, adapted for multi-label
fit/predict/predict_proba shapes.
"""

from datetime import UTC, datetime

import pytest

from app.feature_engineering.category_keywords import CATEGORY_LABELS
from app.pipeline.category_pipeline import CategoryMLPipeline
from app.pipeline.pipeline_config import PipelineConfig

VALID_LABELS = set(CATEGORY_LABELS)


def _record(body_clean: str, subject_raw: str = "", **overrides) -> dict:
    base = {
        "body_clean": body_clean,
        "subject_raw": subject_raw,
        "sender_email": "someone@example.com",
        "received_at": datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
        "recipient_to": ["team@example.com"],
        "recipient_cc": [],
        "is_reply": False,
        "is_forward": False,
        "thread_depth": 0,
        "has_attachments": False,
        "attachment_count": 0,
    }
    base.update(overrides)
    return base


TRAIN_RECORDS = [
    _record("invoice payment past due billing charge"),
    _record("refund dispute the charge on my subscription"),
    _record("billed twice please issue a refund receipt"),
    _record("contract legal review terms compliance audit"),
    _record("subpoena legal notice cease and desist"),
    _record("nda data processing agreement gdpr counsel"),
    _record("vpn access request password reset laptop"),
    _record("server outage network down firewall issue"),
    _record("provisioning install software update reboot"),
    _record("pricing quote demo enterprise plan proposal"),
    _record("purchase upgrade opportunity prospect reseller"),
    _record("interested in your product partnership deal"),
    _record("happy friday team lunch great weekend"),
    _record("building maintenance notice elevator out of service"),
    _record("all hands meeting reminder next week"),
]
# 3+ examples per class -- SVM's CalibratedClassifierCV(cv=3) needs at least
# 3 positive examples of the rarest class or it raises inside its One-vs-Rest
# sub-problem, not a pipeline bug (same fixture-sizing note as
# test_priority_pipeline.py).
TRAIN_LABELS = [
    ["Billing"], ["Billing"], ["Billing"],
    ["Legal"], ["Legal"], ["Legal"],
    ["IT"], ["IT"], ["IT"],
    ["Sales"], ["Sales"], ["Sales"],
    ["General"], ["General"], ["General"],
]


@pytest.fixture(params=["logistic_regression", "naive_bayes", "svm"])
def trained_pipeline(request):
    config = PipelineConfig(model_type=request.param, task="category", class_weight="balanced")
    pipeline = CategoryMLPipeline(config)
    pipeline.fit(TRAIN_RECORDS, TRAIN_LABELS)
    return pipeline


def test_fit_predict_returns_valid_label_lists(trained_pipeline):
    predictions = trained_pipeline.predict(TRAIN_RECORDS)
    assert len(predictions) == len(TRAIN_RECORDS)
    for labels in predictions:
        assert isinstance(labels, list)
        assert set(labels).issubset(VALID_LABELS)


def test_predict_proba_shape_is_samples_by_labels(trained_pipeline):
    probabilities = trained_pipeline.predict_proba(TRAIN_RECORDS)
    assert probabilities.shape == (len(TRAIN_RECORDS), len(CATEGORY_LABELS))
    # Multi-label probabilities are independent per-category — unlike
    # single-label multiclass, rows must NOT be expected to sum to 1.
    for row in probabilities:
        assert all(0.0 <= p <= 1.0 for p in row)


def test_predict_is_deterministic(trained_pipeline):
    first = trained_pipeline.predict(TRAIN_RECORDS)
    second = trained_pipeline.predict(TRAIN_RECORDS)
    assert first == second


def test_save_and_load_round_trip(trained_pipeline, tmp_path):
    path = tmp_path / "category_test.joblib"
    trained_pipeline.save(str(path))

    reloaded = CategoryMLPipeline(trained_pipeline.config)
    reloaded.load(str(path))

    original_preds = trained_pipeline.predict(TRAIN_RECORDS)
    reloaded_preds = reloaded.predict(TRAIN_RECORDS)
    assert original_preds == reloaded_preds


def test_naive_bayes_path_does_not_scale_engineered_features():
    """Same constraint as PriorityMLPipeline — ComplementNB requires
    non-negative input, so no StandardScaler is attached for that path."""
    config = PipelineConfig(model_type="naive_bayes", task="category")
    pipeline = CategoryMLPipeline(config)
    assert pipeline.scaler is None

    pipeline.fit(TRAIN_RECORDS, TRAIN_LABELS)
    pipeline.predict(TRAIN_RECORDS)


def test_logistic_regression_path_does_scale_engineered_features():
    config = PipelineConfig(model_type="logistic_regression", task="category")
    pipeline = CategoryMLPipeline(config)
    assert pipeline.scaler is not None


def test_classes_match_full_taxonomy(trained_pipeline):
    """MultiLabelBinarizer is constructed with classes=CATEGORY_LABELS
    explicitly (app/pipeline/category_pipeline.py) — locks in that the
    model always has all 8 slots, even if a training batch happens not to
    contain every label (a real risk with small/skewed batches)."""
    assert list(trained_pipeline.classes_) == list(CATEGORY_LABELS)


def test_incompatible_feature_schema_is_rejected_explicitly(trained_pipeline):
    """Phase 6 Gate 1 regression test — same mechanism and same rationale
    as test_priority_pipeline.py's equivalent test; see
    app/feature_engineering/feature_schema.py's module docstring."""
    from app.feature_engineering.feature_schema import FeatureSchema, FeatureSchemaMismatchError

    stale_schema = FeatureSchema(
        feature_names=("some_field_that_no_longer_exists",),
        feature_count=1,
        fingerprint="0000deadbeef",
    )
    trained_pipeline.feature_schema = stale_schema

    with pytest.raises(FeatureSchemaMismatchError):
        trained_pipeline.predict(TRAIN_RECORDS)


def test_missing_feature_schema_attribute_does_not_crash(trained_pipeline):
    """A pre-Gate-1 pickled artifact won't have a `feature_schema`
    attribute at all — predict() must still work for legacy artifacts."""
    del trained_pipeline.feature_schema
    trained_pipeline.predict(TRAIN_RECORDS)  # must not raise
