"""
Phase 3 — Spam Detection: train and evaluate baseline models on the real
SpamAssassin corpus (not the toy in-memory samples used by the smoke tests),
with a real Enron business-email sample mixed into the ham class.

Why the Enron mix: SpamAssassin-only training left the model never having
seen real, modern business correspondence as ham -- live testing found
59.3% of ordinary business email flagged as spam even after recalibrating
the decision threshold alone (see scripts/recalibrate_spam_threshold.py,
which now evaluates against a DIFFERENT, disjoint Enron slice than the one
mixed in here -- see split_enron_corpus()'s docstring for how that's kept
leak-free).

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/train_spam_model.py

Produces:
    artifacts/spam_baseline.joblib   — the best baseline model (by recall)
    artifacts/spam_baseline_metrics.json — comparison report for all baselines
    data/interim/enron_holdout_eval.parquet — held-out Enron slice for
        scripts/recalibrate_spam_threshold.py
"""

import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import precision_score, recall_score
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.pipeline_metadata import PipelineRun
from app.data_ingestion.checksum_utils import verify_checksum
from app.data_ingestion.enron_loader import load_enron_kaggle
from app.data_ingestion.spamassassin_loader import load_spamassassin
from app.evaluation.model_evaluator import evaluate_model
from app.mlops.model_metadata import MODULE_EVIDENCE_STATUS
from app.pipeline.pipeline_config import PipelineConfig
from app.preprocessing.email_preprocessor import SPAM_CONFIG, EmailPreprocessor
from app.training.artifact_manager import ArtifactManager
from app.training.logger import get_logger
from app.training.trainer import Trainer

MLFLOW_MODEL_NAME = "spam"


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"

logger = get_logger()

RAW_DATA_DIR = "data/raw/spamassassin"
MODEL_TYPES = ["logistic_regression", "naive_bayes", "svm"]
RECALL_TARGET = 0.99

# Real, out-of-domain business email mixed into the ham class -- SpamAssassin
# alone (2000s mailing-list-era content) never taught this model what
# ordinary modern business correspondence looks like, which is exactly why
# live testing found 59.3% of real business email flagged as spam even
# after threshold recalibration (scripts/recalibrate_spam_threshold.py) --
# a threshold can only move the operating point on a decision boundary the
# model already has; it can't teach the model a class it's never seen.
# Sizes are deliberately disjoint by construction (see split_enron_corpus):
# ENRON_TRAIN_MIX_SIZE rows go into training, the NEXT ENRON_HOLDOUT_SIZE
# rows are saved untouched for scripts/recalibrate_spam_threshold.py to
# evaluate against -- if both scripts sampled independently (even with
# different random seeds) there'd be no guarantee against overlap, which
# would make "held-out" evaluation meaningless.
ENRON_CSV = "data/raw/enron/emails.csv"
ENRON_CHECKSUM = "data/raw/enron/CHECKSUM.sha256"
ENRON_TRAIN_MIX_SIZE = 3000
ENRON_HOLDOUT_SIZE = 3000
ENRON_HOLDOUT_PATH = "data/interim/enron_holdout_eval.parquet"

# Overrides PipelineConfig's default "balanced" — see that field's docstring.
# Derived empirically for THIS corpus by scripts/experiment_class_weight_tuning.py:
# "balanced" (~1:2.3 here) caps SVM recall at 0.9889; 1:4 reaches 0.9944 at
# *higher* precision (0.9133 vs 0.9128) — not a trade-off, a strict improvement.
# Naive Bayes ignores class_weight entirely (sklearn's NB estimators don't
# accept the parameter), so this only affects Logistic Regression and SVM.
SPAM_CLASS_WEIGHT = {0: 1, 1: 4}


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


