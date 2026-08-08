"""
Production inference wrapper for email categorization (Module 4).

Differs from PriorityPredictor in the same structural way CategoryMLPipeline
differs from PriorityMLPipeline: predict_proba returns an (n_labels,) array
of INDEPENDENT per-category probabilities that don't sum to 1, not a single
softmax distribution — because this is multi-label (FR-22), not single-label
argmax. `predict()` applies each binary classifier's own decision threshold
(scikit-learn's OneVsRestClassifier default), which may assign zero
categories to a row — that's a legitimate model output, not an error; the
General-fallback safety net for that case is a business-policy decision that
lives in CategoryService, not here (same separation as SpamService owning
the threshold rather than SpamPredictor).
"""

import time

from app.inference.prediction_models import MultiLabelPredictionResult
from app.training.artifact_manager import ArtifactManager


class CategoryPredictor:
    """Loads the trained CategoryMLPipeline once and reuses it for all
    incoming prediction requests."""

    def __init__(self, model_path: str, artifact_dir: str = "artifacts"):
        artifact_manager = ArtifactManager(artifact_dir=artifact_dir)

        self.pipeline = artifact_manager.load_model(model_path)
        self.classes = list(self.pipeline.classes_)

    def predict(self, email_record: dict) -> MultiLabelPredictionResult:
        start = time.perf_counter()

        probabilities = self.pipeline.predict_proba([email_record])[0]
        predicted_labels = self.pipeline.predict([email_record])[0]

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

    def predict_batch(self, email_records: list[dict]) -> list[MultiLabelPredictionResult]:
        start = time.perf_counter()

        probabilities_matrix = self.pipeline.predict_proba(email_records)
        predictions = self.pipeline.predict(email_records)

        processing_ms = (time.perf_counter() - start) * 1000
        avg_time = round(processing_ms / len(email_records), 2)

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
