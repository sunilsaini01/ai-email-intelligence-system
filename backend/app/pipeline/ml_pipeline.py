import joblib

from app.pipeline.pipeline_config import PipelineConfig
from app.pipeline.pipeline_factory import PipelineFactory


class MLPipeline:
    """
    Unified Machine Learning Pipeline.
    """

    def __init__(self, config: PipelineConfig):

        self.config = config
        self.model = None

    def fit(
        self,
        X_train,
        y_train,
    ):
        """
        Train the selected model.
        """

        self.model = PipelineFactory.create_model(
            X_train=X_train,
            y_train=y_train,
            config=self.config,
        )

        return self

    def predict(
        self,
        X,
    ):
        """
        Predict labels.
        """

        return self.model.predict(X)

    def predict_proba(
        self,
        X,
    ):
        """
        Predict probabilities.
        """

        return self.model.predict_proba(X)

    def save(
        self,
        path: str,
    ):
        """
        Save model.
        """

        joblib.dump(
            self.model,
            path,
        )

    def load(
        self,
        path: str,
    ):
        """
        Load model.
        """

        self.model = joblib.load(path)

        return self