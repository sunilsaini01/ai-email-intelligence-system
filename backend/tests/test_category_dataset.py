"""
Data-quality tests for the synthetic category bootstrap dataset (Phase 5
data audit and leakage-safe split). Mirrors test_priority_dataset.py's
structure, adapted for the multi-label `categories` column.

These test the DATASET, not the model — they'd fail identically if the
dataset were ever regenerated with a leakage-safe-split bug, independent of
whatever model gets trained on top of it. Skipped if the dataset hasn't been
generated.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from app.feature_engineering.category_keywords import CATEGORY_LABELS

DATA_DIR = Path(__file__).resolve().parents[2] / "data/processed/category_synthetic_v1"
VALID_LABELS = set(CATEGORY_LABELS)

pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "train.parquet").exists(),
    reason="category_synthetic_v1 not found — run scripts/generate_synthetic_category_dataset.py first",
)


@pytest.fixture(scope="module")
def splits():
    return {
        name: pd.read_parquet(DATA_DIR / f"{name}.parquet") for name in ("train", "val", "test")
    }


def test_required_columns_present(splits):
    required = {"message_id", "sender_email", "body_text_raw", "categories"}
    for name, df in splits.items():
        assert required.issubset(df.columns), f"{name} split missing columns: {required - set(df.columns)}"


def test_labels_are_within_taxonomy(splits):
    for name, df in splits.items():
        all_labels = {label for row in df["categories"] for label in row}
        invalid = all_labels - VALID_LABELS
        assert not invalid, f"{name} split has invalid labels: {invalid}"


def test_every_row_has_at_least_one_category(splits):
    """The General fallback (docs/data_audit_categorization.md §3) means no
    row should ever end up with zero labels in the dataset itself — an
    empty label list at inference time is a legitimate model output (see
    CategoryService's fallback), but the TRAINING data should never contain
    one, or the model never learns what "no other category applies" looks
    like."""
    for name, df in splits.items():
        empty = df["categories"].apply(len).eq(0).sum()
        assert empty == 0, f"{name} split has {empty} rows with zero categories"


def test_no_missing_body_text(splits):
    for name, df in splits.items():
        assert df["body_text_raw"].isna().sum() == 0, f"{name} split has null body text"
        assert (df["body_text_raw"].str.strip().str.len() > 0).all(), f"{name} split has empty bodies"


def test_no_duplicate_bodies_within_a_split(splits):
    for name, df in splits.items():
        dupes = df["body_text_raw"].duplicated().sum()
        assert dupes == 0, f"{name} split has {dupes} duplicate email bodies"


def test_no_sender_leakage_across_splits(splits):
    """The whole point of docs/data_audit_categorization.md §6's grouped
    split — a regression here means the dataset generator silently went
    back to row-level splitting, which would quietly inflate every
    downstream metric."""
    train_senders = set(splits["train"]["sender_email"])
    val_senders = set(splits["val"]["sender_email"])
    test_senders = set(splits["test"]["sender_email"])

    assert not (train_senders & val_senders), "sender overlap between train and val"
    assert not (train_senders & test_senders), "sender overlap between train and test"
    assert not (val_senders & test_senders), "sender overlap between val and test"


def test_average_labels_per_email_is_genuinely_multilabel(splits):
    """A value at or near 1.0 would suggest the multi-label generation
    logic degenerated into single-label assignment somewhere — this locks
    in that the dataset actually exercises FR-22, not just the taxonomy's
    label names."""
    avg = splits["train"]["categories"].apply(len).mean()
    assert avg > 1.1, f"train split's avg labels/email ({avg:.3f}) looks single-label, not multi-label"


def test_run_metadata_discloses_synthetic_status():
    """Enforces the data-strategy decision (docs/data_audit_categorization.md
    §4) at the file level — if someone regenerates this dataset and forgets
    to carry the disclosure forward, this test catches it, not a future
    reader."""
    metadata = json.loads((DATA_DIR / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["SYNTHETIC"] is True
    assert metadata["PRD_COMPLIANT"] is False
    assert "warning" in metadata
