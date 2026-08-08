"""
Data-quality tests for the synthetic intent bootstrap dataset (Phase 7B),
mirroring test_category_dataset.py's structure (multi-label, may have empty
label lists — unlike category, no "General" fallback exists here).
"""

import json
from pathlib import Path

import pandas as pd
import pytest

DATA_DIR = Path(__file__).resolve().parents[2] / "data/processed/intent_synthetic_v1"
VALID_LABELS = {
    "Complaint", "Inquiry", "Request", "Feedback", "Escalation",
    "Order", "Cancel", "Refund", "Schedule",
}

pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "train.parquet").exists(),
    reason="intent_synthetic_v1 not found — run scripts/generate_synthetic_intent_dataset.py first",
)


@pytest.fixture(scope="module")
def splits():
    return {
        name: pd.read_parquet(DATA_DIR / f"{name}.parquet") for name in ("train", "val", "test")
    }


def test_required_columns_present(splits):
    required = {"message_id", "sender_email", "body_text_raw", "intents"}
    for name, df in splits.items():
        assert required.issubset(df.columns), f"{name} split missing columns: {required - set(df.columns)}"


def test_labels_are_within_taxonomy(splits):
    for name, df in splits.items():
        all_labels = {label for row in df["intents"] for label in row}
        invalid = all_labels - VALID_LABELS
        assert not invalid, f"{name} split has invalid labels: {invalid}"


def test_empty_label_lists_are_allowed_but_not_universal(splits):
    """Unlike category (always >=1 label via the General fallback), intent
    rows may legitimately have zero labels -- but not EVERY row, or the
    generator's keyword scoring silently broke."""
    for name, df in splits.items():
        empty_count = df["intents"].apply(len).eq(0).sum()
        assert 0 < empty_count < len(df), f"{name} split: all-or-nothing empty-label rate looks broken ({empty_count}/{len(df)})"


def test_no_missing_body_text(splits):
    for name, df in splits.items():
        assert df["body_text_raw"].isna().sum() == 0, f"{name} split has null body text"
        assert (df["body_text_raw"].str.strip().str.len() > 0).all(), f"{name} split has empty bodies"


def test_no_duplicate_bodies_within_a_split(splits):
    for name, df in splits.items():
        dupes = df["body_text_raw"].duplicated().sum()
        assert dupes == 0, f"{name} split has {dupes} duplicate email bodies"


def test_no_sender_leakage_across_splits(splits):
    train_senders = set(splits["train"]["sender_email"])
    val_senders = set(splits["val"]["sender_email"])
    test_senders = set(splits["test"]["sender_email"])

    assert not (train_senders & val_senders), "sender overlap between train and val"
    assert not (train_senders & test_senders), "sender overlap between train and test"
    assert not (val_senders & test_senders), "sender overlap between val and test"


def test_run_metadata_discloses_synthetic_status():
    metadata = json.loads((DATA_DIR / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["SYNTHETIC"] is True
    assert metadata["PRD_COMPLIANT"] is False
    assert "warning" in metadata
