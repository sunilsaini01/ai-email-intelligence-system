"""
Sentiment Analysis: SYNTHETIC BOOTSTRAP dataset generator.

============================================================================
THIS DATASET IS NOT PRD-COMPLIANT. DO NOT TREAT ITS LABELS AS GROUND TRUTH.
See docs/data_audit_sentiment.md §4 for the full data strategy decision.
============================================================================

What this does: takes REAL Enron email text (same source and sampling
approach as generate_synthetic_priority_dataset.py) and assigns a 5-class
sentiment label — Very Negative / Negative / Neutral / Positive / Very
Positive — by bucketing VADER's lexicon-based compound polarity score, NOT
via human annotation. Unlike priority/category's heuristic label generators,
there is no separate "keyword feature vs. label generator" leakage channel
here in the traditional sense (VADER is not one of ContentFeatures' fields),
but a different, arguably more direct one exists instead: any classifier
trained on this dataset is trained to predict VADER's own output, so its
ceiling is agreement with VADER, not improvement over it. This is why the
resulting dataset is used only as a documented comparison baseline in this
phase (see train_sentiment_model.py), not as the served model's training
data — see docs/data_audit_sentiment.md §4 for the full reasoning.

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/generate_synthetic_sentiment_dataset.py

Produces:
    data/processed/sentiment_synthetic_v1/{train,val,test}.parquet
    data/processed/sentiment_synthetic_v1/run_metadata.json
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.training.logger import get_logger

logger = get_logger()

RAW_ENRON_CSV = "data/raw/enron/emails.csv"
OUTPUT_DIR = Path("data/processed/sentiment_synthetic_v1")
SAMPLE_SIZE = 10_000  # same target scale as priority/category's bootstraps
RANDOM_STATE = 42

LABELS = ["Very Negative", "Negative", "Neutral", "Positive", "Very Positive"]

# Bucket thresholds on VADER's compound score — see docs/data_audit_sentiment.md
# §3 for why -0.05/+0.05 (VADER's own published neutral band) and +-0.6
# (this phase's own, disclosed-as-heuristic choice) were used.
_VERY_NEGATIVE_MAX = -0.6
_NEGATIVE_MAX = -0.05
_POSITIVE_MIN = 0.05
_VERY_POSITIVE_MIN = 0.6


def bucket_compound(compound: float) -> str:
    if compound <= _VERY_NEGATIVE_MAX:
        return "Very Negative"
    if compound <= _NEGATIVE_MAX:
        return "Negative"
    if compound < _POSITIVE_MIN:
        return "Neutral"
    if compound < _VERY_POSITIVE_MIN:
        return "Positive"
    return "Very Positive"


def load_sample(n: int) -> pd.DataFrame:
    """
    Reuses the exact same over-fetch/parse/dedup approach as
    generate_synthetic_priority_dataset.py's load_sample() — see that
    file's docstring for why. Duplicated here rather than imported: that
    function isn't exposed as shared infrastructure (it's a script-local
    helper in a one-off generator script), and importing across sibling
    scripts would create a coupling neither script's own docstring
    documents or expects.
    """
    import email as email_lib

    from app.data_ingestion.enron_loader import _extract_body_text

    logger.info("Loading %d Enron emails from %s", n, RAW_ENRON_CSV)
    raw = pd.read_csv(RAW_ENRON_CSV, encoding="latin-1", nrows=n * 3)
    raw = raw.dropna(subset=["message"]).drop_duplicates(subset=["message"])

    records = []
    for _, row in raw.iterrows():
        try:
            msg = email_lib.message_from_string(row["message"])
            records.append(
                {
                    "source": "enron",
                    "message_id": msg.get("Message-ID", ""),
                    "sender_email": (msg.get("From", "") or "").strip(),
                    "subject_raw": msg.get("Subject", "") or "",
                    "received_at_raw": msg.get("Date", ""),
                    "body_text_raw": _extract_body_text(msg),
                }
            )
        except Exception as e:
            logger.warning("Skipping unparseable message: %s", e)
            continue

    result = pd.DataFrame(records)
    result = result[result["body_text_raw"].str.strip().str.len() > 0]
    result = result.drop_duplicates(subset=["body_text_raw"])
    return result.head(n).reset_index(drop=True)


def assign_labels(df: pd.DataFrame) -> pd.DataFrame:
    analyzer = SentimentIntensityAnalyzer()

    compounds = []
    for _, row in df.iterrows():
        text = f"{row['subject_raw']} {row['body_text_raw']}".strip()
        # VADER has no practical input-length limit worth guarding here —
        # unlike the abstractive summarizer's transformer, this is a
        # linear lexicon lookup, not a fixed-context-window model.
        scores = analyzer.polarity_scores(text)
        compounds.append(scores["compound"])

    df["vader_compound"] = compounds
    df["sentiment_label"] = df["vader_compound"].apply(bucket_compound)
    return df


def leakage_safe_split(df: pd.DataFrame):
    """Identical mechanism to generate_synthetic_priority_dataset.py — see
    docs/data_audit_sentiment.md §5 for why."""
    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=RANDOM_STATE)
    train_idx, temp_idx = next(gss.split(df, groups=df["sender_email"]))
    train_df = df.iloc[train_idx].reset_index(drop=True)
    temp_df = df.iloc[temp_idx].reset_index(drop=True)

    gss2 = GroupShuffleSplit(n_splits=1, test_size=0.5, random_state=RANDOM_STATE)
    val_idx, test_idx = next(gss2.split(temp_df, groups=temp_df["sender_email"]))
    val_df = temp_df.iloc[val_idx].reset_index(drop=True)
    test_df = temp_df.iloc[test_idx].reset_index(drop=True)

    return train_df, val_df, test_df


def main():
    df = load_sample(SAMPLE_SIZE)
    logger.info("Loaded %d unique, non-empty Enron emails", len(df))

    df = assign_labels(df)
    logger.info("Label distribution (VADER-derived):\n%s", df["sentiment_label"].value_counts())

    unique_senders = df["sender_email"].nunique()
    logger.info("Unique senders: %d (grouping unit for the split)", unique_senders)

    train_df, val_df, test_df = leakage_safe_split(df)
    logger.info(
        "Split sizes -> train: %d, val: %d, test: %d", len(train_df), len(val_df), len(test_df)
    )

    train_senders = set(train_df["sender_email"])
    val_senders = set(val_df["sender_email"])
    test_senders = set(test_df["sender_email"])
    overlap = (train_senders & val_senders) | (train_senders & test_senders) | (val_senders & test_senders)
    assert not overlap, f"Sender leakage across splits: {overlap}"
    logger.info("Verified: zero sender overlap across train/val/test")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_columns = [
        "message_id",
        "sender_email",
        "subject_raw",
        "body_text_raw",
        "received_at_raw",
        "sentiment_label",
        "vader_compound",
    ]

    for name, split_df in [("train", train_df), ("val", val_df), ("test", test_df)]:
        split_df[output_columns].to_parquet(OUTPUT_DIR / f"{name}.parquet", index=False)

    metadata = {
        "dataset": "sentiment_synthetic_v1",
        "SYNTHETIC": True,
        "PRD_COMPLIANT": False,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": RAW_ENRON_CSV,
        "label_source": "VADER SentimentIntensityAnalyzer compound score, bucketed (see module docstring)",
        "sample_size_requested": SAMPLE_SIZE,
        "final_row_count": len(df),
        "unique_senders": unique_senders,
        "label_distribution": df["sentiment_label"].value_counts().to_dict(),
        "split_sizes": {"train": len(train_df), "val": len(val_df), "test": len(test_df)},
        "split_method": "GroupShuffleSplit on sender_email (leakage-safe, not random row split)",
        "warning": (
            "Labels are VADER-lexicon-derived, not human-annotated. A classifier "
            "trained on this dataset can only approximate VADER's own scoring "
            "function -- see docs/data_audit_sentiment.md for the full rationale "
            "and why this dataset is used for baseline comparison only, not as "
            "the served model's training data."
        ),
    }
    (OUTPUT_DIR / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("\n================ SYNTHETIC SENTIMENT DATASET (NOT PRD-COMPLIANT) ================\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
