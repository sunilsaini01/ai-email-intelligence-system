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

            base_model = LogisticRegression(
                C=config.lr_C,
                penalty=config.lr_penalty,
                solver="saga",
                max_iter=config.lr_max_iter,
                class_weight=config.class_weight,
                random_state=config.random_state,
            )

            # CalibratedClassifierCV, method="isotonic" -- NOT "sigmoid"
            # despite that being the "svm" branch's own choice below.
            # Logistic regression is often ASSUMED to need no calibration
            # at all since it directly optimizes log-loss, but that
            # assumption specifically breaks down under
            # class_weight="balanced" (this config's own default -- see
            # PipelineConfig's own comment on why), which reweights the
            # loss function -- a documented scikit-learn caveat for
            # exactly this situation. Measured directly, not assumed
            # (scripts/check_priority_calibration.py against priority,
            # 7000 training rows -- see docs/model_cards/
            # priority_classification.md "Probability Calibration" for
            # the full before/after): "sigmoid" barely moved the
            # multiclass Brier score (0.4389 -> 0.4385) and badly
            # compressed the reported confidence range in the process
            # (the top confidence bin dropped from 154 predictions to 1);
            # "isotonic" -- more flexible, non-parametric, and this
            # dataset has enough rows per cv fold for it to avoid
            # overfitting -- actually improved it (0.4389 -> 0.4247)
            # without that compression side effect. This one branch is
            # shared by priority (PriorityMLPipeline), category, and
            # intent (both via OneVsRestClassifier wrapping this same
            # base estimator) -- fixing it here fixes calibration for all
            # three at once, not three separate changes.
            return CalibratedClassifierCV(
                estimator=base_model,
                method="isotonic",
                cv=3,
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