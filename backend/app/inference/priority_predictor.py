"""
Production inference wrapper for priority classification (Module 3).

Differs from SpamPredictor in exactly one structural way: PriorityMLPipeline
takes a list of RECORDS (dicts with body_clean/subject_raw/received_at/...),
not a list of pre-vectorized strings — because FR-17 requires metadata
features alongside text (see app/pipeline/priority_pipeline.py), whereas
spam's pipeline is text-only. Everything else — load once, reuse, expose the
same PredictionResult shape — mirrors SpamPredictor deliberately, so
PriorityService reads the same way SpamService does.
"""

import time

from app.inference.prediction_models import PredictionResult
from app.training.artifact_manager import ArtifactManager


class PriorityPredictor:
    """
    Loads the trained PriorityMLPipeline once and reuses it for all incoming
    prediction requests.
    """

    # No single "positive_label" the way SpamClassifierBackend needs one —
    # priority is 4-class argmax, not a binary threshold decision. See
    # app/inference/priority_classifier_backend.py's Protocol docstring.

    def __init__(self, model_path: str, artifact_dir: str = "artifacts"):
        artifact_manager = ArtifactManager(artifact_dir=artifact_dir)

        self.pipeline = artifact_manager.load_model(model_path)
        self.classes = list(self.pipeline.classes_)

    def predict(self, email_record: dict) -> PredictionResult:
        start = time.perf_counter()

        probabilities = self.pipeline.predict_proba([email_record])[0]
        prediction = self.pipeline.predict([email_record])[0]

        confidence = float(max(probabilities))
        processing_ms = (time.perf_counter() - start) * 1000

        return PredictionResult(
            label=str(prediction),
            confidence=round(confidence, 4),
            probabilities={
                str(cls): round(float(prob), 4)
                for cls, prob in zip(self.classes, probabilities, strict=True)
            },
            processing_ms=round(processing_ms, 2),
        )

    def predict_batch(self, email_records: list[dict]) -> list[PredictionResult]:
        start = time.perf_counter()

        probabilities_matrix = self.pipeline.predict_proba(email_records)
        predictions = self.pipeline.predict(email_records)

        processing_ms = (time.perf_counter() - start) * 1000
        avg_time = round(processing_ms / len(email_records), 2)

        results = []
        for prediction, probabilities in zip(predictions, probabilities_matrix, strict=True):
            confidence = float(max(probabilities))
            results.append(
                PredictionResult(
                    label=str(prediction),
                    confidence=round(confidence, 4),
                    probabilities={
                        str(cls): round(float(prob), 4)
                        for cls, prob in zip(self.classes, probabilities, strict=True)
                    },
                    processing_ms=avg_time,
                )
            )
        return results
