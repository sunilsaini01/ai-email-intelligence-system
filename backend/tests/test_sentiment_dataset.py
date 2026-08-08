"""
Data-quality tests for the synthetic sentiment bootstrap dataset (Phase 7A),
mirroring test_priority_dataset.py's structure. These test the DATASET, not
the model -- would fail identically if the generator's leakage-safe split
regressed, independent of any downstream training.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

DATA_DIR = Path(__file__).resolve().parents[2] / "data/processed/sentiment_synthetic_v1"
VALID_LABELS = {"Very Negative", "Negative", "Neutral", "Positive", "Very Positive"}

pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "train.parquet").exists(),
    reason="sentiment_synthetic_v1 not found — run scripts/generate_synthetic_sentiment_dataset.py first",
)


@pytest.fixture(scope="module")
def splits():
    return {
        name: pd.read_parquet(DATA_DIR / f"{name}.parquet") for name in ("train", "val", "test")
    }


def test_required_columns_present(splits):
    required = {"message_id", "sender_email", "body_text_raw", "sentiment_label", "vader_compound"}
    for name, df in splits.items():
        assert required.issubset(df.columns), f"{name} split missing columns: {required - set(df.columns)}"


def test_labels_are_within_taxonomy(splits):
    for name, df in splits.items():
        invalid = set(df["sentiment_label"].unique()) - VALID_LABELS
        assert not invalid, f"{name} split has invalid labels: {invalid}"


def test_no_missing_body_text_or_labels(splits):
    for name, df in splits.items():
        assert df["body_text_raw"].isna().sum() == 0, f"{name} split has null body text"
        assert df["sentiment_label"].isna().sum() == 0, f"{name} split has null labels"
        assert (df["body_text_raw"].str.strip().str.len() > 0).all(), f"{name} split has empty bodies"


def test_no_duplicate_bodies_within_a_split(splits):
    for name, df in splits.items():
        dupes = df["body_text_raw"].duplicated().sum()
        assert dupes == 0, f"{name} split has {dupes} duplicate email bodies"


def test_no_sender_leakage_across_splits(splits):
    """The whole point of docs/data_audit_sentiment.md §5's grouped split —
    a regression here means the generator silently went back to row-level
    splitting, which would quietly inflate any downstream comparison metric."""
    train_senders = set(splits["train"]["sender_email"])
    val_senders = set(splits["val"]["sender_email"])
    test_senders = set(splits["test"]["sender_email"])

    assert not (train_senders & val_senders), "sender overlap between train and val"
    assert not (train_senders & test_senders), "sender overlap between train and test"
    assert not (val_senders & test_senders), "sender overlap between val and test"


def test_label_is_a_deterministic_function_of_vader_compound(splits):
    """The label is not independent information -- it's bucket_compound()
    applied to vader_compound. A mismatch here means the dataset and the
    served predictor's bucketing logic have drifted apart."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.inference.sentiment_predictor import bucket_compound

    for name, df in splits.items():
        mismatches = (
            df["vader_compound"].apply(bucket_compound) != df["sentiment_label"]
        ).sum()
        assert mismatches == 0, f"{name} split: {mismatches} rows where the label disagrees with bucket_compound(vader_compound)"


def test_run_metadata_discloses_synthetic_status():
    """Enforces the data-strategy decision (docs/data_audit_sentiment.md §4)
    at the file level — if someone regenerates this dataset and forgets to
    carry the disclosure forward, this test catches it, not a future reader."""
    metadata = json.loads((DATA_DIR / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["SYNTHETIC"] is True
    assert metadata["PRD_COMPLIANT"] is False
    assert "warning" in metadata
