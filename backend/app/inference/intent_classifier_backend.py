"""
Dependency-inversion boundary for intent detection backends.

Same motivation as CategoryClassifierBackend: IntentService should not need
to change when the model behind it changes. Returns MultiLabelPredictionResult
(reused as-is from Category, see prediction_models.py) since FR-34's output
shape is structurally identical -- a set of assigned labels + a distribution
over all 9. Takes plain `text`, not an `email_record` dict, unlike
CategoryClassifierBackend -- IntentMLPipeline is TF-IDF-only (no metadata
features), so there is nothing else for a backend to consume. See
docs/architecture_intent.md for why.
"""

from typing import Protocol, runtime_checkable

from app.inference.prediction_models import MultiLabelPredictionResult


@runtime_checkable
class IntentClassifierBackend(Protocol):
    """
    Anything that can turn already-cleaned email text into a set of intent
    assignments (Complaint/Inquiry/Request/Feedback/Escalation/Order/
    Cancel/Refund/Schedule).

    Implementations: IntentPredictor (TF-IDF + One-vs-Rest classical ML,
    current). Future: a transformer-based multi-label classifier trained on
    real annotated data, same shape.
    """

    def predict(self, text: str) -> MultiLabelPredictionResult: ...

    def predict_batch(self, texts: list[str]) -> list[MultiLabelPredictionResult]: ...
