"""
Data-quality tests for the synthetic priority bootstrap dataset (Phase 4
Step 2/Step 5 — data audit and leakage-safe split).

These test the DATASET, not the model — they'd fail identically if the
dataset were ever regenerated with a leakage-safe-split bug, independent of
whatever model gets trained on top of it. Skipped if the dataset hasn't been
generated (same pattern as the model-artifact skip in test_priority_endpoint.py).
"""

import json
from pathlib import Path

import pandas as pd
import pytest

DATA_DIR = Path(__file__).resolve().parents[2] / "data/processed/priority_synthetic_v1"
VALID_LABELS = {"Critical", "High", "Medium", "Low"}

pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "train.parquet").exists(),
    reason="priority_synthetic_v1 not found — run scripts/generate_synthetic_priority_dataset.py first",
)


@pytest.fixture(scope="module")
def splits():
    return {
        name: pd.read_parquet(DATA_DIR / f"{name}.parquet") for name in ("train", "val", "test")
    }


def test_required_columns_present(splits):
    required = {"message_id", "sender_email", "body_text_raw", "priority_label"}
    for name, df in splits.items():
        assert required.issubset(df.columns), f"{name} split missing columns: {required - set(df.columns)}"


def test_labels_are_within_taxonomy(splits):
    for name, df in splits.items():
        invalid = set(df["priority_label"].unique()) - VALID_LABELS
        assert not invalid, f"{name} split has invalid labels: {invalid}"


def test_no_missing_body_text_or_labels(splits):
    for name, df in splits.items():
        assert df["body_text_raw"].isna().sum() == 0, f"{name} split has null body text"
        assert df["priority_label"].isna().sum() == 0, f"{name} split has null labels"
        assert (df["body_text_raw"].str.strip().str.len() > 0).all(), f"{name} split has empty bodies"


def test_no_duplicate_bodies_within_a_split(splits):
    for name, df in splits.items():
        dupes = df["body_text_raw"].duplicated().sum()
        assert dupes == 0, f"{name} split has {dupes} duplicate email bodies"


def test_no_sender_leakage_across_splits(splits):
    """
    The whole point of docs/data_audit_priority.md §6's grouped split — a
    regression here means the dataset generator silently went back to
    row-level splitting, which would quietly inflate every downstream metric.
    """
    train_senders = set(splits["train"]["sender_email"])
    val_senders = set(splits["val"]["sender_email"])
    test_senders = set(splits["test"]["sender_email"])

    assert not (train_senders & val_senders), "sender overlap between train and val"
    assert not (train_senders & test_senders), "sender overlap between train and test"
    assert not (val_senders & test_senders), "sender overlap between val and test"


def test_run_metadata_discloses_synthetic_status():
    """
    Enforces the data-strategy decision (docs/data_audit_priority.md §4) at
    the file level — if someone regenerates this dataset and forgets to
    carry the disclosure forward, this test catches it, not a future reader.
    """
    metadata = json.loads((DATA_DIR / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["SYNTHETIC"] is True
    assert metadata["PRD_COMPLIANT"] is False
    assert "warning" in metadata
