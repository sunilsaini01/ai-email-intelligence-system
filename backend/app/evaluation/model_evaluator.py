from typing import Any

import numpy as np

from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    confusion_matrix,
    classification_report,
)


def evaluate_model(
    model: Any,
    X_test,
    y_test,
    average: str = "binary",
) -> dict:
    """
    Evaluate a trained classification model and return
    the most common performance metrics.

    `average="binary"` (default) preserves exact original behavior for
    existing (spam) callers. Pass average="macro" for multiclass tasks
    (priority: Critical/High/Medium/Low) — macro treats every class equally
    regardless of frequency, which matters here because Critical is the
    rarest class and also the operationally most important one; a
    frequency-weighted average would let it be dominated by Low/Medium
    performance (see docs/model_cards/priority_classification.md).
    """

    predictions = model.predict(X_test)

    results = {
        "accuracy": accuracy_score(
            y_test,
            predictions,
        ),
        "precision": precision_score(
            y_test,
            predictions,
            average=average,
            zero_division=0,
        ),
        "recall": recall_score(
            y_test,
            predictions,
            average=average,
            zero_division=0,
        ),
        "f1_score": f1_score(
            y_test,
            predictions,
            average=average,
            zero_division=0,
        ),
        "confusion_matrix": confusion_matrix(
            y_test,
            predictions,
        ),
        "classification_report": classification_report(
            y_test,
            predictions,
            zero_division=0,
        ),
    }

    # ROC-AUC requires probability estimates.
    if hasattr(model, "predict_proba"):

        probabilities = model.predict_proba(X_test)

        try:
            if average == "binary":
                results["roc_auc"] = roc_auc_score(
                    y_test,
                    probabilities[:, 1],
                )
            else:
                results["roc_auc"] = roc_auc_score(
                    y_test,
                    probabilities,
                    multi_class="ovr",
                    average=average if average in ("macro", "weighted") else "macro",
                )
        except ValueError:
            # e.g. a class absent from a small val/test split — don't let a
            # missing-class edge case crash the whole comparison run.
            pass

    return results


def print_evaluation(
    results: dict,
) -> None:
    """
    Pretty-print evaluation metrics.
    """

    print("\n==============================")
    print("MODEL EVALUATION")
    print("==============================")

    print(f"Accuracy : {results['accuracy']:.4f}")
    print(f"Precision: {results['precision']:.4f}")
    print(f"Recall   : {results['recall']:.4f}")
    print(f"F1 Score : {results['f1_score']:.4f}")

    if "roc_auc" in results:
        print(f"ROC-AUC  : {results['roc_auc']:.4f}")

    print("\nConfusion Matrix")

    print(results["confusion_matrix"])

    print("\nClassification Report")

    print(results["classification_report"])