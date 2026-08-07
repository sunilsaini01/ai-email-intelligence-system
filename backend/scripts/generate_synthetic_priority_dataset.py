"""
Phase 4 — Priority Classification: SYNTHETIC BOOTSTRAP dataset generator.

============================================================================
THIS DATASET IS NOT PRD-COMPLIANT. DO NOT TREAT ITS LABELS AS GROUND TRUTH.
See docs/data_audit_priority.md §4 for the full data strategy decision.
============================================================================

What this does: takes REAL Enron email text and REAL email headers (sender,
date, recipients — actual corporate correspondence), and assigns a
Critical/High/Medium/Low label via a documented, deterministic heuristic
(keyword lexicons + metadata rules + injected label noise) — NOT via human
annotation. This exists to let the training/serving pipeline be built and
proven mechanically end-to-end while the real annotation effort (3
annotators, Cohen's Kappa >= 0.70, PRD §8.2) is a separate, unstarted, and
out-of-scope-for-this-session line of work.

Why inject label noise (see `_apply_label_noise` below) rather than ship the
heuristic's raw output: a purely deterministic label is a direct function of
the same keyword counts the model trains on. Every classifier would then
score near-perfectly by re-deriving the generating rule, which would be a
meaningless number dressed up as a good one. Noise doesn't fix the deeper
leakage problem (the label is still keyword-derived) but it stops the
dataset from being a trivial lookup table, which makes error analysis (Phase
4 Step 11) actually show something.

Run from the repo root:
    PYTHONPATH=backend python backend/scripts/generate_synthetic_priority_dataset.py

Produces:
    data/processed/priority_synthetic_v1/{train,val,test}.parquet
    data/processed/priority_synthetic_v1/run_metadata.json
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

from app.data_ingestion.enron_loader import load_enron_kaggle
from app.feature_engineering.priority_keywords import (
    ESCALATION_KEYWORDS,
    SLA_KEYWORDS,
    URGENCY_KEYWORDS,
)
from app.training.logger import get_logger

logger = get_logger()

RAW_ENRON_CSV = "data/raw/enron/emails.csv"
OUTPUT_DIR = Path("data/processed/priority_synthetic_v1")
SAMPLE_SIZE = 10_000  # matches the PRD's minimum row-count target, NOT its data-quality bar
RANDOM_STATE = 42

LABELS = ["Low", "Medium", "High", "Critical"]

# Sender local-parts / subject patterns that mark an automated/system email —
# per the taxonomy's explicit rule (docs/data_audit_priority.md §3):
# "Automated/system-generated emails default to Low regardless of
# alarming-sounding subject lines." Encoding this as a hard override (not just
# another weighted signal) is deliberate — it's the one taxonomy rule that's
# supposed to *resist* the keyword heuristic, not agree with it.
AUTOMATED_SENDER_MARKERS = ("noreply", "no-reply", "mailer-daemon", "postmaster", "do-not-reply")
AUTOMATED_SUBJECT_MARKERS = ("daily report", "digest", "auto-reply", "automated", "cron")


def load_sample(n: int) -> pd.DataFrame:
    logger.info("Loading %d Enron emails from %s", n, RAW_ENRON_CSV)
    df = pd.read_csv(RAW_ENRON_CSV, encoding="latin-1", nrows=n * 3)  # over-fetch; some rows will be dropped
    records = list(load_enron_kaggle_from_df(df))
    result = pd.DataFrame(records)
    result = result[result["body_text_raw"].str.strip().str.len() > 0]
    result = result.drop_duplicates(subset=["body_text_raw"])
    return result.head(n).reset_index(drop=True)


def load_enron_kaggle_from_df(df: pd.DataFrame):
    """
    Thin wrapper around enron_loader's per-row parsing so we can cap how many
    raw rows get parsed (the full CSV is ~1.4GB / 500K rows — parsing all of
    it just to sample 10K is wasteful for a bootstrap dataset).
    """
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


def _is_automated(sender_email: str, subject: str) -> bool:
    sender_lower = sender_email.lower()
    subject_lower = subject.lower()
    return any(marker in sender_lower for marker in AUTOMATED_SENDER_MARKERS) or any(
        marker in subject_lower for marker in AUTOMATED_SUBJECT_MARKERS
    )


def heuristic_priority_score(row: pd.Series) -> float:
    """
    Weighted combination of keyword and metadata signals. Escalation language
    is weighted highest per the taxonomy rule that it raises priority
    independent of raw content severity (docs/data_audit_priority.md §3).
    """
    body = row["body_text_raw"]
    subject = row["subject_raw"]
    combined = f"{subject} {body}"

    urgency = _keyword_score(combined, URGENCY_KEYWORDS)
    escalation = _keyword_score(combined, ESCALATION_KEYWORDS)
    sla = _keyword_score(combined, SLA_KEYWORDS)

    exclamations = body.count("!")
    upper_words = sum(1 for w in body.split() if w.isupper() and len(w) > 2)

    dt = row["received_at_parsed"]
    is_after_hours = dt.hour < 8 or dt.hour >= 19
    is_weekend = dt.weekday() >= 5

    score = (
        urgency * 1.0
        + escalation * 2.5
        + sla * 1.5
        + min(exclamations, 5) * 0.3
        + min(upper_words, 5) * 0.2
        + (0.5 if is_after_hours else 0.0)
        + (0.3 if is_weekend else 0.0)
    )
    return score


def _apply_label_noise(labels: np.ndarray, rng: np.random.Generator, flip_rate: float = 0.08) -> np.ndarray:
    """
    Flip ~8% of labels by one adjacent level (never a 2-level jump — that
    would create implausible noise no real annotator confusion would produce).
    Documented, not hidden: this is what makes §4's "not a trivial lookup
    table" claim true, and it's exactly what Phase 4 Step 11's error analysis
    should be able to detect as a distinct error category from genuine
    content-driven ambiguity.
    """
    label_to_idx = {label: i for i, label in enumerate(LABELS)}
    idx_to_label = dict(enumerate(LABELS))

    noisy = labels.copy()
    flip_mask = rng.random(len(labels)) < flip_rate
    directions = rng.choice([-1, 1], size=len(labels))

    for i in np.where(flip_mask)[0]:
        current_idx = label_to_idx[labels[i]]
        new_idx = int(np.clip(current_idx + directions[i], 0, len(LABELS) - 1))
        noisy[i] = idx_to_label[new_idx]

    return noisy


def assign_labels(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    df["received_at_parsed"] = df["received_at_raw"].apply(_parse_date)
    df["heuristic_score"] = df.apply(heuristic_priority_score, axis=1)
    df["is_automated"] = df.apply(
        lambda r: _is_automated(r["sender_email"], r["subject_raw"]), axis=1
    )

    # Quantile thresholds chosen to approximate realistic business-email
    # imbalance (most email is Medium; Critical is rare) rather than an even
    # 25/25/25/25 split, which no real inbox looks like.
    q_low, q_high, q_critical = df["heuristic_score"].quantile([0.55, 0.90, 0.98])

    def bucket(score: float) -> str:
        if score <= q_low:
            return "Low"
        if score <= q_high:
            return "Medium"
        if score <= q_critical:
            return "High"
        return "Critical"

    df["priority_label_raw"] = df["heuristic_score"].apply(bucket)

    # Hard override per the taxonomy's automated-sender rule — applied AFTER
    # bucketing, deliberately fighting the keyword score for these rows.
    df.loc[df["is_automated"], "priority_label_raw"] = "Low"

    df["priority_label"] = _apply_label_noise(df["priority_label_raw"].to_numpy(), rng)

    return df


def leakage_safe_split(df: pd.DataFrame):
    """
    Group by sender_email — see docs/data_audit_priority.md §6 for why plain
    stratified/random splitting is inappropriate here.
    """
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
    rng = np.random.default_rng(RANDOM_STATE)

    df = load_sample(SAMPLE_SIZE)
    logger.info("Loaded %d unique, non-empty Enron emails", len(df))

    df = assign_labels(df, rng)
    logger.info("Label distribution (post-noise):\n%s", df["priority_label"].value_counts())

    noise_flip_rate = (df["priority_label"] != df["priority_label_raw"]).mean()
    logger.info("Actual noise flip rate: %.4f", noise_flip_rate)

    unique_senders = df["sender_email"].nunique()
    logger.info("Unique senders: %d (grouping unit for the split)", unique_senders)

    train_df, val_df, test_df = leakage_safe_split(df)
    logger.info(
        "Split sizes -> train: %d, val: %d, test: %d", len(train_df), len(val_df), len(test_df)
    )

    # Sanity check: no sender appears in more than one split.
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
        "priority_label",
        "priority_label_raw",
        "is_automated",
        "heuristic_score",
    ]

    for name, split_df in [("train", train_df), ("val", val_df), ("test", test_df)]:
        split_df[output_columns].to_parquet(OUTPUT_DIR / f"{name}.parquet", index=False)

    metadata = {
        "dataset": "priority_synthetic_v1",
        "SYNTHETIC": True,
        "PRD_COMPLIANT": False,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": RAW_ENRON_CSV,
        "sample_size_requested": SAMPLE_SIZE,
        "final_row_count": len(df),
        "unique_senders": unique_senders,
        "label_distribution": df["priority_label"].value_counts().to_dict(),
        "noise_flip_rate": round(float(noise_flip_rate), 4),
        "split_sizes": {"train": len(train_df), "val": len(val_df), "test": len(test_df)},
        "split_method": "GroupShuffleSplit on sender_email (leakage-safe, not random row split)",
        "warning": (
            "Labels are heuristic/synthetic, not human-annotated. See "
            "docs/data_audit_priority.md for the full rationale and the "
            "conditions under which this dataset must be replaced."
        ),
    }
    (OUTPUT_DIR / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("\n================ SYNTHETIC PRIORITY DATASET (NOT PRD-COMPLIANT) ================\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
