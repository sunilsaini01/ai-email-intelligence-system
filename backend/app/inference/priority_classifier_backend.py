"""
Dependency-inversion boundary for priority classification backends.

Same motivation as app/inference/classifier_backend.py (SpamClassifierBackend):
PriorityService should not need to change when the model behind it changes
from a classical baseline to a fine-tuned transformer. A separate Protocol
from SpamClassifierBackend, not a shared one, because the contracts
genuinely differ: spam is a binary decision compared against a tunable
threshold (needs `positive_label` to know which probability to compare), and
priority is a 4-class argmax decision (the predicted label IS the decision —
there's no separate threshold-policy layer sitting on top of it). Forcing
both into one Protocol would mean adding a meaningless `positive_label` to
every priority backend just to satisfy an interface it doesn't need.

`email_record` must contain a "body_clean" key with cleaned text, same as
spam — but ALSO the metadata keys PriorityMLPipeline needs (subject_raw,
sender_email, received_at, recipient_to, recipient_cc, is_reply, is_forward,
thread_depth, has_attachments, attachment_count). See
app/services/priority_service.py for where that dict gets built.
"""

from typing import Protocol, runtime_checkable

from app.inference.prediction_models import PredictionResult


@runtime_checkable
class PriorityClassifierBackend(Protocol):
    """
    Anything that can turn an already-cleaned email record into a priority
    prediction (Critical/High/Medium/Low).

    Implementations: PriorityPredictor (TF-IDF + engineered features +
    classical ML, current). Future: a transformer-based classifier with the
    same shape.
    """

    def predict(self, email_record: dict) -> PredictionResult:
        ...

    def predict_batch(self, email_records: list[dict]) -> list[PredictionResult]:
        ...
