"""
Phase 6 — Email Summarization: prepare the BBC News Summary evaluation
dataset.

============================================================================
REAL, HUMAN-WRITTEN SUMMARIES -- but of NEWS ARTICLES, NOT EMAIL. See
docs/data_audit_summarization.md for exactly what this does and does not
license claiming. Unlike Phase 4/5's generators, this script does NOT
fabricate any label -- every reference summary here was written by a human
editor. What's being disclosed is a DOMAIN/FORMAT mismatch (news vs. email;
142-word median summaries vs. FR-25's 2-3-sentence target), not a
ground-truth-fabrication problem.
============================================================================

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/prepare_summarization_dataset.py

Produces:
    data/processed/summarization_bbc_v1/{train,val,test}.parquet
    data/processed/summarization_bbc_v1/run_metadata.json
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data_ingestion.bbc_summary_loader import load_bbc_news_summary
from app.training.logger import get_logger

logger = get_logger()

RAW_DIR = "data/raw/cnn_dailymail/BBC News Summary"  # see docs/data_audit_summarization.md §2
# for why this directory is misleadingly named
OUTPUT_DIR = Path("data/processed/summarization_bbc_v1")
RANDOM_STATE = 42


def main():
    logger.info("Loading BBC News Summary from %s", RAW_DIR)
    df = load_bbc_news_summary(RAW_DIR)
    logger.info("Loaded %d article/summary pairs", len(df))

    duplicates = int(df["body_text_raw"].duplicated().sum())
    df = df.drop_duplicates(subset=["body_text_raw"]).reset_index(drop=True)
    logger.info("Dropped %d duplicate article bodies -> %d remain", duplicates, len(df))

    train_df, temp_df = train_test_split(
        df, test_size=0.2, random_state=RANDOM_STATE, stratify=df["category"]
    )
    val_df, test_df = train_test_split(
        temp_df, test_size=0.5, random_state=RANDOM_STATE, stratify=temp_df["category"]
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_columns = ["source", "category", "body_text_raw", "summary_reference"]
    for name, split_df in [("train", train_df), ("val", val_df), ("test", test_df)]:
        split_df[output_columns].reset_index(drop=True).to_parquet(
            OUTPUT_DIR / f"{name}.parquet", index=False
        )

    metadata = {
        "dataset": "summarization_bbc_v1",
        "SYNTHETIC": False,  # summaries are real, human-written -- see module docstring
        "PRD_COMPLIANT": False,  # domain (news, not email) and format (length) mismatch -- see data audit
        "generated_at": datetime.now(UTC).isoformat(),
        "source": RAW_DIR,
        "original_row_count": len(df) + duplicates,
        "duplicates_dropped": int(duplicates),
        "final_row_count": len(df),
        "category_distribution": {k: int(v) for k, v in df["category"].value_counts().items()},
        "split_sizes": {"train": len(train_df), "val": len(val_df), "test": len(test_df)},
        "split_method": "stratified by category, sklearn train_test_split (not sender/thread-grouped -- "
        "no sender/thread concept exists for news articles)",
        "warning": (
            "Summaries are REAL and human-written (not fabricated), but this is a NEWS dataset, "
            "not email -- see docs/data_audit_summarization.md for the full domain/format mismatch "
            "disclosure. Supports genuine model-quality comparison (extractive vs. abstractive); "
            "does NOT support any PRD-compliance claim for FR-25/26/27."
        ),
    }
    (OUTPUT_DIR / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("\n================ SUMMARIZATION EVAL DATASET (BBC News Summary, real but off-domain) ================\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
