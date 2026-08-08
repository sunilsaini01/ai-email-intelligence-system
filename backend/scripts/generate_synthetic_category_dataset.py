"""
Phase 5 — Email Categorization: SYNTHETIC BOOTSTRAP dataset generator.

============================================================================
THIS DATASET IS NOT PRD-COMPLIANT. DO NOT TREAT ITS LABELS AS GROUND TRUTH.
See docs/data_audit_categorization.md §4 for the full data strategy decision.
============================================================================

What this does: takes REAL Enron email text and REAL email headers (sender,
date, recipients), and assigns MULTI-LABEL category tags (Support / Sales /
Billing / Legal / HR / IT / Marketing / General) via a documented,
deterministic keyword heuristic + injected label noise — NOT via human
annotation. Mirrors generate_synthetic_priority_dataset.py's role and
disclosure exactly, extended to a multi-label output. Exists to let the
Phase 5 pipeline be built and proven mechanically end-to-end while the real
annotation effort (docs/annotation_guidelines_categorization.md — 3
annotators, per-category Kappa >= 0.70) is unstarted, out-of-scope-for-this-
session work.

Why per-category ADAPTIVE thresholds, not a single fixed keyword-count
cutoff: the 7 category lexicons (app/feature_engineering/category_keywords.py)
have very different natural hit rates against Enron's actual (energy-sector,
2001-2002, pre-SaaS) vocabulary — e.g. "contract"/"agreement" (Legal) fire
constantly in this corpus, "bug"/"crash" (Support) almost never (Enron isn't
a software company with end users). A single fixed threshold would make
Legal fire on nearly everything and Support fire on nearly nothing,
independent of any real signal. Each category's own threshold is set from
its own nonzero-score distribution instead, the direct multi-label extension
of generate_synthetic_priority_dataset.py's per-run quantile approach.

Why inject per-category label noise: identical reasoning to
generate_synthetic_priority_dataset.py's `_apply_label_noise` — a purely
deterministic label is a direct function of the same keyword counts the
model trains on. Noise doesn't fix the deeper leakage problem (the label is
still keyword-derived, see docs/data_audit_categorization.md §4) but stops
the dataset from being a trivial lookup table.

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/generate_synthetic_category_dataset.py

Produces:
    data/processed/category_synthetic_v1/{train,val,test}.parquet
    data/processed/category_synthetic_v1/run_metadata.json
"""

import json
import sys
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.feature_engineering.category_keywords import CATEGORY_KEYWORDS, CATEGORY_LABELS
from app.training.logger import get_logger

logger = get_logger()

RAW_ENRON_CSV = "data/raw/enron/emails.csv"
OUTPUT_DIR = Path("data/processed/category_synthetic_v1")
SAMPLE_SIZE = 10_000  # matches Phase 4's precedent row count, not a data-quality bar — see §4
RANDOM_STATE = 42
NON_GENERAL_LABELS = [label for label in CATEGORY_LABELS if label != "General"]
NOISE_FLIP_RATE = 0.04  # per (row, category) bit — lower than priority's 8% single-level
# flip because a multi-label bit-flip is a more severe perturbation per
# affected label (adds/removes a whole category, not a one-level nudge)


def load_sample(n: int) -> pd.DataFrame:
    logger.info("Loading %d Enron emails from %s", n, RAW_ENRON_CSV)
    df = pd.read_csv(RAW_ENRON_CSV, encoding="latin-1", nrows=n * 4)  # over-fetch; rows get dropped
    records = list(load_enron_kaggle_from_df(df))
    result = pd.DataFrame(records)
    result = result[result["body_text_raw"].str.strip().str.len() > 0]
    result = result.drop_duplicates(subset=["body_text_raw"])
    return result.head(n).reset_index(drop=True)


def load_enron_kaggle_from_df(df: pd.DataFrame):
    """Same over-fetch-then-cap pattern as generate_synthetic_priority_dataset.py —
    parsing the full 500K-row / 1.4GB CSV just to sample 10K is wasteful."""
    import email as email_lib

    from app.data_ingestion.enron_loader import _extract_body_text

    df = df.dropna(subset=["message"]).drop_duplicates(subset=["message"])
    for _, row in df.iterrows():
        try:
            msg = email_lib.message_from_string(row["message"])
            yield {
                "source": "enron",
                "source_file": row.get("file", ""),
                "message_id": msg.get("Message-ID", ""),
                "sender_email": (msg.get("From", "") or "").strip(),
                "subject_raw": msg.get("Subject", "") or "",
                "received_at_raw": msg.get("Date", ""),
                "recipient_to_raw": msg.get("To", "") or "",
                "body_text_raw": _extract_body_text(msg),
            }
        except Exception as e:
            logger.warning("Skipping unparseable message: %s", e)
            continue


def _parse_date(raw: str) -> datetime:
    try:
        dt = parsedate_to_datetime(raw)
        if dt is None:
            return datetime(2001, 1, 1, tzinfo=UTC)
        return dt
    except (TypeError, ValueError):
        return datetime(2001, 1, 1, tzinfo=UTC)


def _keyword_score(text: str, keywords: frozenset) -> int:
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw in text_lower)


def score_categories(df: pd.DataFrame) -> pd.DataFrame:
    combined = (df["subject_raw"].fillna("") + " " + df["body_text_raw"].fillna("")).str.lower()

    for label in NON_GENERAL_LABELS:
        keywords = CATEGORY_KEYWORDS[label]
        df[f"score_{label}"] = combined.apply(lambda text, kw=keywords: _keyword_score(text, kw))

    return df


