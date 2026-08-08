"""
Phase 7A — Sentiment Analysis: classical-baseline COMPARISON script.

============================================================================
NOT THE SERVED MODEL. Trained on data/processed/sentiment_synthetic_v1,
whose labels are VADER's own bucketed compound score, not human judgment.
This script exists to answer one specific, narrower question than
train_priority_model.py's "which classifier should we serve": CAN a
TF-IDF + classical-ML model learn to approximate VADER's lexicon-based
bucketing function from surface text patterns? It cannot, even in
principle, exceed the accuracy of the very function that generated its own
labels -- so "high accuracy" here means "successfully imitated VADER," not
"accurately classifies real email sentiment." See docs/data_audit_sentiment.md
§4 and docs/model_cards/sentiment.md "Model Selection" for the full
reasoning behind why VaderSentimentPredictor (app/inference/sentiment_predictor.py),
not the model trained here, is what backend/app/services/sentiment_service.py
actually serves.
============================================================================

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/train_sentiment_model.py

Produces (comparison artifacts only -- NOT loaded by SentimentService):
    artifacts/sentiment_comparison.joblib
    artifacts/sentiment_comparison_metrics.json
"""

import sys
import time
from pathlib import Path

import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.model_evaluator import evaluate_model
from app.inference.sentiment_predictor import VaderSentimentPredictor
from app.pipeline.ml_pipeline import MLPipeline
from app.pipeline.pipeline_config import PipelineConfig
from app.preprocessing.email_preprocessor import SENTIMENT_CONFIG, EmailPreprocessor
from app.training.artifact_manager import ArtifactManager
from app.training.logger import get_logger
from app.training.trainer import Trainer

logger = get_logger()

DATA_DIR = Path("data/processed/sentiment_synthetic_v1")
MODEL_TYPES = ["logistic_regression", "naive_bayes", "svm"]
LABELS = ["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"]
SENTIMENT_CLASS_WEIGHT = "balanced"  # label distribution is heavily skewed -- see run_metadata.json


def load_split(name: str) -> pd.DataFrame:
    df = pd.read_parquet(DATA_DIR / f"{name}.parquet")
    logger.info("Loaded %s split: %d rows", name, len(df))
    return df


def clean_texts(df: pd.DataFrame, preprocessor: EmailPreprocessor) -> list[str]:
    combined = (df["subject_raw"].fillna("") + " " + df["body_text_raw"].fillna("")).tolist()
    return preprocessor.process_batch(combined)


def train_and_evaluate(train_texts, train_labels, test_texts, test_labels):
    results = []
    trained = {}

    for model_type in MODEL_TYPES:
        logger.info("Training %s", model_type)

        config = PipelineConfig(
            model_type=model_type,
            task="sentiment",
            class_weight=SENTIMENT_CLASS_WEIGHT,
        )
        trainer = Trainer(config, pipeline_cls=MLPipeline)
        trainer.train(X_train=train_texts, y_train=train_labels)

        metrics = evaluate_model(
            model=trainer.pipeline,
            X_test=test_texts,
            y_test=test_labels,
            average="macro",
        )

        test_preds = trainer.pipeline.predict(test_texts)
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
                "weighted_f1": round(
                    f1_score(test_labels, test_preds, average="weighted", zero_division=0), 4
                ),
                "macro_precision": round(metrics["precision"], 4),
                "macro_recall": round(metrics["recall"], 4),
                "accuracy": round(metrics["accuracy"], 4),
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


def benchmark_vader(test_texts: list[str]) -> dict:
    """
    VADER's own latency/behavior on the same test split, run through the
    SERVED predictor code path (not re-implemented here) -- gives a direct,
    same-data latency comparison alongside the trained classifiers above.
    Accuracy is deliberately NOT reported as "VADER accuracy" here: since
    the test labels ARE VADER's own bucketed output, that number would be
    ~100% by construction (see module docstring), not a real evaluation.
    """
    predictor = VaderSentimentPredictor()
    start = time.perf_counter()
    results = [predictor.predict(text) for text in test_texts]
    total_ms = (time.perf_counter() - start) * 1000
    return {
        "avg_latency_ms": round(total_ms / len(test_texts), 4) if test_texts else 0.0,
        "total_ms_for_test_set": round(total_ms, 2),
        "test_set_size": len(test_texts),
        "note": (
            "Accuracy intentionally not reported here -- the test labels are "
            "VADER's own bucketed compound score, so 'VADER accuracy against "
            "them' is ~100% by construction, not a real evaluation. See "
            "docs/model_cards/sentiment.md."
        ),
    }


def main():
    preprocessor = EmailPreprocessor(SENTIMENT_CONFIG)

    train_df = load_split("train")
    test_df = load_split("test")

    train_texts = clean_texts(train_df, preprocessor)
    test_texts = clean_texts(test_df, preprocessor)

    train_labels = train_df["sentiment_label"].tolist()
    test_labels = test_df["sentiment_label"].tolist()

    results, trained = train_and_evaluate(train_texts, train_labels, test_texts, test_labels)

    comparison = pd.DataFrame(
        [
            {k: v for k, v in r.items() if k not in ("per_class_f1", "per_class_recall", "per_class_precision", "confusion_matrix")}
            for r in results
        ]
    ).sort_values(["macro_f1"], ascending=False)

    print("\n================ SENTIMENT CLASSIFIER-vs-VADER-LABEL COMPARISON (NOT a real-world accuracy measurement) ================\n")
    print(comparison.to_string(index=False))

    best_row = comparison.iloc[0]
    best_model_type = best_row["model"]
    best_result = next(r for r in results if r["model"] == best_model_type)

    vader_bench = benchmark_vader(test_texts)
    print("\nVADER (served predictor) latency on the same test split:", vader_bench)

    print(f"\nBest classifier at approximating VADER's own labels: {best_model_type}")
    print(f"Macro F1 (vs. VADER-derived test labels): {best_result['macro_f1']}")
    print("This measures label-imitation, not real-world sentiment accuracy -- see module docstring.")

    artifact_manager = ArtifactManager()
    artifact_manager.save_model(trained[best_model_type].pipeline, "sentiment_comparison.joblib")
    artifact_manager.save_json(
        {
            "comparison": results,
            "best_model": best_model_type,
            "labels": LABELS,
            "vader_benchmark": vader_bench,
            "train_size": len(train_df),
            "test_size": len(test_df),
            "SYNTHETIC_DATA": True,
            "PRD_COMPLIANT": False,
            "SERVED_BY_API": False,
            "warning": (
                "This artifact is NOT loaded by SentimentService. Test labels are "
                "VADER's own bucketed compound score (data/processed/sentiment_synthetic_v1), "
                "so these metrics measure how well a classical classifier can imitate "
                "VADER from surface text patterns, not real-world sentiment accuracy. "
                "See docs/data_audit_sentiment.md and docs/model_cards/sentiment.md."
            ),
        },
        "sentiment_comparison_metrics.json",
    )
    print("\nSaved: artifacts/sentiment_comparison.joblib, artifacts/sentiment_comparison_metrics.json")
    print("(Comparison artifacts only -- SentimentService serves VaderSentimentPredictor directly.)")


if __name__ == "__main__":
    main()
