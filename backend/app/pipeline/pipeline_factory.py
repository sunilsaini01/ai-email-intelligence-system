from app.pipeline.pipeline_config import PipelineConfig

from app.ml_models.logistic_regression_model import (
    train_logistic_regression,
)

from app.ml_models.naive_bayes_model import (
    train_naive_bayes,
)

from app.ml_models.svm_model import (
    train_svm,
)


class PipelineFactory:
    """
    Factory responsible for creating and training
    machine learning models.
    """

    @staticmethod
    def create_model(
        X_train,
        y_train,
        config: PipelineConfig,
    ):
        """
        Train and return the selected model.
        """

        if config.model_type == "logistic_regression":

            return train_logistic_regression(
                X_train=X_train,
                y_train=y_train,
                C=config.lr_C,
                penalty=config.lr_penalty,
                max_iter=config.lr_max_iter,
                class_weight=config.class_weight,
            )

        elif config.model_type == "naive_bayes":

            return train_naive_bayes(
                X_train=X_train,
                y_train=y_train,
                alpha=config.nb_alpha,
                variant=config.nb_variant,
            )

        elif config.model_type == "svm":

            return train_svm(
                X_train=X_train,
                y_train=y_train,
                C=config.svm_C,
                max_iter=config.svm_max_iter,
                class_weight=config.class_weight,
            )

        else:

            raise ValueError(
                f"Unsupported model type: {config.model_type}"
            )