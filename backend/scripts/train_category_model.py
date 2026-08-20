"""
Phase 5 — Email Categorization: train and evaluate baseline models.

============================================================================
TRAINED ON data/processed/category_synthetic_v1 — A SYNTHETIC, NOT
PRD-COMPLIANT DATASET. See docs/data_audit_categorization.md. Every metric
this script prints is a PIPELINE VALIDATION metric, not evidence the model
is ready to make real category-routing decisions.
============================================================================

Compares Logistic Regression, (Complement) Naive Bayes, and SVM, each
wrapped One-vs-Rest per PRD §9.1's named baseline architecture (see
app/pipeline/category_pipeline.py) — same three-baseline comparison
discipline as train_spam_model.py / train_priority_model.py, adapted to
multi-label evaluation (F1-micro + Hamming loss, PRD §14.1) instead of
single-label accuracy/recall.

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/train_category_model.py

Produces:
    artifacts/category_baseline.joblib
    artifacts/category_baseline_metrics.json
    artifacts/versions/category_{model_version}.joblib
"""

import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.model_evaluator import evaluate_multilabel_model
from app.mlops.model_metadata import MODULE_EVIDENCE_STATUS
from app.pipeline.category_pipeline import CategoryMLPipeline
from app.pipeline.pipeline_config import PipelineConfig
from app.preprocessing.email_preprocessor import CATEGORY_CONFIG, EmailPreprocessor
from app.training.artifact_manager import ArtifactManager
from app.training.logger import get_logger
from app.training.trainer import Trainer

logger = get_logger()

MLFLOW_MODEL_NAME = "category"


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


DATA_DIR = Path("data/processed/category_synthetic_v1")
MODEL_TYPES = ["logistic_regression", "naive_bayes", "svm"]

# Same reasoning as train_priority_model.py: no prior sweep has been done
# for category yet (unlike spam's tuned {0:1,1:4}), so "balanced" is the
# defensible starting point, applied per-binary-problem inside OneVsRest.
CATEGORY_CLASS_WEIGHT = "balanced"


def load_split(name: str) -> pd.DataFrame:
    df = pd.read_parquet(DATA_DIR / f"{name}.parquet")
    logger.info("Loaded %s split: %d rows", name, len(df))
    return df


