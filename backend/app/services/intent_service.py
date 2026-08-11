"""
Intent detection service (Module 7 / Phase 7B).

No "General"-style fallback when zero intents cross threshold, unlike
CategoryService -- FR-33 names no default/fallback intent, and this phase
deliberately does not invent one (see docs/intent_taxonomy.md). An empty
`intents` list is a valid, surfaced response.

Also owns FR-35's entity extraction, composed alongside the intent
classification result -- entity extraction (app/nlp/intent_entities.py) is
independent of the trained classifier (regex + spaCy NER, not ML), so it
runs unconditionally regardless of which/how-many intents were detected.
"""

import json
from functools import lru_cache
from pathlib import Path

from app.inference.intent_classifier_backend import IntentClassifierBackend
from app.inference.intent_predictor import IntentPredictor
from app.nlp.intent_entities import extract_intent_entities
from app.preprocessing.email_preprocessor import CATEGORY_CONFIG, EmailPreprocessor

MODEL_FILENAME = "intent_baseline.joblib"
METRICS_FILENAME = "intent_baseline_metrics.json"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_ARTIFACT_DIR = str(_REPO_ROOT / "artifacts")


class IntentServiceUnavailable(RuntimeError):
    """Raised when the trained intent model artifact hasn't been produced yet."""


class IntentService:
    """
    Depends on IntentClassifierBackend (a Protocol), not concretely on
    IntentPredictor -- see app/inference/intent_classifier_backend.py.
    """

    def __init__(
        self,
        artifact_dir: str = _DEFAULT_ARTIFACT_DIR,
        predictor: IntentClassifierBackend | None = None,
    ):
        model_path = Path(artifact_dir) / MODEL_FILENAME

        if predictor is None and not model_path.exists():
            raise IntentServiceUnavailable(
                f"No trained intent model found at {model_path}. "
                "Run `python backend/scripts/train_intent_model.py` from the repo root first."
            )

        self.predictor = predictor or IntentPredictor(MODEL_FILENAME, artifact_dir=artifact_dir)
        # Reuses CATEGORY_CONFIG -- see train_intent_model.py's module
        # docstring for why no dedicated INTENT_CONFIG was created.
        self.preprocessor = EmailPreprocessor(CATEGORY_CONFIG)
        self.model_version = self._load_model_version(artifact_dir)

    @staticmethod
    def _load_model_version(artifact_dir: str) -> str:
        metrics_path = Path(artifact_dir) / METRICS_FILENAME
        if not metrics_path.exists():
            return "unknown"
        data = json.loads(metrics_path.read_text(encoding="utf-8"))
        return str(data.get("model_version", "unknown"))

    def analyze(self, subject: str, body: str) -> dict:
        subject = subject or ""
        raw_combined = f"{subject} {body}".strip()
        cleaned = self.preprocessor.process(raw_combined)

        result = self.predictor.predict(cleaned)

        # FR-35 entities are extracted from the RAW text, not the cleaned/
        # lemmatized text the classifier sees -- lemmatization would mangle
        # order IDs, dates, and names (e.g. "Smith" un-lemmatized is fine,
        # but a regex-matched order ID token could be corrupted by the
        # tokenize-filter-rejoin pass). Same "raw text in, cleaned text only
        # for the classifier" separation FR-26's grounding check already
        # established for summarization.
        entities = extract_intent_entities(raw_combined)

        return {
            "intents": [
                {"intent": label, "confidence": result.label_confidences[label]}
                for label in result.labels
            ],
            "all_scores": result.all_scores,
            "entities": {
                "order_ids": entities.order_ids,
                "dates": entities.dates,
                "monetary_amounts": entities.monetary_amounts,
                "person_names": entities.person_names,
                "product_names": entities.product_names,
            },
            "model_version": self.model_version,
            "processing_ms": result.processing_ms,
        }


@lru_cache
def get_intent_service() -> IntentService:
    return IntentService()
