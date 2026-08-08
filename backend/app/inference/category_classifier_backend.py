"""
Dependency-inversion boundary for email categorization backends.

Same motivation as PriorityClassifierBackend/SpamClassifierBackend: a
CategoryService should not need to change when the model behind it changes
from a classical One-vs-Rest baseline to a fine-tuned transformer (PRD
Sec9.1 names both as the baseline/production pair). A separate Protocol, not
shared with priority's: categorization returns a MultiLabelPredictionResult
(a list of assigned labels + a distribution over all 8), which has no
`positive_label` (spam's shape) or single scalar `label` (priority's shape)
— the return type itself is the reason this can't reuse either existing
Protocol.
"""

from typing import Protocol, runtime_checkable

from app.inference.prediction_models import MultiLabelPredictionResult


@runtime_checkable
class CategoryClassifierBackend(Protocol):
    """
    Anything that can turn an already-cleaned email record into a set of
    category assignments (Support/Sales/Billing/Legal/HR/IT/Marketing/General).

    Implementations: CategoryPredictor (TF-IDF + engineered features + One-
    vs-Rest classical ML, current). Future: a transformer-based multi-label
    classifier with the same shape.
    """

    def predict(self, email_record: dict) -> MultiLabelPredictionResult:
        ...

    def predict_batch(self, email_records: list[dict]) -> list[MultiLabelPredictionResult]:
        ...
