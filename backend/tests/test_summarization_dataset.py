"""
Data-quality tests for summarization_bbc_v1 (Module 5). Mirrors
test_category_dataset.py/test_priority_dataset.py's structure, adapted:
this dataset's summaries are REAL (not synthetic/heuristic), so the
disclosure being enforced is SYNTHETIC=False / PRD_COMPLIANT=False (domain
mismatch), not the "labels are fabricated" warning the other two enforce.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

DATA_DIR = Path(__file__).resolve().parents[2] / "data/processed/summarization_bbc_v1"

pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "train.parquet").exists(),
    reason="summarization_bbc_v1 not found — run scripts/prepare_summarization_dataset.py first",
)


@pytest.fixture(scope="module")
def splits():
    return {
        name: pd.read_parquet(DATA_DIR / f"{name}.parquet") for name in ("train", "val", "test")
    }


def test_required_columns_present(splits):
    required = {"source", "category", "body_text_raw", "summary_reference"}
    for name, df in splits.items():
        assert required.issubset(df.columns), f"{name} split missing columns: {required - set(df.columns)}"


def test_every_row_has_a_non_empty_reference_summary(splits):
    for name, df in splits.items():
        assert df["summary_reference"].isna().sum() == 0, f"{name} split has null summaries"
        assert (df["summary_reference"].str.strip().str.len() > 0).all(), f"{name} split has empty summaries"


def test_no_duplicate_article_bodies_within_a_split(splits):
    for name, df in splits.items():
        dupes = df["body_text_raw"].duplicated().sum()
        assert dupes == 0, f"{name} split has {dupes} duplicate article bodies"


def test_run_metadata_discloses_domain_mismatch():
    """Enforces docs/data_audit_summarization.md's decision at the file
    level — SYNTHETIC=False (summaries ARE real) but PRD_COMPLIANT=False
    (wrong domain/format) must both be present, and both must stay correct
    if this dataset is ever regenerated."""
    metadata = json.loads((DATA_DIR / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["SYNTHETIC"] is False
    assert metadata["PRD_COMPLIANT"] is False
    assert "warning" in metadata


def test_category_distribution_is_stratified_across_splits(splits):
    """A regression here would mean the split silently went back to plain
    random splitting and one category could be starved in a given split."""
    for name, df in splits.items():
        categories_present = set(df["category"].unique())
        assert len(categories_present) == 5, f"{name} split is missing categories: {categories_present}"
