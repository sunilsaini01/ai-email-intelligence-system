"""
Spam classification service.

Wraps the trained SpamPredictor with the operating threshold chosen during
training (see scripts/train_spam_model.py) and the raw-email cleaning step,
so the API layer only deals with request/response schemas.

Why a module-level cache, not per-request construction:
    Loading the model artifact and the spaCy-backed EmailPreprocessor is
    expensive (disk I/O + model deserialization). Both are stateless once
    built, so one instance is built lazily on first use and reused for the
    lifetime of the process — the same reasoning as Settings/get_settings.
"""

import json
from functools import lru_cache
from pathlib import Path

from app.inference.spam_predictor import SpamPredictor
from app.preprocessing.email_preprocessor import SPAM_CONFIG, EmailPreprocessor

MODEL_FILENAME = "spam_baseline.joblib"
METRICS_FILENAME = "spam_baseline_metrics.json"
DEFAULT_THRESHOLD = 0.5

# Resolved relative to this file, not the process's cwd — the model must load the
# same way whether the app is started from the repo root, from backend/, or by
# pytest, all of which are legitimate ways this project gets run today.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_ARTIFACT_DIR = str(_REPO_ROOT / "artifacts")


class SpamServiceUnavailable(RuntimeError):
    """Raised when the trained spam model artifact hasn't been produced yet."""


class SpamService:
    def __init__(self, artifact_dir: str = _DEFAULT_ARTIFACT_DIR):
        model_path = Path(artifact_dir) / MODEL_FILENAME

        if not model_path.exists():
            raise SpamServiceUnavailable(
                f"No trained spam model found at {model_path}. "
                "Run `python backend/scripts/train_spam_model.py` from the repo root first."
            )

        self.predictor = SpamPredictor(MODEL_FILENAME, artifact_dir=artifact_dir)
        self.preprocessor = EmailPreprocessor(SPAM_CONFIG)
        self.threshold, self.model_version = self._load_threshold(artifact_dir)

    @staticmethod
    def _load_threshold(artifact_dir: str) -> tuple[float, str]:
        metrics_path = Path(artifact_dir) / METRICS_FILENAME
        if not metrics_path.exists():
            return DEFAULT_THRESHOLD, "unknown"

        data = json.loads(metrics_path.read_text(encoding="utf-8"))
        return float(data.get("decision_threshold", DEFAULT_THRESHOLD)), str(
            data.get("best_model", "unknown")
        )

    def classify(self, subject: str, body: str) -> dict:
        cleaned = self.preprocessor.process(f"{subject} {body}".strip())

        result = self.predictor.predict({"body_clean": cleaned})

        spam_score = result.probabilities.get("1", 0.0)
        is_spam = spam_score >= self.threshold

        return {
            "is_spam": is_spam,
            "status": "quarantined" if is_spam else "clear",
            "confidence": result.confidence,
            "spam_score": spam_score,
            "threshold_used": self.threshold,
            "model_version": self.model_version,
            "processing_ms": result.processing_ms,
        }


@lru_cache
def get_spam_service() -> SpamService:
    return SpamService()
