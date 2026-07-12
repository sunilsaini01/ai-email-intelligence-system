import joblib

from pathlib import Path

from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier


def train_multilabel_classifier(
    X_train,
    y_train_multilabel,
) -> OneVsRestClassifier:
    """
    Train a One-vs-Rest Logistic Regression classifier
    for multi-label email classification.
    """

    base_classifier = LogisticRegression(
        C=1.0,
        solver="saga",
        max_iter=1000,
        class_weight="balanced",
        random_state=42,
    )

    model = OneVsRestClassifier(
        estimator=base_classifier,
        n_jobs=-1,
    )

    model.fit(
        X_train,
        y_train_multilabel,
    )

    return model


def save_model(
    model,
    path: str | Path,
) -> None:
    """
    Save a trained multi-label classifier.
    """
    joblib.dump(
        model,
        path,
    )


def load_model(
    path: str | Path,
):
    """
    Load a trained multi-label classifier.
    """
    return joblib.load(path)