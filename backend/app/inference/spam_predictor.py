import time

from app.inference.prediction_models import PredictionResult
from app.training.artifact_manager import ArtifactManager


class SpamPredictor:
    """
    Production inference wrapper.

    Loads the trained pipeline once and reuses it
    for all incoming prediction requests.
    """

    # Matches app/inference/classifier_backend.py's SpamClassifierBackend contract.
    # "1" specifically because scripts/train_spam_model.py encodes spam=1, ham=0
    # (df["label"] = (df["spam_label"] == "spam").astype(int)) — not a general
    # property of sklearn classifiers, a fact about how THIS model was trained.
    positive_label = "1"

    def __init__(self, model_path: str, artifact_dir: str = "artifacts"):
        artifact_manager = ArtifactManager(artifact_dir=artifact_dir)

        self.pipeline = artifact_manager.load_model(model_path)
        self.classes = self.pipeline.pipeline.classes_

    def predict(
        self,
        email_record: dict,
    ) -> PredictionResult:
        """
        Predict a single email.
        """

        start = time.perf_counter()

        probabilities = self.pipeline.predict_proba(
            [email_record["body_clean"]]
        )[0]

        prediction = self.pipeline.predict(
            [email_record["body_clean"]]
        )[0]

        confidence = float(max(probabilities))

        processing_ms = (
            time.perf_counter() - start
        ) * 1000

        return PredictionResult(
            label=str(prediction),
            confidence=round(confidence, 4),
            probabilities={
                str(cls): round(float(prob), 4)
                for cls, prob in zip(
                    self.classes,
                    probabilities,
                    strict=True,
                )
            },
            processing_ms=round(processing_ms, 2),
        )
        
    def predict_batch(
        self,
        email_records: list[dict],
    ) -> list[PredictionResult]:
        """
        Predict multiple emails in a single pipeline call.
        """

        start = time.perf_counter()

        texts = [record["body_clean"] for record in email_records]

        probabilities_matrix = self.pipeline.predict_proba(texts)

        predictions = self.pipeline.predict(texts)

        processing_ms = (
        time.perf_counter() - start
        ) * 1000

        results = []

        avg_time = round(
        processing_ms / len(email_records),
        2,
        )

        for prediction, probabilities in zip(
        predictions,
        probabilities_matrix,
        strict=True,
        ):
            confidence = float(max(probabilities))

            results.append(
                PredictionResult(
                    label=str(prediction),
                    confidence=round(confidence, 4),
                    probabilities={
                        str(cls): round(float(prob), 4)
                        for cls, prob in zip(
                            self.classes,
                            probabilities,
                            strict=True,
                        )
                    },
                    processing_ms=avg_time,
                )
            )

        return results