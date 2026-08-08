"""
Email categorization service (Module 4).

Owns one policy decision PriorityService's docstring already established
the pattern for (spam's threshold, priority's "no policy layer needed"):
what to do when the One-vs-Rest classifier assigns ZERO categories to an
email. That's a legitimate model output (every binary classifier said "no"),
but FR-21's taxonomy defines General as the fallback for exactly this case
(docs/data_audit_categorization.md §3) — so if the model's own labels come
back empty, this service assigns ["General"] using the model's own
(sub-threshold) General score as the reported confidence, rather than
exposing a category-less response no caller should have to special-case.
"""

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from app.inference.category_classifier_backend import CategoryClassifierBackend
from app.inference.category_predictor import CategoryPredictor
from app.preprocessing.email_preprocessor import CATEGORY_CONFIG, EmailPreprocessor

MODEL_FILENAME = "category_baseline.joblib"
METRICS_FILENAME = "category_baseline_metrics.json"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_ARTIFACT_DIR = str(_REPO_ROOT / "artifacts")


class CategoryServiceUnavailable(RuntimeError):
    """Raised when the trained category model artifact hasn't been produced yet."""


class CategoryService:
    """
    Depends on CategoryClassifierBackend (a Protocol), not concretely on
    CategoryPredictor — see app/inference/category_classifier_backend.py.
    """

    def __init__(
        self,
        artifact_dir: str = _DEFAULT_ARTIFACT_DIR,
        predictor: CategoryClassifierBackend | None = None,
    ):
        model_path = Path(artifact_dir) / MODEL_FILENAME

        if predictor is None and not model_path.exists():
            raise CategoryServiceUnavailable(
                f"No trained category model found at {model_path}. "
                "Run `python backend/scripts/train_category_model.py` from the repo root first."
            )

        self.predictor = predictor or CategoryPredictor(MODEL_FILENAME, artifact_dir=artifact_dir)
        self.preprocessor = EmailPreprocessor(CATEGORY_CONFIG)
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

        labels = result.labels
        label_confidences = result.label_confidences

        # General-fallback safety net — see module docstring. Only triggers
        # when every one of the 8 binary classifiers said "no"; does not
        # override a model that positively assigned other categories.
        if not labels:
            general_score = result.all_scores.get("General", 0.0)
            labels = ["General"]
            label_confidences = {"General": general_score}

        return {
            "categories": [
                {"category": label, "confidence": label_confidences[label]} for label in labels
            ],
            "all_scores": result.all_scores,
            "model_version": self.model_version,
            "processing_ms": result.processing_ms,
        }


@lru_cache
def get_category_service() -> CategoryService:
    return CategoryService()
