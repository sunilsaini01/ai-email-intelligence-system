import numpy as np

from sklearn.svm import LinearSVC
from sklearn.calibration import CalibratedClassifierCV


def train_svm(
    X_train,
    y_train,
    C: float = 1.0,
    max_iter: int = 2000,
    class_weight: str = "balanced",
) -> CalibratedClassifierCV:
    """
    Train a calibrated Linear SVM for email classification.
    """

    base_svm = LinearSVC(
        C=C,
        max_iter=max_iter,
        class_weight=class_weight,
        dual=True,
        random_state=42,
    )

    calibrated_svm = CalibratedClassifierCV(
        estimator=base_svm,
        method="sigmoid",
        cv=3,
    )

    calibrated_svm.fit(
        X_train,
        y_train,
    )

    return calibrated_svm


def inspect_svm_weights(
    model: CalibratedClassifierCV,
    feature_names: list[str],
    n_top: int = 20,
) -> None:
    """
    Display the most important positive and negative
    features learned by the Linear SVM.
    """

    weights = np.mean(
        [
            est.estimator.coef_[0]
            for est in model.calibrated_classifiers_
        ],
        axis=0,
    )

    top_positive = np.argsort(weights)[-n_top:][::-1]
    top_negative = np.argsort(weights)[:n_top]

    print(f"\nTop {n_top} SVM features -> spam:")

    for idx in top_positive:
        print(
            f"  {feature_names[idx]:40s} "
            f"weight: {weights[idx]:+.4f}"
        )

    print(f"\nTop {n_top} SVM features -> ham:")

    for idx in top_negative:
        print(
            f"  {feature_names[idx]:40s} "
            f"weight: {weights[idx]:+.4f}"
        )