def split_enron_corpus() -> pd.DataFrame:
    """Loads real Enron business email, verifies its checksum, shuffles it
    deterministically, and returns only the training-mix slice -- rows
    [ENRON_TRAIN_MIX_SIZE : ENRON_TRAIN_MIX_SIZE + ENRON_HOLDOUT_SIZE] are
    written to ENRON_HOLDOUT_PATH untouched (not returned here) so
    scripts/recalibrate_spam_threshold.py can evaluate against them without
    ever re-deriving the same rows this function trained on."""
    logger.info("Verifying Enron corpus checksum before use")
    verify_checksum(ENRON_CSV, ENRON_CHECKSUM)

    logger.info("Loading Enron corpus (real business email) for training mix + held-out eval")
    df = load_enron_kaggle(ENRON_CSV)
    df = df[df["body_text_raw"].str.len() > 20].reset_index(drop=True)

    # frac=1 with a fixed random_state -- a deterministic full shuffle, not
    # two independent .sample() calls, is what makes the two slices below
    # provably disjoint rather than "probably disjoint."
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)

    train_mix = df.iloc[:ENRON_TRAIN_MIX_SIZE].copy()
    holdout = df.iloc[ENRON_TRAIN_MIX_SIZE : ENRON_TRAIN_MIX_SIZE + ENRON_HOLDOUT_SIZE].copy()

    Path(ENRON_HOLDOUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    holdout.to_parquet(ENRON_HOLDOUT_PATH)
    logger.info(
        "Enron split: %d rows into training mix, %d rows held out -> %s",
        len(train_mix),
        len(holdout),
        ENRON_HOLDOUT_PATH,
    )

    train_mix["spam_label"] = "ham"  # every Enron email is genuine business correspondence, never spam
    return train_mix[["body_text_raw", "spam_label"]].assign(source="enron")


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
    mlflow_run_ids: dict[str, str | None] = {}
    git_commit = _git_commit()

    for model_type in MODEL_TYPES:
        logger.info("Training %s", model_type)

        config = PipelineConfig(model_type=model_type, task="spam", class_weight=SPAM_CLASS_WEIGHT)
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

        # Logged for EVERY candidate, not just the eventual winner -- real
        # model comparison (Phase 15A / FR-71 Phase 5) needs more than one
        # run to compare against. Registration (a Model Registry version)
        # happens later in main(), only for whichever model wins selection.
        # Failure here (MLflow unreachable) must not fail training itself --
        # the local artifact/metrics files this script produces are still
        # useful on their own, same graceful-degradation stance every other
        # optional dependency in this codebase already takes (Kafka
        # producer warmup, LLM provider warmup, etc.).
        try:
            from app.mlops.mlflow_client import log_training_run

            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp) / "spam_baseline.joblib"
                ArtifactManager(artifact_dir=tmp).save_model(trainer.pipeline, "spam_baseline.joblib")
                run_id = log_training_run(
                    experiment_name="spam",
                    model_filename="spam_baseline.joblib",
                    local_artifact_path=tmp_path,
                    params={
                        "model_type": model_type,
                        "class_weight": str(SPAM_CLASS_WEIGHT),
                        "calibrated_threshold": round(threshold, 4),
                        "train_size": len(train_df),
                    },
                    metrics={
                        "accuracy_at_0.5": metrics["accuracy"],
                        "precision_at_0.5": metrics["precision"],
                        "recall_at_0.5": metrics["recall"],
                        "f1_at_0.5": metrics["f1_score"],
                        "roc_auc": metrics.get("roc_auc", 0.0),
                        "recall_at_threshold": test_recall_at_threshold,
                        "precision_at_threshold": test_precision_at_threshold,
                    },
                    tags={
                        "project_module": "spam",
                        "evidence_status": MODULE_EVIDENCE_STATUS["spam"].value,
                        "git_commit": git_commit,
                        "dataset_version": "spamassassin+enron_v1",
                    },
                )
            mlflow_run_ids[model_type] = run_id
            logger.info("mlflow_run_logged", extra={"model_type": model_type, "run_id": run_id})
        except Exception as exc:  # noqa: BLE001 -- MLflow being unreachable must not fail training
            mlflow_run_ids[model_type] = None
            logger.warning("mlflow_logging_skipped: %s: %s", type(exc).__name__, exc)

    return results, trained, mlflow_run_ids


