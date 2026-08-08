"""
Production inference wrapper for intent detection (Module 7).

Differs from CategoryPredictor in the same way IntentMLPipeline differs
from CategoryMLPipeline: takes plain text, not an email_record dict (no
metadata features to pass through). predict_proba returns independent
per-intent probabilities that don't sum to 1 (multi-label, FR-34), same
reasoning as CategoryPredictor. predict() may return an empty label list --
a legitimate output here (see intent_pipeline.py), unlike Category which
always has a "General" fallback to fall back on at the SERVICE layer.
"""

import time

from app.inference.prediction_models import MultiLabelPredictionResult
from app.training.artifact_manager import ArtifactManager


class IntentPredictor:
    """Loads the trained IntentMLPipeline once and reuses it for all
    incoming prediction requests."""

    def __init__(self, model_path: str, artifact_dir: str = "artifacts"):
        artifact_manager = ArtifactManager(artifact_dir=artifact_dir)

        self.pipeline = artifact_manager.load_model(model_path)
        self.classes = list(self.pipeline.classes_)

    def predict(self, text: str) -> MultiLabelPredictionResult:
        start = time.perf_counter()

        probabilities = self.pipeline.predict_proba([text])[0]
        predicted_labels = self.pipeline.predict([text])[0]

        processing_ms = (time.perf_counter() - start) * 1000

        all_scores = {
            str(cls): round(float(prob), 4)
            for cls, prob in zip(self.classes, probabilities, strict=True)
        }
        label_confidences = {label: all_scores[label] for label in predicted_labels}

        return MultiLabelPredictionResult(
            labels=list(predicted_labels),
            label_confidences=label_confidences,
            all_scores=all_scores,
            processing_ms=round(processing_ms, 2),
        )

    def predict_batch(self, texts: list[str]) -> list[MultiLabelPredictionResult]:
        start = time.perf_counter()

        probabilities_matrix = self.pipeline.predict_proba(texts)
        predictions = self.pipeline.predict(texts)

        processing_ms = (time.perf_counter() - start) * 1000
        avg_time = round(processing_ms / len(texts), 2) if texts else 0.0

        results = []
        for predicted_labels, probabilities in zip(predictions, probabilities_matrix, strict=True):
            all_scores = {
                str(cls): round(float(prob), 4)
                for cls, prob in zip(self.classes, probabilities, strict=True)
            }
            label_confidences = {label: all_scores[label] for label in predicted_labels}
            results.append(
                MultiLabelPredictionResult(
                    labels=list(predicted_labels),
                    label_confidences=label_confidences,
                    all_scores=all_scores,
                    processing_ms=avg_time,
                )
            )
        return results
