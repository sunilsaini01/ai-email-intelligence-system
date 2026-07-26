"""
Phase 3 — Spam Detection: train and evaluate baseline models on the real
SpamAssassin corpus (not the toy in-memory samples used by the smoke tests).

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/train_spam_model.py

Produces:
    artifacts/spam_baseline.joblib   — the best baseline model (by recall)
    artifacts/spam_baseline_metrics.json — comparison report for all baselines
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import precision_score, recall_score
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data_ingestion.spamassassin_loader import load_spamassassin
from app.evaluation.model_evaluator import evaluate_model
from app.pipeline.pipeline_config import PipelineConfig
from app.preprocessing.email_preprocessor import SPAM_CONFIG, EmailPreprocessor
from app.training.artifact_manager import ArtifactManager
from app.training.logger import get_logger
from app.training.trainer import Trainer

logger = get_logger()

RAW_DATA_DIR = "data/raw/spamassassin"
MODEL_TYPES = ["logistic_regression", "naive_bayes", "svm"]
RECALL_TARGET = 0.99


def load_dataset() -> pd.DataFrame:
    logger.info("Loading SpamAssassin corpus from %s", RAW_DATA_DIR)

    records = list(load_spamassassin(RAW_DATA_DIR))
    df = pd.DataFrame(records)

    logger.info("Loaded %d raw emails", len(df))

    # Ground truth labels only — drop anything the loader couldn't parse a body for.
    df = df[df["body_text_raw"].str.len() > 0].reset_index(drop=True)

    logger.info("Kept %d emails with non-empty body", len(df))
    logger.info("Class balance:\n%s", df["spam_label"].value_counts())

    return df


def clean_dataset(df: pd.DataFrame) -> pd.DataFrame:
    logger.info("Cleaning email bodies (HTML strip, quote/signature removal, lemmatization)")

    preprocessor = EmailPreprocessor(SPAM_CONFIG)

    df["body_clean"] = preprocessor.process_batch(df["body_text_raw"].tolist())

    before = len(df)
    df = df[df["body_clean"].str.len() > 0].reset_index(drop=True)
    logger.info("Dropped %d emails that cleaned to empty text", before - len(df))

    df["label"] = (df["spam_label"] == "spam").astype(int)

    return df


def split_dataset(df: pd.DataFrame):
    train_df, temp_df = train_test_split(
        df,
        test_size=0.2,
        random_state=42,
        stratify=df["label"],
    )
    val_df, test_df = train_test_split(
        temp_df,
        test_size=0.5,
        random_state=42,
        stratify=temp_df["label"],
    )

    logger.info(
        "Split sizes -> train: %d, val: %d, test: %d",
        len(train_df),
        len(val_df),
        len(test_df),
    )

    return train_df, val_df, test_df


def pick_recall_threshold(y_true, probabilities, target_recall=RECALL_TARGET):
    """
    Find the highest decision threshold that still clears `target_recall`.

    Why not just use argmax (threshold=0.5): FR-11 treats a missed spam
    email as worse than a quarantined legitimate one, so the operating
    point should be chosen to satisfy the recall floor first, precision
    second — the opposite of the default balanced threshold.
    """
    candidates = np.linspace(0.5, 0.01, 50)

    best_threshold = 0.01
    for t in candidates:
        preds = (probabilities >= t).astype(int)
        if recall_score(y_true, preds) >= target_recall:
            best_threshold = t
            break

    preds = (probabilities >= best_threshold).astype(int)
    achieved_recall = recall_score(y_true, preds)
    achieved_precision = precision_score(y_true, preds, zero_division=0)

    return float(best_threshold), float(achieved_recall), float(achieved_precision)


def train_and_evaluate(train_df, val_df, test_df):
    results = []
    trained = {}

    for model_type in MODEL_TYPES:
        logger.info("Training %s", model_type)

        config = PipelineConfig(model_type=model_type, task="spam")
        trainer = Trainer(config)
        trainer.train(
            X_train=train_df["body_clean"].tolist(),
            y_train=train_df["label"].tolist(),
        )

        # Default-threshold (0.5) metrics, for comparison against the calibrated ones.
        metrics = evaluate_model(
            model=trainer.pipeline.pipeline,
            X_test=test_df["body_clean"].tolist(),
            y_test=test_df["label"].tolist(),
        )

        # Calibrate the decision threshold on the validation set (never on test),
        # then confirm it actually clears the recall target on the held-out test set.
        val_proba = trainer.predict_proba(val_df["body_clean"].tolist())[:, 1]
        threshold, val_recall, val_precision = pick_recall_threshold(
            val_df["label"].tolist(), val_proba
        )

        test_proba = trainer.predict_proba(test_df["body_clean"].tolist())[:, 1]
        test_preds_at_threshold = (test_proba >= threshold).astype(int)
        test_recall_at_threshold = recall_score(test_df["label"].tolist(), test_preds_at_threshold)
        test_precision_at_threshold = precision_score(
            test_df["label"].tolist(), test_preds_at_threshold, zero_division=0
        )

        results.append(
            {
                "model": model_type,
                "accuracy@0.5": round(metrics["accuracy"], 4),
                "precision@0.5": round(metrics["precision"], 4),
                "recall@0.5": round(metrics["recall"], 4),
                "f1_score@0.5": round(metrics["f1_score"], 4),
                "roc_auc": round(metrics.get("roc_auc", 0.0), 4),
                "calibrated_threshold": round(threshold, 4),
                "recall_at_threshold": round(test_recall_at_threshold, 4),
                "precision_at_threshold": round(test_precision_at_threshold, 4),
            }
        )
        trained[model_type] = trainer

    return results, trained


def main():
    df = load_dataset()
    df = clean_dataset(df)
    train_df, val_df, test_df = split_dataset(df)

    results, trained = train_and_evaluate(train_df, val_df, test_df)

    comparison = pd.DataFrame(results).sort_values(
        ["recall_at_threshold", "precision_at_threshold"], ascending=[False, False]
    )

    print("\n================ SPAM BASELINE COMPARISON (real test set) ================\n")
    print(comparison.to_string(index=False))

    best_row = comparison.iloc[0]
    best_model_type = best_row["model"]
    meets_target = bool(best_row["recall_at_threshold"] >= RECALL_TARGET)

    print(
        f"\nBest model: {best_model_type} "
        f"(threshold={best_row['calibrated_threshold']:.4f}, "
        f"test recall={best_row['recall_at_threshold']:.4f}, "
        f"test precision={best_row['precision_at_threshold']:.4f})"
    )

    if meets_target:
        print(f"[OK] Meets FR-11 target: recall >= {RECALL_TARGET} at the calibrated threshold")
    else:
        print(
            f"[WARN] Still short of FR-11's recall >= {RECALL_TARGET} even after threshold "
            "calibration. Consider class-weight tuning or a fine-tuned transformer model."
        )

    artifact_manager = ArtifactManager()

    artifact_manager.save_model(
        trained[best_model_type].pipeline,
        "spam_baseline.joblib",
    )

    artifact_manager.save_json(
        {
            "comparison": results,
            "best_model": best_model_type,
            "decision_threshold": float(best_row["calibrated_threshold"]),
            "recall_target": RECALL_TARGET,
            "meets_target": meets_target,
            "train_size": len(train_df),
            "val_size": len(val_df),
            "test_size": len(test_df),
        },
        "spam_baseline_metrics.json",
    )


if __name__ == "__main__":
    main()
