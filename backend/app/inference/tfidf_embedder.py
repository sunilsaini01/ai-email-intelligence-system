"""
TF-IDF baseline embedder (Module 9 / Phase 9 Step 8's "baseline first").

Mirrors PRD §9.1's own framing of this exact module: "Email Embeddings |
TF-IDF vectors (baseline) | all-MiniLM-L6-v2 (production)" -- this is the
baseline, `minilm_embedder.py` is the production comparison, and
docs/embedding_model_decision.md documents the actual measured comparison
between them, not an assumption that the transformer wins by default.

No trained-artifact-missing 503 path unlike Spam/Priority/Category/Intent
would suggest at first glance -- wait, this DOES have an artifact
(`tfidf_embedder.joblib`, produced by scripts/train_tfidf_embedder.py) and
DOES raise if it's missing, same pattern as those four modules -- unlike
Sentiment (zero-shot, no artifact at all).
"""

import json
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer

from app.training.artifact_manager import ArtifactManager

MODEL_FILENAME = "tfidf_embedder.joblib"
METRICS_FILENAME = "tfidf_embedder_metrics.json"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_ARTIFACT_DIR = str(_REPO_ROOT / "artifacts")


class TfidfEmbedderUnavailable(RuntimeError):
    """Raised when the fitted TF-IDF vectorizer artifact hasn't been produced yet."""


class TfidfEmbedder:
    def __init__(self, artifact_dir: str = _DEFAULT_ARTIFACT_DIR):
        model_path = Path(artifact_dir) / MODEL_FILENAME
        if not model_path.exists():
            raise TfidfEmbedderUnavailable(
                f"No fitted TF-IDF embedder found at {model_path}. "
                "Run `python backend/scripts/train_tfidf_embedder.py` from the repo root first."
            )

        self._vectorizer: TfidfVectorizer = ArtifactManager(artifact_dir).load_model(MODEL_FILENAME)
        self.dimension = len(self._vectorizer.get_feature_names_out())
        self.model_version = self._load_version(artifact_dir)

    @staticmethod
    def _load_version(artifact_dir: str) -> str:
        metrics_path = Path(artifact_dir) / METRICS_FILENAME
        if not metrics_path.exists():
            return "unknown"
        data = json.loads(metrics_path.read_text(encoding="utf-8"))
        return str(data.get("model_version", "unknown"))

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # TfidfVectorizer(norm="l2") at fit time -> already L2-normalized;
        # .toarray() densifies (max_features caps this at a fixed, small
        # width -- see train_tfidf_embedder.py's module docstring).
        matrix = self._vectorizer.transform(texts)
        return matrix.toarray().tolist()
