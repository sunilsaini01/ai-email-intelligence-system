"""
Unit tests for IntentMLPipeline (Module 7) — fast, self-contained, no
dependency on the real trained artifact or the synthetic dataset files.
Takes plain text (not record dicts), unlike CategoryMLPipeline — see
app/pipeline/intent_pipeline.py's module docstring for why.
"""

from app.feature_engineering.intent_keywords import INTENT_LABELS
from app.pipeline.intent_pipeline import IntentMLPipeline
from app.pipeline.pipeline_config import PipelineConfig

VALID_LABELS = set(INTENT_LABELS)

TRAIN_TEXTS = [
    "please cancel my subscription immediately",
    "i want a refund for my last payment",
    "please cancel and refund my order",
    "can you tell me the status of my order",
    "does your product support single sign on",
    "i have a question about pricing",
    "please escalate this to your manager now",
    "this is my third email please escalate",
    "are you available for a call next week",
    "can we schedule a meeting for tuesday",
    "just wanted to share some positive feedback",
    "great job on the new release",
]
TRAIN_LABELS = [
    ["Cancel"],
    ["Refund"],
    ["Cancel", "Refund"],
    ["Order"],
    ["Inquiry"],
    ["Inquiry"],
    ["Escalation"],
    ["Escalation"],
    ["Schedule"],
    ["Schedule"],
    ["Feedback"],
    ["Feedback"],
]


def _fit_pipeline() -> IntentMLPipeline:
    config = PipelineConfig(model_type="logistic_regression", task="intent")
    pipeline = IntentMLPipeline(config)
    pipeline.fit(TRAIN_TEXTS, TRAIN_LABELS)
    return pipeline


def test_fit_produces_classes_matching_intent_taxonomy():
    pipeline = _fit_pipeline()
    assert set(pipeline.classes_) == VALID_LABELS


def test_predict_returns_a_list_of_label_lists():
    pipeline = _fit_pipeline()
    predictions = pipeline.predict(["please cancel my account", "schedule a call please"])
    assert len(predictions) == 2
    for labels in predictions:
        assert isinstance(labels, list)
        assert set(labels).issubset(VALID_LABELS)


def test_predict_can_return_an_empty_list():
    """No fallback label exists for Intent (unlike Category's 'General') --
    an email matching none of the 9 classes should be able to predict []."""
    pipeline = _fit_pipeline()
    predictions = pipeline.predict(["the weather is nice today"])
    assert isinstance(predictions[0], list)


def test_predict_proba_rows_do_not_sum_to_one():
    """Multi-label: independent per-class probabilities, not a softmax --
    same structural assertion as test_category_pipeline.py's equivalent."""
    pipeline = _fit_pipeline()
    probabilities = pipeline.predict_proba(["please cancel my subscription"])
    assert probabilities.shape == (1, len(VALID_LABELS))


def test_save_and_load_round_trip(tmp_path):
    pipeline = _fit_pipeline()
    path = tmp_path / "intent_test.joblib"
    pipeline.save(str(path))

    loaded = IntentMLPipeline(PipelineConfig(model_type="logistic_regression", task="intent"))
    loaded.load(str(path))

    assert set(loaded.classes_) == VALID_LABELS
    assert loaded.predict(["please cancel my subscription"])[0]


def test_pipeline_has_no_feature_schema_attribute():
    """Deliberately not coupled to the shared ContentFeatures/MetadataFeatures
    FeatureSchema mechanism -- see docs/architecture_intent.md. This test
    locks in that deliberate absence rather than leaving it undocumented."""
    pipeline = _fit_pipeline()
    assert not hasattr(pipeline, "feature_schema")
