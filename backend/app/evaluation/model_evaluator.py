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
    hamming_loss,
    multilabel_confusion_matrix,
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


def evaluate_multilabel_model(
    model: Any,
    X_test: list[dict],
    y_test: list[list[str]],
) -> dict:
    """
    Evaluate a multi-label classifier (Module 4 — CategoryMLPipeline).

    Not a variant of evaluate_model()'s `average` parameter (like priority's
    multiclass case was): multi-label metrics need a fundamentally different
    input shape (binary indicator matrices, not label vectors) and a
    genuinely different metric set (Hamming loss and subset accuracy have no
    single-label equivalent). Forcing this into evaluate_model() would mean
    branching its internals on a shape assumption every existing (spam,
    priority) caller doesn't need to think about — a separate function is
    the honest boundary, mirroring why CategoryMLPipeline is a separate
    class from PriorityMLPipeline rather than a branch inside it.

    Primary metric per PRD §14.1: F1-micro. Secondary: Hamming loss (also
    PRD-named). Per-label breakdown and Hamming loss specifically matter here
    because a single blended score can hide a rare category (e.g. Legal)
    that never gets predicted at all — same failure mode
    docs/model_cards/priority_classification.md's "Class Imbalance" section
    already documents for Priority's Critical class, one label space over.
    """
    y_true_bin = model.mlb.transform(y_test)

    predicted_labels = model.predict(X_test)
    y_pred_bin = model.mlb.transform(predicted_labels)

    label_names = list(model.classes_)

    results = {
        "hamming_loss": hamming_loss(y_true_bin, y_pred_bin),
        "f1_micro": f1_score(y_true_bin, y_pred_bin, average="micro", zero_division=0),
        "f1_macro": f1_score(y_true_bin, y_pred_bin, average="macro", zero_division=0),
        "f1_weighted": f1_score(y_true_bin, y_pred_bin, average="weighted", zero_division=0),
        "precision_micro": precision_score(y_true_bin, y_pred_bin, average="micro", zero_division=0),
        "recall_micro": recall_score(y_true_bin, y_pred_bin, average="micro", zero_division=0),
        # Exact-match ratio: accuracy_score on a 2D indicator matrix requires
        # every one of the 8 per-row labels to match, not just one — a much
        # stricter bar than any per-label metric, reported because it's what
        # "the model got this email completely right" actually means for a
        # multi-label task.
        "subset_accuracy": accuracy_score(y_true_bin, y_pred_bin),
        "per_label_report": classification_report(
            y_true_bin,
            y_pred_bin,
            target_names=label_names,
            zero_division=0,
            output_dict=True,
        ),
        "per_label_confusion_matrices": {
            label: cm.tolist()
            for label, cm in zip(
                label_names, multilabel_confusion_matrix(y_true_bin, y_pred_bin), strict=True
            )
        },
    }

    return results


def print_multilabel_evaluation(results: dict) -> None:
    """Pretty-print multi-label evaluation metrics — mirrors print_evaluation()."""

    print("\n==============================")
    print("MULTI-LABEL MODEL EVALUATION")
    print("==============================")

    print(f"F1-micro       : {results['f1_micro']:.4f}")
    print(f"F1-macro       : {results['f1_macro']:.4f}")
    print(f"F1-weighted    : {results['f1_weighted']:.4f}")
    print(f"Hamming Loss   : {results['hamming_loss']:.4f}")
    print(f"Precision-micro: {results['precision_micro']:.4f}")
    print(f"Recall-micro   : {results['recall_micro']:.4f}")
    print(f"Subset Accuracy: {results['subset_accuracy']:.4f}")


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