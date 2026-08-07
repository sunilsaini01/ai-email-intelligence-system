"""
Phase 4 — Priority Classification: train and evaluate baseline models.

============================================================================
TRAINED ON data/processed/priority_synthetic_v1 — A SYNTHETIC, NOT
PRD-COMPLIANT DATASET. See docs/data_audit_priority.md. Every metric this
script prints is a PIPELINE VALIDATION metric, not evidence the model is
ready to make real business-priority decisions.
============================================================================

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/train_priority_model.py

Produces:
    artifacts/priority_baseline.joblib
    artifacts/priority_baseline_metrics.json
    artifacts/versions/priority_{model_version}.joblib
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.model_evaluator import evaluate_model
from app.pipeline.pipeline_config import PipelineConfig
from app.pipeline.priority_pipeline import PriorityMLPipeline
from app.preprocessing.email_preprocessor import PRIORITY_CONFIG, EmailPreprocessor
from app.training.artifact_manager import ArtifactManager
from app.training.logger import get_logger
from app.training.trainer import Trainer

logger = get_logger()

DATA_DIR = Path("data/processed/priority_synthetic_v1")
MODEL_TYPES = ["logistic_regression", "naive_bayes", "svm"]
LABELS = ["Low", "Medium", "High", "Critical"]
CRITICAL_HIGH = ["Critical", "High"]

# NOT PipelineConfig's spam-derived default -- priority has its own class
# balance (see run_metadata.json from the dataset generator: roughly
# 57/33/8/2 Low/Medium/High/Critical). "balanced" is the reasonable starting
# point here (unlike spam, no prior sweep has been done for priority yet --
# see docs/model_cards/priority_classification.md "Known Gaps").
PRIORITY_CLASS_WEIGHT = "balanced"


def load_split(name: str) -> pd.DataFrame:
    df = pd.read_parquet(DATA_DIR / f"{name}.parquet")
    logger.info("Loaded %s split: %d rows", name, len(df))
    return df


def clean_and_build_records(df: pd.DataFrame, preprocessor: EmailPreprocessor) -> list[dict]:
    """
    Builds the exact record shape PriorityMLPipeline/PriorityService expect.

    Deliberately excludes heuristic_score, priority_label_raw, and
    is_automated — those are dataset-generation artifacts (see
    generate_synthetic_priority_dataset.py), not inference-time-available
    signals. Including them wouldn't just correlate with the label, it would
    BE the label-generation logic, which is a stronger, more dishonest form
    of leakage than anything documented in docs/data_audit_priority.md §4.
    """
    body_clean = preprocessor.process_batch(df["body_text_raw"].tolist())

    records = []
    for i, row in df.reset_index(drop=True).iterrows():
        subject = row["subject_raw"] or ""
        is_reply = subject.strip().lower().startswith("re:")
        is_forward = subject.strip().lower().startswith(("fwd:", "fw:"))
        to_field = row["recipient_to_raw"] or ""
        recipient_to = [addr.strip() for addr in to_field.split(",") if addr.strip()]

        records.append(
            {
                "body_clean": body_clean[i],
                "subject_raw": subject,
                "sender_email": row["sender_email"],
                "received_at": row["received_at_raw"],
                "recipient_to": recipient_to,
                "recipient_cc": [],
                "is_reply": is_reply,
                "is_forward": is_forward,
                # Not extracted by any loader in this repo yet -- same
                # default used at inference time, see
                # docs/data_audit_priority.md §5.
                "thread_depth": 0,
                "has_attachments": False,
                "attachment_count": 0,
            }
        )
    return records


def train_and_evaluate(train_records, train_labels, val_records, val_labels, test_records, test_labels):
    results = []
    trained = {}

    for model_type in MODEL_TYPES:
        logger.info("Training %s", model_type)

        config = PipelineConfig(
            model_type=model_type,
            task="priority",
            class_weight=PRIORITY_CLASS_WEIGHT,
        )
        trainer = Trainer(config, pipeline_cls=PriorityMLPipeline)
        trainer.train(X_train=train_records, y_train=train_labels)

        metrics = evaluate_model(
            model=trainer.pipeline,
            X_test=test_records,
            y_test=test_labels,
            average="macro",
        )

        # Critical/High specifically -- the PRD's operationally significant
        # classes (§14.1: "F1 > 0.85 for High/Critical"). Macro F1 across all
        # 4 classes can hide poor performance on the 2 rarest, most important
        # ones -- computing them in isolation is the whole point of this
        # block, not a redundant re-slice of the same number.
        test_preds = trainer.pipeline.predict(test_records)
        critical_high_f1 = f1_score(
            test_labels, test_preds, labels=CRITICAL_HIGH, average="macro", zero_division=0
        )
        critical_high_recall = recall_score(
            test_labels, test_preds, labels=CRITICAL_HIGH, average="macro", zero_division=0
        )
        critical_high_precision = precision_score(
            test_labels, test_preds, labels=CRITICAL_HIGH, average="macro", zero_division=0
        )

        per_class_f1 = f1_score(test_labels, test_preds, labels=LABELS, average=None, zero_division=0)
        per_class_recall = recall_score(test_labels, test_preds, labels=LABELS, average=None, zero_division=0)
        per_class_precision = precision_score(
            test_labels, test_preds, labels=LABELS, average=None, zero_division=0
        )

        cm = confusion_matrix(test_labels, test_preds, labels=LABELS)

        results.append(
            {
                "model": model_type,
                "macro_f1": round(metrics["f1_score"], 4),
                "macro_precision": round(metrics["precision"], 4),
                "macro_recall": round(metrics["recall"], 4),
                "accuracy": round(metrics["accuracy"], 4),
                "critical_high_f1": round(critical_high_f1, 4),
                "critical_high_recall": round(critical_high_recall, 4),
                "critical_high_precision": round(critical_high_precision, 4),
                "per_class_f1": dict(zip(LABELS, [round(x, 4) for x in per_class_f1], strict=True)),
                "per_class_recall": dict(zip(LABELS, [round(x, 4) for x in per_class_recall], strict=True)),
                "per_class_precision": dict(
                    zip(LABELS, [round(x, 4) for x in per_class_precision], strict=True)
                ),
                "confusion_matrix": cm.tolist(),
            }
        )
        trained[model_type] = trainer

    return results, trained


def main():
    preprocessor = EmailPreprocessor(PRIORITY_CONFIG)

    train_df = load_split("train")
    val_df = load_split("val")
    test_df = load_split("test")

    train_records = clean_and_build_records(train_df, preprocessor)
    val_records = clean_and_build_records(val_df, preprocessor)
    test_records = clean_and_build_records(test_df, preprocessor)

    train_labels = train_df["priority_label"].tolist()
    val_labels = val_df["priority_label"].tolist()
    test_labels = test_df["priority_label"].tolist()

    results, trained = train_and_evaluate(
        train_records, train_labels, val_records, val_labels, test_records, test_labels
    )

    comparison = pd.DataFrame(
        [{k: v for k, v in r.items() if k not in ("per_class_f1", "per_class_recall", "per_class_precision", "confusion_matrix")} for r in results]
    ).sort_values(["critical_high_f1", "macro_f1"], ascending=[False, False])

    print("\n================ PRIORITY BASELINE COMPARISON (SYNTHETIC test set) ================\n")
    print(comparison.to_string(index=False))

    best_row = comparison.iloc[0]
    best_model_type = best_row["model"]
    best_result = next(r for r in results if r["model"] == best_model_type)

    print(f"\nBest model: {best_model_type}")
    print(f"Macro F1: {best_result['macro_f1']}  |  Critical/High F1: {best_result['critical_high_f1']}")
    print("\nPer-class F1:", best_result["per_class_f1"])
    print("\nConfusion matrix (rows=actual, cols=predicted), labels =", LABELS)
    for row_label, row in zip(LABELS, best_result["confusion_matrix"], strict=True):
        print(f"  {row_label:10s} {row}")

    macro_target = 0.82  # PRD Milestone 2
    critical_high_target = 0.85  # PRD §14.1
    print(
        f"\n[INFO] PRD targets: macro F1 > {macro_target}, Critical/High F1 > {critical_high_target}. "
        "These targets are NOT evaluable as PRD-compliant here — this dataset is synthetic "
        "(docs/data_audit_priority.md). Reported for pipeline-validation reference only."
    )

    model_version = f"{best_model_type}-{datetime.now(UTC):%Y%m%d-%H%M%S}"

    artifact_manager = ArtifactManager()
    artifact_manager.save_model(trained[best_model_type].pipeline, "priority_baseline.joblib")

    versioned_artifact_manager = ArtifactManager(artifact_dir="artifacts/versions")
    versioned_artifact_manager.save_model(
        trained[best_model_type].pipeline, f"priority_{model_version}.joblib"
    )

    artifact_manager.save_json(
        {
            "comparison": results,
            "best_model": best_model_type,
            "model_version": model_version,
            "labels": LABELS,
            "macro_f1_target": macro_target,
            "critical_high_f1_target": critical_high_target,
            "meets_macro_target": bool(best_result["macro_f1"] >= macro_target),
            "meets_critical_high_target": bool(best_result["critical_high_f1"] >= critical_high_target),
            "train_size": len(train_df),
            "val_size": len(val_df),
            "test_size": len(test_df),
            "SYNTHETIC_DATA": True,
            "PRD_COMPLIANT": False,
            "warning": (
                "Trained on data/processed/priority_synthetic_v1 (heuristic labels, "
                "not human-annotated). These metrics validate the pipeline mechanically; "
                "they are not evidence of real-world priority classification quality. "
                "See docs/data_audit_priority.md and docs/model_cards/priority_classification.md."
            ),
        },
        "priority_baseline_metrics.json",
    )

    print(f"\nModel version: {model_version}")
    print(f"Versioned artifact: artifacts/versions/priority_{model_version}.joblib")


if __name__ == "__main__":
    main()
