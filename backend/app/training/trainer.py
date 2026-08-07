from pathlib import Path

from app.pipeline.ml_pipeline import MLPipeline
from app.pipeline.pipeline_config import PipelineConfig


class Trainer:
    """
    Responsible for training, evaluating,
    saving and loading ML pipelines.
    """

    def __init__(
        self,
        config: PipelineConfig,
        pipeline_cls: type = MLPipeline,
    ):
        """
        `pipeline_cls` defaults to MLPipeline (spam's TF-IDF-only pipeline) —
        existing callers are unaffected. Pass PriorityMLPipeline (or any
        class implementing fit/predict/predict_proba/save/load) to reuse
        this same Trainer for a pipeline that also needs engineered
        features — see app/pipeline/priority_pipeline.py.
        """
        self.config = config
        self.pipeline = pipeline_cls(config)

    def train(
        self,
        X_train,
        y_train,
    ):
        """
        Train the pipeline.
        """

        self.pipeline.fit(
            X_train=X_train,
            y_train=y_train,
        )

        return self.pipeline

    def predict(
        self,
        X,
    ):
        """
        Predict labels.
        """

        return self.pipeline.predict(X)

    def predict_proba(
        self,
        X,
    ):
        """
        Predict probabilities.
        """

        return self.pipeline.predict_proba(X)

    def save_model(
        self,
        path: str | Path,
    ):
        """
        Save trained pipeline.
        """

        self.pipeline.save(path)

    def load_model(
        self,
        path: str | Path,
    ):
        """
        Load trained pipeline.
        """

        self.pipeline.load(path)

        return self.pipeline