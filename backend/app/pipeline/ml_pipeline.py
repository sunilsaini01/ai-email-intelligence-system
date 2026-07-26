import joblib

from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer

from app.pipeline.pipeline_config import PipelineConfig
from app.pipeline.pipeline_factory import PipelineFactory


class MLPipeline:
    """
    End-to-end Machine Learning Pipeline.

    Raw Email
        ↓
    TF-IDF Vectorizer
        ↓
    Classifier
    """

    def __init__(self, config: PipelineConfig):

        self.config = config
        self.pipeline = None

    def fit(
        self,
        X_train,
        y_train,
    ):
        """
        Train the complete pipeline.
        """

        classifier = PipelineFactory.create_model(
            X_train=None,
            y_train=None,
            config=self.config,
            build_only=True,
        )

        self.pipeline = Pipeline(
            [
                (
                    "tfidf",
                    TfidfVectorizer(
                        max_features=self.config.tfidf_max_features,
                        ngram_range=self.config.tfidf_ngram_range,
                        sublinear_tf=self.config.tfidf_sublinear_tf,
                        min_df=1,
                    ),
                ),
                (
                    "classifier",
                    classifier,
                ),
            ]
        )

        self.pipeline.fit(
            X_train,
            y_train,
        )

        return self

    def predict(
        self,
        X,
    ):

        return self.pipeline.predict(X)

    def predict_proba(
        self,
        X,
    ):

        return self.pipeline.predict_proba(X)

    def save(
        self,
        path: str,
    ):

        joblib.dump(
            self.pipeline,
            path,
        )

    def load(
        self,
        path: str,
    ):

        self.pipeline = joblib.load(path)

        return self