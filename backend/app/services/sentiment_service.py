"""
Sentiment analysis service (Module 6 / Phase 7A).

No `SentimentServiceUnavailable` / 503 path, for the same reason
summarization's endpoint has none (see app/api/v1/endpoints/summarization.py):
VaderSentimentPredictor has no trained artifact to be missing. There is
nothing analogous to "training script hasn't been run yet." (If the
`vaderSentiment` package itself failed to import, that would surface as an
ImportError at process startup, not a per-request 503 -- same failure class
as `transformers` being missing, not a runtime state this service needs to
guard against per-request.)

No separate threshold/policy layer either, for the same reason priority has
none: this is a single-label argmax decision (VADER's bucketed label IS the
decision) -- see app/inference/sentiment_predictor.py's bucket_compound().
"""

from functools import lru_cache

from app.inference.sentiment_classifier_backend import SentimentClassifierBackend
from app.inference.sentiment_predictor import VaderSentimentPredictor
from app.preprocessing.email_preprocessor import SENTIMENT_CONFIG, EmailPreprocessor

MODEL_VERSION = "vader-lexicon-3.3.2"


class SentimentService:
    """
    Depends on SentimentClassifierBackend (a Protocol), not concretely on
    VaderSentimentPredictor -- same dependency-inversion boundary every
    other module's service uses.
    """

    def __init__(self, predictor: SentimentClassifierBackend | None = None):
        self.predictor = predictor or VaderSentimentPredictor()
        # remove_stopwords=False, lemmatize=False (see SENTIMENT_CONFIG) --
        # negation words and inflection both carry sentiment signal that
        # stopword removal/lemmatization would destroy.
        self.preprocessor = EmailPreprocessor(SENTIMENT_CONFIG)

    def analyze(self, subject: str, body: str) -> dict:
        subject = subject or ""
        text = self.preprocessor.process(f"{subject} {body}".strip())

        result = self.predictor.predict(text)

        return {
            "sentiment": result.label,
            "confidence": result.confidence,
            "probabilities": result.probabilities,
            "model_version": MODEL_VERSION,
            "processing_ms": result.processing_ms,
        }


@lru_cache
def get_sentiment_service() -> SentimentService:
    return SentimentService()
