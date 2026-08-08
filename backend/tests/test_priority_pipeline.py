"""
Unit tests for PriorityMLPipeline (Module 3) — fast, self-contained, no
dependency on the real trained artifact or the synthetic dataset files.
Mirrors test_ml_pipeline.py's spirit (small in-memory example) but as a real
pytest-suite test, and covers save/load round-tripping which that script
never did.
"""

from datetime import UTC, datetime

import pytest

from app.pipeline.pipeline_config import PipelineConfig
from app.pipeline.priority_pipeline import PriorityMLPipeline

VALID_LABELS = {"Critical", "High", "Medium", "Low"}


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
    _record("critical outage escalate immediately production down"),
    _record("escalate to your manager this is unacceptable"),
    _record("urgent server breach detected act now"),
    _record("customer complaint delayed payment issue"),
    _record("high priority ticket needs same day response"),
    _record("important deadline approaching for the contract"),
    _record("please respond when you can no rush"),
    _record("status update project on track"),
    _record("internal request for the quarterly numbers"),
    _record("newsletter monthly digest fyi"),
    _record("routine meeting notes attached"),
    _record("automated report daily summary"),
]
# 3+ examples per class -- SVM's CalibratedClassifierCV(cv=3) needs at least
# 3 examples of the rarest class or it raises, not a pipeline bug (see the
# error this caught before the fixture was sized correctly).
TRAIN_LABELS = [
    "Critical", "Critical", "Critical",
    "High", "High", "High",
    "Medium", "Medium", "Medium",
    "Low", "Low", "Low",
]


@pytest.fixture(params=["logistic_regression", "naive_bayes", "svm"])
def trained_pipeline(request):
    config = PipelineConfig(model_type=request.param, task="priority", class_weight="balanced")
    pipeline = PriorityMLPipeline(config)
    pipeline.fit(TRAIN_RECORDS, TRAIN_LABELS)
    return pipeline


def test_fit_predict_returns_valid_labels(trained_pipeline):
    predictions = trained_pipeline.predict(TRAIN_RECORDS)
    assert len(predictions) == len(TRAIN_RECORDS)
    assert set(predictions).issubset(VALID_LABELS)


def test_predict_proba_sums_to_one(trained_pipeline):
    probabilities = trained_pipeline.predict_proba(TRAIN_RECORDS)
    for row in probabilities:
        assert abs(row.sum() - 1.0) < 1e-6


def test_predict_is_deterministic(trained_pipeline):
    first = trained_pipeline.predict(TRAIN_RECORDS)
    second = trained_pipeline.predict(TRAIN_RECORDS)
    assert list(first) == list(second)


def test_save_and_load_round_trip(trained_pipeline, tmp_path):
    path = tmp_path / "priority_test.joblib"
    trained_pipeline.save(str(path))

    reloaded = PriorityMLPipeline(trained_pipeline.config)
    reloaded.load(str(path))

    original_preds = trained_pipeline.predict(TRAIN_RECORDS)
    reloaded_preds = reloaded.predict(TRAIN_RECORDS)
    assert list(original_preds) == list(reloaded_preds)


def test_naive_bayes_path_does_not_scale_engineered_features():
    """
    Locks in the documented constraint from build_feature_matrix's
    docstring: Naive Bayes requires non-negative input, so PriorityMLPipeline
    must not attach a scaler for it (a StandardScaler can produce negative
    values, which would make ComplementNB raise).
    """
    config = PipelineConfig(model_type="naive_bayes", task="priority")
    pipeline = PriorityMLPipeline(config)
    assert pipeline.scaler is None

    # Must not raise -- this is the actual regression this test guards.
    pipeline.fit(TRAIN_RECORDS, TRAIN_LABELS)
    pipeline.predict(TRAIN_RECORDS)


def test_logistic_regression_path_does_scale_engineered_features():
    config = PipelineConfig(model_type="logistic_regression", task="priority")
    pipeline = PriorityMLPipeline(config)
    assert pipeline.scaler is not None


def test_incompatible_feature_schema_is_rejected_explicitly(trained_pipeline):
    """
    Phase 6 Gate 1 regression test — directly reproduces the Phase 5
    incident class (a stored schema that no longer matches the installed
    ContentFeatures/MetadataFeatures code) and confirms it now fails with a
    clear FeatureSchemaMismatchError instead of a cryptic sklearn
    dimension-mismatch error several call frames down.
    """
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
    """
    A pre-Gate-1 pickled artifact won't have a `feature_schema` attribute
    at all (not None — genuinely absent). predict() must still work rather
    than raising AttributeError, so legacy artifacts keep functioning until
    their next retrain (which will populate the attribute going forward).
    """
    del trained_pipeline.feature_schema
    trained_pipeline.predict(TRAIN_RECORDS)  # must not raise
