"""
Phase 7B — Intent Detection: SYNTHETIC BOOTSTRAP dataset generator.

============================================================================
THIS DATASET IS NOT PRD-COMPLIANT. DO NOT TREAT ITS LABELS AS GROUND TRUTH.
See docs/data_audit_intent.md §4 for the full data strategy decision.
============================================================================

What this does: takes REAL Enron email text and assigns MULTI-LABEL intent
tags (Complaint / Inquiry / Request / Feedback / Escalation / Order / Cancel
/ Refund / Schedule) via a documented, deterministic keyword heuristic +
injected per-label noise -- NOT via human annotation. Mirrors
generate_synthetic_category_dataset.py's mechanics almost exactly (per-class
adaptive thresholds, per-bit noise), with one deliberate difference: category
always falls back to ["General"] when nothing scores; intent has no PRD-named
default class (see app/feature_engineering/intent_keywords.py's module
docstring), so a row may legitimately end up with ZERO intent labels here.

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/generate_synthetic_intent_dataset.py

Produces:
    data/processed/intent_synthetic_v1/{train,val,test}.parquet
    data/processed/intent_synthetic_v1/run_metadata.json
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

from app.feature_engineering.intent_keywords import INTENT_KEYWORDS, INTENT_LABELS
from app.training.logger import get_logger

logger = get_logger()

RAW_ENRON_CSV = "data/raw/enron/emails.csv"
OUTPUT_DIR = Path("data/processed/intent_synthetic_v1")
SAMPLE_SIZE = 10_000
RANDOM_STATE = 42
NOISE_FLIP_RATE = 0.04  # same per-bit rate as category's generator


def load_sample(n: int) -> pd.DataFrame:
    import email as email_lib

    from app.data_ingestion.enron_loader import _extract_body_text

    logger.info("Loading %d Enron emails from %s", n, RAW_ENRON_CSV)
    raw = pd.read_csv(RAW_ENRON_CSV, encoding="latin-1", nrows=n * 4)
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
                    "recipient_to_raw": msg.get("To", "") or "",
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


def _keyword_score(text: str, keywords: frozenset) -> int:
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw in text_lower)


def score_intents(df: pd.DataFrame) -> pd.DataFrame:
    combined = (df["subject_raw"].fillna("") + " " + df["body_text_raw"].fillna("")).str.lower()
    for label in INTENT_LABELS:
        keywords = INTENT_KEYWORDS[label]
        df[f"score_{label}"] = combined.apply(lambda text, kw=keywords: _keyword_score(text, kw))
    return df


def assign_labels(df: pd.DataFrame, rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    """
    Per-class adaptive threshold, identical mechanism to
    generate_synthetic_category_dataset.py's assign_labels() -- see that
    file's docstring for why a single fixed cutoff is inappropriate. Unlike
    category, NO fallback label is applied when a row scores zero on every
    class -- an empty label list is a legitimate, expected outcome here
    (see module docstring).
    """
    thresholds = {}
    raw_flags = {}

    for label in INTENT_LABELS:
        scores = df[f"score_{label}"]
        nonzero = scores[scores > 0]
        if len(nonzero) >= 5:
            threshold = max(1, int(np.ceil(nonzero.quantile(0.70))))
        else:
            threshold = 1
        thresholds[label] = threshold
        raw_flags[label] = (scores >= threshold).to_numpy()

    raw_flags_matrix = np.column_stack([raw_flags[label] for label in INTENT_LABELS])
    df["intents_raw"] = [
        [label for label, flag in zip(INTENT_LABELS, row, strict=True) if flag]
        for row in raw_flags_matrix
    ]

    noisy_matrix = raw_flags_matrix.copy()
    flip_mask = rng.random(noisy_matrix.shape) < NOISE_FLIP_RATE
    noisy_matrix = np.where(flip_mask, ~noisy_matrix, noisy_matrix)

    df["intents"] = [
        [label for label, flag in zip(INTENT_LABELS, row, strict=True) if flag]
        for row in noisy_matrix
    ]

    return df, thresholds


def leakage_safe_split(df: pd.DataFrame):
    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=RANDOM_STATE)
    train_idx, temp_idx = next(gss.split(df, groups=df["sender_email"]))
    train_df = df.iloc[train_idx].reset_index(drop=True)
    temp_df = df.iloc[temp_idx].reset_index(drop=True)

    gss2 = GroupShuffleSplit(n_splits=1, test_size=0.5, random_state=RANDOM_STATE)
    val_idx, test_idx = next(gss2.split(temp_df, groups=temp_df["sender_email"]))
    val_df = temp_df.iloc[val_idx].reset_index(drop=True)
    test_df = temp_df.iloc[test_idx].reset_index(drop=True)

    return train_df, val_df, test_df


def _label_distribution(intents_series: pd.Series) -> dict:
    counts = {label: 0 for label in INTENT_LABELS}
    zero_label_rows = 0
    for labels in intents_series:
        if not labels:
            zero_label_rows += 1
        for label in labels:
            counts[label] += 1
    total = len(intents_series)
    dist = {
        label: {"count": count, "pct": round(100 * count / total, 2) if total else 0.0}
        for label, count in counts.items()
    }
    dist["_zero_intents_rows"] = {
        "count": zero_label_rows,
        "pct": round(100 * zero_label_rows / total, 2) if total else 0.0,
    }
    return dist


def main():
    rng = np.random.default_rng(RANDOM_STATE)

    df = load_sample(SAMPLE_SIZE)
    logger.info("Loaded %d unique, non-empty Enron emails", len(df))

    df = score_intents(df)
    df, thresholds = assign_labels(df, rng)
    logger.info("Per-class adaptive thresholds: %s", thresholds)

    avg_labels_raw = df["intents_raw"].apply(len).mean()
    avg_labels_noisy = df["intents"].apply(len).mean()
    logger.info("Avg labels/email -- raw: %.3f, post-noise: %.3f", avg_labels_raw, avg_labels_noisy)

    raw_sets = df["intents_raw"].apply(set)
    noisy_sets = df["intents"].apply(set)
    bit_diffs = sum(len(r.symmetric_difference(n)) for r, n in zip(raw_sets, noisy_sets, strict=True))
    total_bits = len(df) * len(INTENT_LABELS)
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
        "intents",
        "intents_raw",
    ]

    for name, split_df in [("train", train_df), ("val", val_df), ("test", test_df)]:
        split_df[output_columns].to_parquet(OUTPUT_DIR / f"{name}.parquet", index=False)

    label_dist = _label_distribution(df["intents"])
    metadata = {
        "dataset": "intent_synthetic_v1",
        "SYNTHETIC": True,
        "PRD_COMPLIANT": False,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": RAW_ENRON_CSV,
        "sample_size_requested": SAMPLE_SIZE,
        "final_row_count": len(df),
        "unique_senders": unique_senders,
        "taxonomy": list(INTENT_LABELS),
        "per_class_thresholds": thresholds,
        "label_distribution": label_dist,
        "avg_labels_per_email_raw": round(float(avg_labels_raw), 4),
        "avg_labels_per_email_post_noise": round(float(avg_labels_noisy), 4),
        "measured_bit_flip_rate": round(float(measured_flip_rate), 4),
        "split_sizes": {"train": len(train_df), "val": len(val_df), "test": len(test_df)},
        "split_method": "GroupShuffleSplit on sender_email (leakage-safe, not random row split)",
        "warning": (
            "Labels are heuristic/synthetic, not human-annotated. See "
            "docs/data_audit_intent.md for the full rationale. Order/Refund/"
            "Cancel classes are expected to be rare or near-absent given "
            "Enron's B2B domain -- check label_distribution above before "
            "assuming any class has meaningful support in this dataset."
        ),
    }
    (OUTPUT_DIR / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("\n================ SYNTHETIC INTENT DATASET (NOT PRD-COMPLIANT) ================\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