def assign_labels(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """
    Per-category adaptive threshold: a category is assigned if its keyword
    score is >= the 70th percentile of that category's OWN nonzero-score
    distribution (or >= 1 if the category has fewer than 5 nonzero rows in
    the sample — avoids a degenerate threshold when a category is naturally
    very rare in this corpus). Documented per-category in run_metadata.json,
    not a single silently-shared cutoff.
    """
    thresholds = {}
    raw_flags = {}

    for label in NON_GENERAL_LABELS:
        scores = df[f"score_{label}"]
        nonzero = scores[scores > 0]
        if len(nonzero) >= 5:
            threshold = max(1, int(np.ceil(nonzero.quantile(0.70))))
        else:
            threshold = 1
        thresholds[label] = threshold
        raw_flags[label] = (scores >= threshold).to_numpy()

    raw_flags_matrix = np.column_stack([raw_flags[label] for label in NON_GENERAL_LABELS])
    df["categories_raw"] = [
        [label for label, flag in zip(NON_GENERAL_LABELS, row, strict=True) if flag] or ["General"]
        for row in raw_flags_matrix
    ]

    noisy_matrix = raw_flags_matrix.copy()
    flip_mask = rng.random(noisy_matrix.shape) < NOISE_FLIP_RATE
    noisy_matrix = np.where(flip_mask, ~noisy_matrix, noisy_matrix)

    df["categories"] = [
        [label for label, flag in zip(NON_GENERAL_LABELS, row, strict=True) if flag] or ["General"]
        for row in noisy_matrix
    ]

    return df, thresholds


def leakage_safe_split(df: pd.DataFrame):
    """Identical mechanism to generate_synthetic_priority_dataset.py's
    leakage_safe_split — see docs/data_audit_categorization.md §6."""
    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=RANDOM_STATE)
    train_idx, temp_idx = next(gss.split(df, groups=df["sender_email"]))
    train_df = df.iloc[train_idx].reset_index(drop=True)
    temp_df = df.iloc[temp_idx].reset_index(drop=True)

    gss2 = GroupShuffleSplit(n_splits=1, test_size=0.5, random_state=RANDOM_STATE)
    val_idx, test_idx = next(gss2.split(temp_df, groups=temp_df["sender_email"]))
    val_df = temp_df.iloc[val_idx].reset_index(drop=True)
    test_df = temp_df.iloc[test_idx].reset_index(drop=True)

    return train_df, val_df, test_df


def _label_distribution(categories_series: pd.Series) -> dict:
    counts = {label: 0 for label in CATEGORY_LABELS}
    for labels in categories_series:
        for label in labels:
            counts[label] += 1
    total = len(categories_series)
    return {
        label: {"count": count, "pct": round(100 * count / total, 2) if total else 0.0}
        for label, count in counts.items()
    }


def main():
    rng = np.random.default_rng(RANDOM_STATE)

    df = load_sample(SAMPLE_SIZE)
    logger.info("Loaded %d unique, non-empty Enron emails", len(df))

    df["received_at_parsed"] = df["received_at_raw"].apply(_parse_date)
    df = score_categories(df)
    df, thresholds = assign_labels(df, rng)
    logger.info("Per-category adaptive thresholds: %s", thresholds)

    avg_labels_raw = df["categories_raw"].apply(len).mean()
    avg_labels_noisy = df["categories"].apply(len).mean()
    logger.info("Avg labels/email — raw: %.3f, post-noise: %.3f", avg_labels_raw, avg_labels_noisy)

    # Fraction of (row, category) bits that differ between raw and noisy —
    # the multi-label equivalent of priority's scalar "noise flip rate".
    raw_sets = df["categories_raw"].apply(set)
    noisy_sets = df["categories"].apply(set)
    bit_diffs = sum(len(r.symmetric_difference(n)) for r, n in zip(raw_sets, noisy_sets, strict=True))
    total_bits = len(df) * len(NON_GENERAL_LABELS)
    measured_flip_rate = bit_diffs / total_bits

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
        "recipient_to_raw",
        "categories",
        "categories_raw",
    ]

    for name, split_df in [("train", train_df), ("val", val_df), ("test", test_df)]:
        split_df[output_columns].to_parquet(OUTPUT_DIR / f"{name}.parquet", index=False)

    metadata = {
        "dataset": "category_synthetic_v1",
        "SYNTHETIC": True,
        "PRD_COMPLIANT": False,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": RAW_ENRON_CSV,
        "sample_size_requested": SAMPLE_SIZE,
        "final_row_count": len(df),
        "unique_senders": unique_senders,
        "taxonomy": list(CATEGORY_LABELS),
        "per_category_thresholds": thresholds,
        "label_distribution": _label_distribution(df["categories"]),
        "avg_labels_per_email_raw": round(float(avg_labels_raw), 4),
        "avg_labels_per_email_post_noise": round(float(avg_labels_noisy), 4),
        "measured_bit_flip_rate": round(float(measured_flip_rate), 4),
        "split_sizes": {"train": len(train_df), "val": len(val_df), "test": len(test_df)},
        "split_method": "GroupShuffleSplit on sender_email (leakage-safe, not random row split)",
        "warning": (
            "Labels are heuristic/synthetic, not human-annotated. See "
            "docs/data_audit_categorization.md for the full rationale and the "
            "conditions under which this dataset must be replaced. See also "
            "docs/annotation_guidelines_categorization.md for the annotation "
            "process specification this dataset is a placeholder for."
        ),
    }
    (OUTPUT_DIR / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("\n================ SYNTHETIC CATEGORY DATASET (NOT PRD-COMPLIANT) ================\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
