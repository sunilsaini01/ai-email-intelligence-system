"""
Recall-gap remediation experiment — cheapest option first (per
docs/model_cards/spam_detection.md's "Path to Closing the Recall Gap").

The shipped SVM already trains with class_weight="balanced" (see
PipelineConfig) and still lands at 98.89% recall vs. the 99% FR-11 target.
"Balanced" reweights inversely to class frequency (~1:2.3 ham:spam here) —
it is not the same as deliberately overweighting spam beyond that ratio to
push recall further, which is the actual untried lever. This script sweeps
explicit spam:ham weight ratios and reports whether any of them closes the
gap without collapsing precision, so that decision is made with data, not
by guessing at a ratio and shipping it.

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/experiment_class_weight_tuning.py

This is an experiment script, not part of the production training path —
it doesn't write any artifact. If a ratio here beats the shipped baseline,
promote it into scripts/train_spam_model.py deliberately, don't wire this
script into CI.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from app.training.logger import get_logger
from scripts.train_spam_model import (
    RECALL_TARGET,
    clean_dataset,
    load_dataset,
    pick_recall_threshold,
    split_dataset,
)

logger = get_logger()

# "balanced" on this corpus (~70% ham / 30% spam) works out to roughly a
# 1:2.3 spam:ham weight ratio. Candidates below deliberately bracket and
# exceed that so the sweep can show whether pushing further actually helps.
CANDIDATE_WEIGHTS = [
    ("balanced (shipped baseline)", "balanced"),
    ("1:3", {0: 1, 1: 3}),
    ("1:4", {0: 1, 1: 4}),
    ("1:6", {0: 1, 1: 6}),
    ("1:10", {0: 1, 1: 10}),
]


def build_svm_pipeline(class_weight) -> Pipeline:
    base_svm = LinearSVC(
        C=1.0,
        max_iter=2000,
        class_weight=class_weight,
        random_state=42,
    )
    calibrated = CalibratedClassifierCV(estimator=base_svm, method="sigmoid", cv=3)
    # Must match app/pipeline/ml_pipeline.py's TfidfVectorizer exactly (including
    # its min_df=1 hardcode, which ignores PipelineConfig.tfidf_min_df/max_df) —
    # otherwise this sweep isn't comparing against the model that's actually shipped.
    return Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    max_features=50_000,
                    ngram_range=(1, 2),
                    sublinear_tf=True,
                    min_df=1,
                ),
            ),
            ("classifier", calibrated),
        ]
    )


def main():
    df = load_dataset()
    df = clean_dataset(df)
    train_df, val_df, test_df = split_dataset(df)

    rows = []
    for label, weight in CANDIDATE_WEIGHTS:
        logger.info("Training SVM with class_weight=%s", label)
        pipeline = build_svm_pipeline(weight)
        pipeline.fit(train_df["body_clean"].tolist(), train_df["label"].tolist())

        val_proba = pipeline.predict_proba(val_df["body_clean"].tolist())[:, 1]
        threshold, _, _ = pick_recall_threshold(val_df["label"].tolist(), val_proba)

        test_proba = pipeline.predict_proba(test_df["body_clean"].tolist())[:, 1]
        from sklearn.metrics import precision_score, recall_score

        test_preds = (test_proba >= threshold).astype(int)
        test_recall = recall_score(test_df["label"].tolist(), test_preds)
        test_precision = precision_score(test_df["label"].tolist(), test_preds, zero_division=0)

        rows.append(
            {
                "class_weight": label,
                "calibrated_threshold": round(threshold, 4),
                "test_recall": round(test_recall, 4),
                "test_precision": round(test_precision, 4),
                "meets_target": bool(test_recall >= RECALL_TARGET),
            }
        )

    comparison = pd.DataFrame(rows)
    print("\n================ CLASS-WEIGHT SWEEP (SVM, real test set) ================\n")
    print(comparison.to_string(index=False))

    baseline_precision = rows[0]["test_precision"]
    better = [
        r for r in rows[1:] if r["test_recall"] >= RECALL_TARGET and r["test_precision"] >= baseline_precision
    ]
    if better:
        print(
            f"\n[RESULT] {len(better)} configuration(s) meet the {RECALL_TARGET} recall target "
            "at precision >= the shipped baseline. Consider promoting the best one."
        )
    else:
        any_meets_target = [r for r in rows[1:] if r["test_recall"] >= RECALL_TARGET]
        if any_meets_target:
            print(
                f"\n[RESULT] {len(any_meets_target)} configuration(s) reach {RECALL_TARGET} recall, "
                "but only by trading away precision below the shipped baseline "
                f"({baseline_precision}). Not a clear win — see model card for the next option "
                "(fresher/more labeled data) before reaching for a transformer."
            )
        else:
            print(
                f"\n[RESULT] No class-weight ratio tried reaches {RECALL_TARGET} recall on this "
                "corpus without threshold calibration doing the work instead. Class-weight tuning "
                "does not close the gap here — confirms the model card's assessment that the next "
                "cheapest lever is more/fresher labeled data, not further reweighting."
            )


if __name__ == "__main__":
    main()
