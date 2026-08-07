"""
Proves the Module 13 claim: SpamService depends on SpamClassifierBackend
(a Protocol), not on SpamPredictor specifically. A future transformer-based
classifier only needs to match this shape — no inheritance, no API changes.

This test uses a fake backend that returns a fixed prediction, with no model
artifact, no scikit-learn, no SpamAssassin corpus involved — if this passes,
the abstraction boundary is real, not just a docstring claim.
"""

from app.inference.classifier_backend import SpamClassifierBackend
from app.inference.prediction_models import PredictionResult
from app.services.spam_service import SpamService


class FakeAlwaysSpamBackend:
    """Minimal stand-in for a future transformer classifier."""

    positive_label = "1"

    def predict(self, email_record: dict) -> PredictionResult:
        return PredictionResult(
            label="1",
            confidence=0.99,
            probabilities={"0": 0.01, "1": 0.99},
            processing_ms=1.0,
        )

    def predict_batch(self, email_records: list[dict]) -> list[PredictionResult]:
        return [self.predict(r) for r in email_records]


class FakeBackendWithDifferentLabelConvention:
    """
    Uses "SPAM"/"HAM" instead of "1"/"0" — deliberately NOT the convention
    SpamPredictor happens to use. If SpamService ever regresses to reading a
    hardcoded "1" key instead of `backend.positive_label`, this is the test
    that catches it (this exact bug existed and was fixed during review —
    see git history for app/services/spam_service.py).
    """

    positive_label = "SPAM"

    def predict(self, email_record: dict) -> PredictionResult:
        return PredictionResult(
            label="SPAM",
            confidence=0.95,
            probabilities={"HAM": 0.05, "SPAM": 0.95},
            processing_ms=1.0,
        )

    def predict_batch(self, email_records: list[dict]) -> list[PredictionResult]:
        return [self.predict(r) for r in email_records]


def test_fake_backend_satisfies_the_protocol():
    backend = FakeAlwaysSpamBackend()
    assert isinstance(backend, SpamClassifierBackend)


def test_spam_service_works_with_an_injected_backend():
    service = SpamService(predictor=FakeAlwaysSpamBackend())

    result = service.classify(subject="anything", body="anything at all")

    assert result["is_spam"] is True
    assert result["spam_score"] == 0.99


def test_spam_service_respects_backend_specific_positive_label():
    service = SpamService(predictor=FakeBackendWithDifferentLabelConvention())

    result = service.classify(subject="anything", body="anything at all")

    assert result["is_spam"] is True
    assert result["spam_score"] == 0.95
