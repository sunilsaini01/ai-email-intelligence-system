"""
Unit tests for IntentService (Module 7 / Phase 7B), mirroring
test_sentiment_service.py's dependency-injection style (fake backend, not
the real trained artifact).
"""

from app.inference.prediction_models import MultiLabelPredictionResult
from app.services.intent_service import IntentService


class _FakeBackend:
    def __init__(self, labels=None):
        self.labels = labels if labels is not None else ["Cancel", "Refund"]
        self.last_text = None

    def predict(self, text: str) -> MultiLabelPredictionResult:
        self.last_text = text
        all_scores = dict.fromkeys(
            ["Complaint", "Inquiry", "Request", "Feedback", "Escalation",
             "Order", "Cancel", "Refund", "Schedule"],
            0.1,
        )
        for label in self.labels:
            all_scores[label] = 0.9
        return MultiLabelPredictionResult(
            labels=list(self.labels),
            label_confidences={label: 0.9 for label in self.labels},
            all_scores=all_scores,
            processing_ms=1.5,
        )

    def predict_batch(self, texts):
        return [self.predict(t) for t in texts]


def test_analyze_returns_the_expected_response_shape():
    service = IntentService(predictor=_FakeBackend())
    result = service.analyze(subject="Cancel", body="Please cancel and refund my order #123.")

    assert {i["intent"] for i in result["intents"]} == {"Cancel", "Refund"}
    assert result["processing_ms"] == 1.5
    assert set(result["all_scores"].keys()) == {
        "Complaint", "Inquiry", "Request", "Feedback", "Escalation",
        "Order", "Cancel", "Refund", "Schedule",
    }
    assert "order_ids" in result["entities"]
    assert result["entities"]["order_ids"] == ["123"]


def test_analyze_can_return_empty_intents():
    service = IntentService(predictor=_FakeBackend(labels=[]))
    result = service.analyze(subject="", body="the weather is nice today")
    assert result["intents"] == []


def test_analyze_preprocesses_before_predicting():
    backend = _FakeBackend()
    service = IntentService(predictor=backend)

    service.analyze(subject="Re: Update", body="<p>Please cancel.</p>")

    assert backend.last_text is not None
    assert "<p>" not in backend.last_text


def test_analyze_extracts_entities_from_raw_not_cleaned_text():
    """Entities must be extracted from the raw (pre-lemmatization) text --
    see intent_service.py's module comment on why."""
    service = IntentService(predictor=_FakeBackend())
    result = service.analyze(subject="", body="Please contact John Smith about order #999.")

    assert "John Smith" in result["entities"]["person_names"]
    assert "999" in result["entities"]["order_ids"]


def test_get_intent_service_returns_a_singleton():
    from app.services.intent_service import get_intent_service

    get_intent_service.cache_clear()
    try:
        a = get_intent_service()
        b = get_intent_service()
        assert a is b
    finally:
        get_intent_service.cache_clear()