def clean_and_build_records(df: pd.DataFrame, preprocessor: EmailPreprocessor) -> list[dict]:
    """
    Builds the exact record shape CategoryMLPipeline/CategoryService expect.
    Deliberately excludes categories_raw (pre-noise labels — a dataset-
    generation artifact, not an inference-time-available signal; including
    it would be a direct label leak, stronger than the keyword-lexicon
    leakage already disclosed in docs/data_audit_categorization.md §4).
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
                # Not extracted by any loader in this repo yet — same
                # default at inference time, see
                # docs/data_audit_categorization.md §5.
                "thread_depth": 0,
                "has_attachments": False,
                "attachment_count": 0,
            }
        )
    return records


def train_and_evaluate(train_records, train_labels, test_records, test_labels):
    results = []
    trained = {}

    for model_type in MODEL_TYPES:
        logger.info("Training %s", model_type)

        config = PipelineConfig(
            model_type=model_type,
            task="category",
            class_weight=CATEGORY_CLASS_WEIGHT,
        )
        trainer = Trainer(config, pipeline_cls=CategoryMLPipeline)
        trainer.train(X_train=train_records, y_train=train_labels)

        metrics = evaluate_multilabel_model(
            model=trainer.pipeline,
            X_test=test_records,
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

    train_records = clean_and_build_records(train_df, preprocessor)
    test_records = clean_and_build_records(test_df, preprocessor)

    train_labels = train_df["categories"].tolist()
    test_labels = test_df["categories"].tolist()

    results, trained = train_and_evaluate(train_records, train_labels, test_records, test_labels)

    comparison = pd.DataFrame(
        [{k: v for k, v in r.items() if k != "per_label_f1"} for r in results]
    ).sort_values(["f1_micro", "hamming_loss"], ascending=[False, True])

    print("\n================ CATEGORY BASELINE COMPARISON (SYNTHETIC test set) ================\n")
    print(comparison.to_string(index=False))

    best_row = comparison.iloc[0]
    best_model_type = best_row["model"]
    best_result = next(r for r in results if r["model"] == best_model_type)

    print(f"\nBest model: {best_model_type}")
    print(f"F1-micro: {best_result['f1_micro']}  |  Hamming Loss: {best_result['hamming_loss']}")
    print("\nPer-label F1:", best_result["per_label_f1"])

    f1_micro_target = 0.80  # PRD §14.1 business threshold
    print(
        f"\n[INFO] PRD target: F1-micro > {f1_micro_target}. This target is NOT evaluable as "
        "PRD-compliant here — this dataset is synthetic (docs/data_audit_categorization.md). "
        "Reported for pipeline-validation reference only."
    )

    model_version = f"{best_model_type}-{datetime.now(UTC):%Y%m%d-%H%M%S}"

    # Phase 15A / FR-71: training no longer writes directly to
    # artifacts/category_baseline.joblib (the serving path) -- that was
    # exactly the "candidate becomes production merely because training
    # completed successfully" shortcut the promotion policy forbids (see
    # train_spam_model.py's own comment on this same behavior change).
    # Only scripts/mlops/promote_model.py writes there now.
    versioned_artifact_manager = ArtifactManager(artifact_dir="artifacts/versions")
    versioned_artifact_manager.save_model(
        trained[best_model_type].pipeline, f"category_{model_version}.joblib"
    )

    candidate_metrics = {
        "comparison": results,
        "best_model": best_model_type,
        "model_version": model_version,
        "labels": list(trained[best_model_type].pipeline.classes_),
        "f1_micro_target": f1_micro_target,
        "meets_f1_micro_target": bool(best_result["f1_micro"] >= f1_micro_target),
        "train_size": len(train_df),
        "test_size": len(test_df),
        "SYNTHETIC_DATA": True,
        "PRD_COMPLIANT": False,
        "warning": (
            "Trained on data/processed/category_synthetic_v1 (heuristic multi-label "
            "tags, not human-annotated). These metrics validate the pipeline "
            "mechanically; they are not evidence of real-world categorization "
            "quality. See docs/data_audit_categorization.md and "
            "docs/model_cards/email_categorization.md."
        ),
    }
    versioned_artifact_manager.save_json(candidate_metrics, f"category_{model_version}_metrics.json")

    print(f"\nModel version: {model_version}")
    print(f"Versioned artifact: artifacts/versions/category_{model_version}.joblib")

    try:
        from app.mlops.mlflow_client import log_training_run, register_candidate

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "category_baseline.joblib"
            ArtifactManager(artifact_dir=tmp).save_model(trained[best_model_type].pipeline, "category_baseline.joblib")
            run_id = log_training_run(
                experiment_name="category",
                model_filename="category_baseline.joblib",
                local_artifact_path=tmp_path,
                params={"model_type": best_model_type, "train_size": len(train_df)},
                metrics={
                    "f1_micro": best_result["f1_micro"],
                    "f1_macro": best_result["f1_macro"],
                    "f1_weighted": best_result["f1_weighted"],
                    "hamming_loss": best_result["hamming_loss"],
                    "precision_micro": best_result["precision_micro"],
                    "recall_micro": best_result["recall_micro"],
                    "subset_accuracy": best_result["subset_accuracy"],
                },
                tags={
                    "project_module": "category",
                    "evidence_status": MODULE_EVIDENCE_STATUS["category"].value,
                    "git_commit": _git_commit(),
                    "dataset_version": "category_synthetic_v1",
                    "model_version": model_version,
                },
            )
        candidate_version = register_candidate(run_id=run_id, model_name=MLFLOW_MODEL_NAME)
        print(f"\n[OK] Registered as MLflow candidate: {MLFLOW_MODEL_NAME} version {candidate_version} (run_id={run_id})")
        print(
            f"This is NOT deployed yet. To promote it to production:\n"
            f"    python -m scripts.mlops.promote_model --module category --version {candidate_version}"
        )
    except Exception as exc:  # noqa: BLE001 -- MLflow being unreachable must not fail training
        print(f"\n[WARN] MLflow logging/registration skipped ({type(exc).__name__}: {exc}). "
              "Artifact was still saved locally under artifacts/versions/.")


if __name__ == "__main__":
    main()
