"""
Dependency-inversion boundary for spam classification backends.

Why this exists (Module 13 — future-proof design):
    SpamService currently talks to SpamPredictor, which wraps a scikit-learn
    Pipeline (TF-IDF + classical model). When a transformer model (DistilBERT
    etc.) replaces it, nothing about email validation, preprocessing,
    threshold policy, quarantine status, or the API contract should need to
    change — only the class that turns cleaned text into a probability.

    Protocol (structural typing) is used instead of an ABC base class so a
    future TransformerSpamClassifier doesn't need to inherit from anything
    in app/inference/ — it only needs to match this shape. That keeps a
    transformers-based module free to have its own class hierarchy.

Why the contract is "text in, PredictionResult out" and nothing more:
    Anything more specific (e.g. exposing the sklearn Pipeline object, or a
    torch Tensor) would leak the implementation into the interface and defeat
    the point. Batch prediction is included because it's a real production
    need (throughput), not because both current implementations happen to
    support it.
"""

from typing import Protocol, runtime_checkable

from app.inference.prediction_models import PredictionResult


@runtime_checkable
class SpamClassifierBackend(Protocol):
    """
    Anything that can turn already-cleaned email text into a spam prediction.

    Implementations: SpamPredictor (TF-IDF + classical ML, current).
    Future: a transformer-based classifier with the same shape.

    `positive_label` matters more than it looks: SpamService reads
    `result.probabilities[backend.positive_label]` to get the spam
    probability for threshold comparison — it does NOT assume "1", "spam",
    or any other specific string. A backend using different class-label
    conventions (a transformer classifier might use "SPAM"/"HAM" instead of
    "1"/"0") only needs to set this correctly; nothing else has to change.
    Getting this wrong silently breaks classification (spam_score reads as
    0.0 for everything) rather than raising, which is exactly why it's a
    required, explicit part of the contract instead of a hardcoded key.
    """

    positive_label: str

    def predict(self, email_record: dict) -> PredictionResult:
        """`email_record` must contain a "body_clean" key with cleaned text."""
        ...

    def predict_batch(self, email_records: list[dict]) -> list[PredictionResult]:
        ...