def main():
    # PipelineRun existed since Phase 1/2 scaffolding but was never actually
    # called by any real training script (confirmed by a dead-code sweep --
    # its only prior reference was a since-deleted test, which left a stray
    # dummy run_metadata.json with a fake "dummy_checksum_123" checksum
    # sitting in data/processed/v1.0/, now removed). Every OTHER dataset
    # script in this project (generate_synthetic_*.py, etc.) already writes
    # its own ad-hoc run_metadata.json rather than using this shared class --
    # wiring it in here, for the one training script with no lineage record
    # at all, uses the utility as originally intended instead of adding a
    # fourth reimplementation of the same pattern.
    run = PipelineRun(version="spam_baseline_v1", script_name="train_spam_model.py")
    run.log_input(RAW_DATA_DIR, checksum="not applicable -- directory of individual raw email files, not a single checksummable archive")

    df = load_dataset()
    run.log_step("load_dataset", {"raw_email_count": len(df)})

    enron_mix = split_enron_corpus()
    run.log_input(ENRON_CSV, checksum=Path(ENRON_CHECKSUM).read_text().strip())
    run.log_step(
        "mix_in_enron_business_email",
        {
            "enron_train_mix_count": len(enron_mix),
            "reason": "SpamAssassin-only ham never taught the model real business-email "
            "language; live testing found 59.3% of business email flagged as spam even "
            "after threshold recalibration alone",
        },
    )
    df = pd.concat([df, enron_mix], ignore_index=True)

    df = clean_dataset(df)
    run.log_step("clean_dataset", {"cleaned_email_count": len(df)})

    train_df, val_df, test_df = split_dataset(df)
    run.log_step("split_dataset", {"train": len(train_df), "val": len(val_df), "test": len(test_df)})

    results, trained, mlflow_run_ids = train_and_evaluate(train_df, val_df, test_df)
    run.log_step("train_and_evaluate", {"models_compared": [r["model"] for r in results]})

    comparison = pd.DataFrame(results).sort_values(
        ["recall_at_threshold", "precision_at_threshold"], ascending=[False, False]
    )

    print("\n================ SPAM BASELINE COMPARISON (real test set) ================\n")
    print(comparison.to_string(index=False))

    # Sorting on recall alone (the previous selection rule) picks whichever
    # model's own pick_recall_threshold() found the LOWEST threshold needed
    # to clear RECALL_TARGET -- with the Enron mix added, that was
    # naive_bayes at threshold=0.03, recall=0.9945, but precision=0.4545
    # (confirmed by actually running this: naive_bayes "won" the old sort
    # over SVM's recall=0.9834/precision=0.8318, which is obviously the
    # better real-world model). A model that flags more ham as spam than it
    # correctly catches spam is worse than the false-positive problem this
    # retraining set out to fix, not an improvement -- so precision has to
    # gate selection too, not just break ties.
    MIN_PRECISION_FLOOR = 0.7
    viable = comparison[comparison["precision_at_threshold"] >= MIN_PRECISION_FLOOR]
    if viable.empty:
        print(
            f"\n[WARN] No model clears the {MIN_PRECISION_FLOOR} precision floor at its "
            "calibrated threshold -- falling back to pure recall ranking (previous behavior)."
        )
        best_row = comparison.iloc[0]
    else:
        best_row = viable.sort_values(
            ["recall_at_threshold", "precision_at_threshold"], ascending=[False, False]
        ).iloc[0]
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

    # Version string identifies *this specific training run's* artifact — not a
    # semantic "v1/v2" (that implies deliberate release management we don't have
    # yet), just enough to answer "which run produced the model currently
    # serving traffic" when someone is debugging a regression.
    model_version = f"{best_model_type}-{datetime.now(UTC):%Y%m%d-%H%M%S}"

    # Phase 15A / FR-71 behavior change, stated plainly: training used to
    # write directly to artifacts/spam_baseline.joblib (the live serving
    # path) -- "run training, restart the API" was the entire deployment
    # process. That is exactly the "candidate becomes production merely
    # because training completed successfully" shortcut the promotion
    # policy explicitly forbids (docs/model_promotion_policy.md). Training
    # now ONLY produces a versioned candidate + an MLflow registration;
    # nothing here touches the serving path. Deploying it is a separate,
    # explicit step: scripts/mlops/promote_model.py.
    versioned_artifact_manager = ArtifactManager(artifact_dir="artifacts/versions")
    versioned_path = versioned_artifact_manager.save_model(
        trained[best_model_type].pipeline,
        f"spam_{model_version}.joblib",
    )
    run.log_output(str(versioned_path), record_count=len(train_df))

    candidate_metrics = {
        "comparison": results,
        "best_model": best_model_type,
        "model_version": model_version,
        "decision_threshold": float(best_row["calibrated_threshold"]),
        "recall_target": RECALL_TARGET,
        "meets_target": meets_target,
        "train_size": len(train_df),
        "val_size": len(val_df),
        "test_size": len(test_df),
    }
    versioned_artifact_manager.save_json(candidate_metrics, f"spam_{model_version}_metrics.json")
    run.log_output(f"artifacts/versions/spam_{model_version}_metrics.json", record_count=len(results))

    run_output_dir = Path("data/processed/spam_baseline_v1")
    run_output_dir.mkdir(parents=True, exist_ok=True)
    run.save(str(run_output_dir))

    print(f"\nModel version: {model_version}")
    print(f"Versioned artifact: {versioned_path}")

    winning_run_id = mlflow_run_ids.get(best_model_type)
    if winning_run_id is None:
        print(
            "\n[WARN] MLflow was unreachable during training -- no candidate was "
            "registered. The trained artifact above still exists locally, but "
            "nothing was deployed and nothing can be promoted through "
            "scripts/mlops/promote_model.py until it's registered. Re-run this "
            "script once MLflow is reachable, or register the existing artifact "
            "manually (see docs/model_lifecycle.md \"Registering An Existing "
            "Artifact\")."
        )
    else:
        from app.mlops.mlflow_client import register_candidate, tag_run

        # model_version is only known now (computed after the comparison
        # loop that logged this run) -- tagging it post-hoc onto the
        # already-completed run is what lets promote_model.py recover an
        # accurate model_version string even when no metrics.json artifact
        # was logged alongside it (spam's per-candidate logging never logs
        # one -- see train_and_evaluate()'s own log_training_run call).
        tag_run(winning_run_id, "model_version", model_version)
        candidate_version = register_candidate(run_id=winning_run_id, model_name=MLFLOW_MODEL_NAME)
        print(
            f"\n[OK] Registered as MLflow candidate: {MLFLOW_MODEL_NAME} version "
            f"{candidate_version} (run_id={winning_run_id})"
        )
        print(
            f"This is NOT deployed yet. To promote it to production:\n"
            f"    python -m scripts.mlops.promote_model --module spam --version {candidate_version}"
        )


if __name__ == "__main__":
    main()
