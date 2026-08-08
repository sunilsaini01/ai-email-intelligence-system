"""
Dependency-inversion boundary for sentiment classification backends.

Same motivation as classifier_backend.py/priority_classifier_backend.py: the
service layer should not need to change if the model behind it changes. A
separate Protocol from PriorityClassifierBackend, not a shared one, for the
same reason priority didn't share spam's: `predict()` here does not need any
of priority's metadata fields (`sender_email`, `received_at`, ...) -- VADER
is a pure text scorer, so the input contract is narrower, not just relabeled.

Unlike every other *ClassifierBackend in this codebase, an implementation of
this Protocol is not required to have been "trained" at all -- see
VaderSentimentPredictor, which wraps a lexicon lookup, not a fitted sklearn
estimator. The Protocol doesn't encode that difference (predict() -> a
PredictionResult is identical either way); it's a fact about the
implementation, not the interface.
"""

from typing import Protocol, runtime_checkable

from app.inference.prediction_models import PredictionResult


@runtime_checkable
class SentimentClassifierBackend(Protocol):
    """
    Anything that can turn raw email text into a sentiment prediction
    (Very Negative / Negative / Neutral / Positive / Very Positive).

    Implementations: VaderSentimentPredictor (lexicon-based, zero-shot,
    served default -- see docs/data_audit_sentiment.md). Future: a
    classifier trained on real annotated email sentiment, once that data
    exists.
    """

    def predict(self, text: str) -> PredictionResult: ...

    def predict_batch(self, texts: list[str]) -> list[PredictionResult]: ...
