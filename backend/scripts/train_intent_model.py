"""
Phase 7B — Intent Detection: train and evaluate baseline models.

============================================================================
TRAINED ON data/processed/intent_synthetic_v1 -- A SYNTHETIC, NOT
PRD-COMPLIANT DATASET. See docs/data_audit_intent.md. Every metric this
script prints is a PIPELINE VALIDATION metric, not evidence the model is
ready to make real intent-routing decisions.
============================================================================

Compares Logistic Regression, (Complement) Naive Bayes, and SVM, each
wrapped One-vs-Rest per PRD's suggested classical baseline ("TF-IDF +
Multi-label LR") -- same three-baseline discipline as
train_priority_model.py / train_category_model.py, multi-label evaluation
(F1-macro per PRD §14.1's Intent target, plus F1-micro/Hamming loss for
comparability with Category's report).

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/train_intent_model.py

Produces:
    artifacts/intent_baseline.joblib
    artifacts/intent_baseline_metrics.json
    artifacts/versions/intent_{model_version}.joblib
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.model_evaluator import evaluate_multilabel_model
from app.pipeline.intent_pipeline import IntentMLPipeline
from app.pipeline.pipeline_config import PipelineConfig
from app.preprocessing.email_preprocessor import CATEGORY_CONFIG, EmailPreprocessor
from app.training.artifact_manager import ArtifactManager
from app.training.logger import get_logger
from app.training.trainer import Trainer

logger = get_logger()

DATA_DIR = Path("data/processed/intent_synthetic_v1")
MODEL_TYPES = ["logistic_regression", "naive_bayes", "svm"]

# Reuses CATEGORY_CONFIG (stopword removal + lemmatization) rather than a
# new INTENT_CONFIG -- both are bag-of-words-style multi-label
# classification over the same kind of business-email text, and no
# intent-specific preprocessing need (like sentiment's capitalization
# sensitivity) was found during this phase's audit. If one emerges, add a
# dedicated INTENT_CONFIG then rather than pre-emptively.
INTENT_CLASS_WEIGHT = "balanced"


def load_split(name: str) -> pd.DataFrame:
    df = pd.read_parquet(DATA_DIR / f"{name}.parquet")
    logger.info("Loaded %s split: %d rows", name, len(df))
    return df


def clean_texts(df: pd.DataFrame, preprocessor: EmailPreprocessor) -> list[str]:
    """
    IntentMLPipeline takes plain cleaned text (TF-IDF-only, no record
    dict) -- deliberately excludes intents_raw (pre-noise labels, a
    dataset-generation artifact, not an inference-time signal -- same
    exclusion discipline as train_category_model.py's clean_and_build_records).
    """
    combined = (df["subject_raw"].fillna("") + " " + df["body_text_raw"].fillna("")).tolist()
    return preprocessor.process_batch(combined)


def train_and_evaluate(train_texts, train_labels, test_texts, test_labels):
    results = []
    trained = {}

    for model_type in MODEL_TYPES:
        logger.info("Training %s", model_type)

        config = PipelineConfig(
            model_type=model_type,
            task="intent",
            class_weight=INTENT_CLASS_WEIGHT,
        )
        trainer = Trainer(config, pipeline_cls=IntentMLPipeline)
        trainer.train(X_train=train_texts, y_train=train_labels)

        metrics = evaluate_multilabel_model(
            model=trainer.pipeline,
            X_test=test_texts,
            y_test=test_labels,
        )

        per_label = metrics["per_label_report"]
        per_label_f1 = {
            label: round(per_label[label]["f1-score"], 4)
            for label in trainer.pipeline.classes_
            if label in per_label
        }

        results.append(
            {
                "model": model_type,
                "f1_micro": round(metrics["f1_micro"], 4),
                "f1_macro": round(metrics["f1_macro"], 4),
                "f1_weighted": round(metrics["f1_weighted"], 4),
                "hamming_loss": round(metrics["hamming_loss"], 4),
                "precision_micro": round(metrics["precision_micro"], 4),
                "recall_micro": round(metrics["recall_micro"], 4),
                "subset_accuracy": round(metrics["subset_accuracy"], 4),
                "per_label_f1": per_label_f1,
            }
        )
        trained[model_type] = trainer

    return results, trained


def main():
    preprocessor = EmailPreprocessor(CATEGORY_CONFIG)

    train_df = load_split("train")
    test_df = load_split("test")

    train_texts = clean_texts(train_df, preprocessor)
    test_texts = clean_texts(test_df, preprocessor)

    train_labels = train_df["intents"].tolist()
    test_labels = test_df["intents"].tolist()

    results, trained = train_and_evaluate(train_texts, train_labels, test_texts, test_labels)

    comparison = pd.DataFrame(
        [{k: v for k, v in r.items() if k != "per_label_f1"} for r in results]
    ).sort_values(["f1_macro", "hamming_loss"], ascending=[False, True])

    print("\n================ INTENT BASELINE COMPARISON (SYNTHETIC test set) ================\n")
    print(comparison.to_string(index=False))

    best_row = comparison.iloc[0]
    best_model_type = best_row["model"]
    best_result = next(r for r in results if r["model"] == best_model_type)

    print(f"\nBest model: {best_model_type}")
    print(f"F1-macro: {best_result['f1_macro']}  |  F1-micro: {best_result['f1_micro']}  |  Hamming Loss: {best_result['hamming_loss']}")
    print("\nPer-label F1:", best_result["per_label_f1"])

    f1_macro_target = 0.80  # PRD §14.1 metrics table (Definition of Done states 0.78 -- both recorded)
    print(
        f"\n[INFO] PRD target: F1-macro > {f1_macro_target} (also stated as >0.78 elsewhere in the PRD). "
        "This target is NOT evaluable as PRD-compliant here — this dataset is synthetic "
        "(docs/data_audit_intent.md). Reported for pipeline-validation reference only."
    )

    model_version = f"{best_model_type}-{datetime.now(UTC):%Y%m%d-%H%M%S}"

    artifact_manager = ArtifactManager()
    artifact_manager.save_model(trained[best_model_type].pipeline, "intent_baseline.joblib")

    versioned_artifact_manager = ArtifactManager(artifact_dir="artifacts/versions")
    versioned_artifact_manager.save_model(
        trained[best_model_type].pipeline, f"intent_{model_version}.joblib"
    )

    artifact_manager.save_json(
        {
            "comparison": results,
            "best_model": best_model_type,
            "model_version": model_version,
            "labels": list(trained[best_model_type].pipeline.classes_),
            "f1_macro_target": f1_macro_target,
            "meets_f1_macro_target": bool(best_result["f1_macro"] >= f1_macro_target),
            "train_size": len(train_df),
            "test_size": len(test_df),
            "SYNTHETIC_DATA": True,
            "PRD_COMPLIANT": False,
            "warning": (
                "Trained on data/processed/intent_synthetic_v1 (heuristic multi-label "
                "tags, not human-annotated). These metrics validate the pipeline "
                "mechanically; they are not evidence of real-world intent-detection "
                "quality. See docs/data_audit_intent.md and docs/model_cards/intent.md."
            ),
        },
        "intent_baseline_metrics.json",
    )

    print(f"\nModel version: {model_version}")
    print(f"Versioned artifact: artifacts/versions/intent_{model_version}.joblib")


if __name__ == "__main__":
    main()
