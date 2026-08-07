"""
Phase 4 follow-up (Step 10 gap closure) — is the shipped Logistic Regression
model's confidence score actually calibrated, or just a number that happens
to come out of softmax?

Checks top-1 confidence calibration: bins predictions by their reported
confidence, and compares each bin's average confidence to its actual
accuracy. A well-calibrated model has confidence ~= accuracy in every bin.
Also reports the Brier score (multiclass, one-vs-rest averaged) as a single
summary number.

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/check_priority_calibration.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.preprocessing.email_preprocessor import PRIORITY_CONFIG, EmailPreprocessor
from app.training.artifact_manager import ArtifactManager
from app.training.logger import get_logger
from scripts.train_priority_model import LABELS, clean_and_build_records, load_split

logger = get_logger()


def brier_score_multiclass(y_true_idx: np.ndarray, probabilities: np.ndarray, n_classes: int) -> float:
    one_hot = np.eye(n_classes)[y_true_idx]
    return float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))


def main():
    artifact_manager = ArtifactManager()
    pipeline = artifact_manager.load_model("priority_baseline.joblib")

    preprocessor = EmailPreprocessor(PRIORITY_CONFIG)
    test_df = load_split("test")
    test_records = clean_and_build_records(test_df, preprocessor)
    test_labels = test_df["priority_label"].tolist()

    probabilities = pipeline.predict_proba(test_records)
    predictions = pipeline.predict(test_records)
    classes = list(pipeline.classes_)
    label_to_idx = {label: classes.index(label) for label in LABELS}

    top1_confidence = probabilities.max(axis=1)
    correct = np.array([pred == actual for pred, actual in zip(predictions, test_labels, strict=True)])

    y_true_idx = np.array([label_to_idx[label] for label in test_labels])
    brier = brier_score_multiclass(y_true_idx, probabilities, len(classes))

    print("\n================ PRIORITY MODEL CALIBRATION CHECK (SYNTHETIC test set) ================\n")
    print(f"Multiclass Brier score (0=perfect, higher=worse, max=2.0 for {len(classes)} classes): {brier:.4f}")
    print("\nTop-1 confidence calibration (bin: predicted confidence -> actual accuracy in that bin):\n")

    bins = [(0.0, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]
    rows = []
    for lo, hi in bins:
        mask = (top1_confidence >= lo) & (top1_confidence < hi)
        n = int(mask.sum())
        if n == 0:
            rows.append((lo, hi, n, None, None))
            continue
        avg_confidence = float(top1_confidence[mask].mean())
        actual_accuracy = float(correct[mask].mean())
        rows.append((lo, hi, n, avg_confidence, actual_accuracy))

    for lo, hi, n, avg_conf, acc in rows:
        if n == 0:
            print(f"  [{lo:.1f}, {hi:.1f}): n=0 (no predictions in this range)")
        else:
            gap = abs(avg_conf - acc)
            flag = "  <-- overconfident" if avg_conf - acc > 0.1 else ("  <-- underconfident" if acc - avg_conf > 0.1 else "")
            print(
                f"  [{lo:.1f}, {hi:.1f}): n={n:4d}  avg_confidence={avg_conf:.3f}  "
                f"actual_accuracy={acc:.3f}  gap={gap:.3f}{flag}"
            )

    print(
        "\n[CONCLUSION] See docs/model_cards/priority_classification.md 'Probability Calibration' "
        "for interpretation. This is measured on SYNTHETIC data - a calibration gap here reflects "
        "the synthetic label distribution, not necessarily how confidence would behave on real data."
    )


if __name__ == "__main__":
    main()
