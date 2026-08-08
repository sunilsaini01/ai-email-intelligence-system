"""
Unit tests for SentimentService (Module 6 / Phase 7A), mirroring
test_summarization_service.py's dependency-injection style (a fake backend,
not the real VADER predictor, so these tests assert wiring/contract, not
lexicon behavior -- that's test_sentiment_predictor.py's job).
"""

from app.inference.prediction_models import PredictionResult
from app.services.sentiment_service import MODEL_VERSION, SentimentService


class _FakeBackend:
    def __init__(self, label="Positive"):
        self.label = label
        self.last_text = None

    def predict(self, text: str) -> PredictionResult:
        self.last_text = text
        return PredictionResult(
            label=self.label,
            confidence=0.9,
            probabilities={
                "Very Negative": 0.0,
                "Negative": 0.0,
                "Neutral": 0.1,
                "Positive": 0.9,
                "Very Positive": 0.0,
            },
            processing_ms=1.23,
        )

    def predict_batch(self, texts):
        return [self.predict(t) for t in texts]


def test_analyze_returns_the_expected_response_shape():
    service = SentimentService(predictor=_FakeBackend())
    result = service.analyze(subject="Hi", body="Thanks a lot!")

    assert result["sentiment"] == "Positive"
    assert result["confidence"] == 0.9
    assert result["model_version"] == MODEL_VERSION
    assert result["processing_ms"] == 1.23
    assert set(result["probabilities"].keys()) == {
        "Very Negative",
        "Negative",
        "Neutral",
        "Positive",
        "Very Positive",
    }


def test_analyze_preprocesses_before_predicting():
    """Confirms the backend receives cleaned text (subject+body combined,
    run through EmailPreprocessor(SENTIMENT_CONFIG)), not the raw request
    fields directly -- e.g. HTML/quote stripping should have already run."""
    backend = _FakeBackend()
    service = SentimentService(predictor=backend)

    service.analyze(subject="Re: Update", body="<p>Thanks!</p>")

    assert backend.last_text is not None
    assert "<p>" not in backend.last_text
    assert "Re: Update" in backend.last_text or "update" in backend.last_text.lower()


def test_analyze_handles_empty_subject():
    service = SentimentService(predictor=_FakeBackend())
    result = service.analyze(subject="", body="Just the body.")
    assert result["sentiment"] == "Positive"


def test_get_sentiment_service_returns_a_singleton():
    from app.services.sentiment_service import get_sentiment_service

    get_sentiment_service.cache_clear()
    try:
        a = get_sentiment_service()
        b = get_sentiment_service()
        assert a is b
    finally:
        get_sentiment_service.cache_clear()
