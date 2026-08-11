from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import ComplementNB, MultinomialNB
from sklearn.svm import LinearSVC

from app.pipeline.pipeline_config import PipelineConfig


class PipelineFactory:
    """
    Factory responsible for creating machine learning models.
    """

    @staticmethod
    def create_model(
        X_train=None,
        y_train=None,
        config: PipelineConfig = None,
        build_only: bool = False,
    ):
        """
        Create a classifier.

        When build_only=True:
            Returns an untrained classifier.

        When build_only=False:
            (Reserved for future use.)
        """

        if config.model_type == "logistic_regression":

            return LogisticRegression(
                C=config.lr_C,
                penalty=config.lr_penalty,
                solver="saga",
                max_iter=config.lr_max_iter,
                class_weight=config.class_weight,
                random_state=config.random_state,
            )

        elif config.model_type == "naive_bayes":

            if config.nb_variant == "multinomial":
                return MultinomialNB(
                    alpha=config.nb_alpha,
                )

            return ComplementNB(
                alpha=config.nb_alpha,
            )

        elif config.model_type == "svm":

            base_model = LinearSVC(
                C=config.svm_C,
                max_iter=config.svm_max_iter,
                class_weight=config.class_weight,
                random_state=config.random_state,
            )

            return CalibratedClassifierCV(
                estimator=base_model,
                method="sigmoid",
                cv=3,
            )

        raise ValueError(
            f"Unsupported model type: {config.model_type}"
        )