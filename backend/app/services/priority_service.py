"""
Priority classification service (Module 3).

Simpler than SpamService in one respect: priority has no separate
threshold/policy layer. Spam's threshold exists because a single
probability gets compared against a business-chosen cutoff (recall-first,
FR-11). Priority is a 4-class argmax decision — the model's predicted label
already IS the decision; there's nothing analogous to "quarantine vs. clear"
sitting on top of it. If a future need arises to bias toward e.g. never
under-predicting Critical, that policy would live here, the same way spam's
threshold does — not in the model.
"""

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from app.inference.priority_classifier_backend import PriorityClassifierBackend
from app.inference.priority_predictor import PriorityPredictor
from app.preprocessing.email_preprocessor import PRIORITY_CONFIG, EmailPreprocessor

MODEL_FILENAME = "priority_baseline.joblib"
METRICS_FILENAME = "priority_baseline_metrics.json"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_ARTIFACT_DIR = str(_REPO_ROOT / "artifacts")


class PriorityServiceUnavailable(RuntimeError):
    """Raised when the trained priority model artifact hasn't been produced yet."""


class PriorityService:
    """
    Depends on PriorityClassifierBackend (a Protocol), not concretely on
    PriorityPredictor — see app/inference/priority_classifier_backend.py.
    """

    def __init__(
        self,
        artifact_dir: str = _DEFAULT_ARTIFACT_DIR,
        predictor: PriorityClassifierBackend | None = None,
    ):
        model_path = Path(artifact_dir) / MODEL_FILENAME

        if predictor is None and not model_path.exists():
            raise PriorityServiceUnavailable(
                f"No trained priority model found at {model_path}. "
                "Run `python backend/scripts/train_priority_model.py` from the repo root first."
            )

        self.predictor = predictor or PriorityPredictor(MODEL_FILENAME, artifact_dir=artifact_dir)
        self.preprocessor = EmailPreprocessor(PRIORITY_CONFIG)
        self.model_version = self._load_model_version(artifact_dir)

    @staticmethod
    def _load_model_version(artifact_dir: str) -> str:
        metrics_path = Path(artifact_dir) / METRICS_FILENAME
        if not metrics_path.exists():
            return "unknown"
        data = json.loads(metrics_path.read_text(encoding="utf-8"))
        return str(data.get("model_version", "unknown"))

    def classify(
        self,
        subject: str,
        body: str,
        sender_email: str = "",
        received_at: datetime | None = None,
        recipient_to: list[str] | None = None,
        recipient_cc: list[str] | None = None,
        is_reply: bool | None = None,
        is_forward: bool | None = None,
        has_attachments: bool = False,
        attachment_count: int = 0,
    ) -> dict:
        subject = subject or ""
        subject_lower = subject.strip().lower()

        record = {
            "body_clean": self.preprocessor.process(f"{subject} {body}".strip()),
            "subject_raw": subject,
            "sender_email": sender_email,
            "received_at": received_at or datetime.now(UTC),
            "recipient_to": recipient_to or [],
            "recipient_cc": recipient_cc or [],
            # Auto-derive from the subject line when the caller doesn't know
            # (or hasn't bothered to say) — same rule the synthetic dataset
            # generator and training script use, so train/serve stay
            # consistent (docs/data_audit_priority.md §5).
            "is_reply": is_reply if is_reply is not None else subject_lower.startswith("re:"),
            "is_forward": (
                is_forward
                if is_forward is not None
                else subject_lower.startswith(("fwd:", "fw:"))
            ),
            "thread_depth": 0,
            "has_attachments": has_attachments,
            "attachment_count": attachment_count,
        }

        result = self.predictor.predict(record)

        return {
            "priority": result.label,
            "confidence": result.confidence,
            "probabilities": result.probabilities,
            "model_version": self.model_version,
            "processing_ms": result.processing_ms,
        }


@lru_cache
def get_priority_service() -> PriorityService:
    return PriorityService()
