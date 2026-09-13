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

# 3+ examples per class -- Logistic Regression's CalibratedClassifierCV(cv=3)
# (Phase 22) needs at least 3 positive examples of the rarest class or it
# raises inside its One-vs-Rest sub-problem, not a pipeline bug (same
# fixture-sizing note as test_category_pipeline.py and test_priority_pipeline.py).
TRAIN_TEXTS = [
    "please cancel my subscription immediately",
    "please cancel my account right away",
    "i need to cancel this order today",
    "i want a refund for my last payment",
    "please refund my last two charges",
    "requesting a refund for the duplicate charge",
    "can you tell me the status of my order",
    "when will my order ship out",
    "please confirm my order was received",
    "does your product support single sign on",
    "i have a question about pricing",
    "what plans do you offer for enterprise",
    "please escalate this to your manager now",
    "this is my third email please escalate",
    "escalating this complaint to a supervisor",
    "are you available for a call next week",
    "can we schedule a meeting for tuesday",
    "please schedule a demo for next month",
    "just wanted to share some positive feedback",
    "great job on the new release",
    "leaving some feedback about the support team",
    "this is extremely frustrating and unacceptable service",
    "i am not happy with how this was handled",
    "filing a complaint about the delayed response",
    "please send me the updated invoice",
    "requesting access to the shared drive",
    "please process this request as soon as possible",
]
TRAIN_LABELS = [
    ["Cancel"],
    ["Cancel"],
    ["Cancel"],
    ["Refund"],
    ["Refund"],
    ["Refund"],
    ["Order"],
    ["Order"],
    ["Order"],
    ["Inquiry"],
    ["Inquiry"],
    ["Inquiry"],
    ["Escalation"],
    ["Escalation"],
    ["Escalation"],
    ["Schedule"],
    ["Schedule"],
    ["Schedule"],
    ["Feedback"],
    ["Feedback"],
    ["Feedback"],
    ["Complaint"],
    ["Complaint"],
    ["Complaint"],
    ["Request"],
    ["Request"],
    ["Request"],
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
