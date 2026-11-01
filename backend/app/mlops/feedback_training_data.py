"""
Turns logged human corrections into training rows (FR-15 "reported
mistakes shall be logged for retraining pipeline", FR-61).

Source: the per-module `artifacts/{module}_feedback.jsonl` files every
`*/feedback` endpoint already appends to (app/services/feedback_service.py)
-- they carry the subject/body a correction was about, which the
feedback_events table deliberately does not.

Opt-in: a training script only folds corrections into its TRAIN split
when INCLUDE_FEEDBACK_CORRECTIONS=1 (set by the retraining runner,
app/mlops/retraining_runner.py). Never into val/test -- evaluating a model
on the very corrections it was just trained on would inflate its metrics.
Corrections only ever add rows; they never relabel the original dataset.

Rows are deduplicated on (subject, body), latest correction wins, and a
correction whose label is not one the module's model can emit is dropped
rather than guessed at.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.feature_engineering.category_keywords import CATEGORY_LABELS
from app.feature_engineering.intent_keywords import INTENT_LABELS
from app.services.feedback_service import feedback_log_dir

INCLUDE_FEEDBACK_ENV = "INCLUDE_FEEDBACK_CORRECTIONS"


LABEL_COLUMNS = {
    "spam": "spam_label",
    "priority": "priority_label",
    "category": "categories",
    "intent": "intents",
}

_PRIORITY_LABELS = ("Critical", "High", "Medium", "Low")


def feedback_enabled() -> bool:
    return os.environ.get(INCLUDE_FEEDBACK_ENV, "").strip().lower() in ("1", "true", "yes")


def _normalize_label(module: str, label):
    if module == "spam":
        return label if label in ("spam", "ham") else None
    if module == "priority":
        return label if label in _PRIORITY_LABELS else None
    allowed = CATEGORY_LABELS if module == "category" else INTENT_LABELS
    if isinstance(label, str):
        label = [label]
    if not isinstance(label, list):
        return None
    cleaned = [lbl for lbl in label if lbl in allowed]
    # An empty intent set is a legitimate correction ("no intent"); an
    # empty category set is not (CategoryService always assigns one).
    if module == "category" and not cleaned:
        return None
    return cleaned


def load_feedback_corrections(module: str, artifact_dir: Path | str | None = None) -> list[dict]:
    path = Path(artifact_dir or feedback_log_dir()) / f"{module}_feedback.jsonl"
    if not path.exists():
        return []

    latest: dict[tuple[str, str], dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        body = (record.get("body") or "").strip()
        label = _normalize_label(module, record.get("corrected_label"))
        if not body or label is None:
            continue
        latest[(record.get("subject") or "", body)] = {
            "subject": record.get("subject") or "",
            "body": body,
            "label": label,
            "created_at": record.get("created_at"),
        }
    return list(latest.values())


def feedback_training_frame(module: str, artifact_dir: Path | str | None = None) -> pd.DataFrame:
    """Rows in the shared raw schema the train_*_model.py scripts read
    (message_id, sender_email, subject_raw, body_text_raw, received_at_raw,
    recipient_to_raw, <label column>). Metadata the correction does not
    carry is left neutral (no sender, no recipients) rather than invented."""
    label_column = LABEL_COLUMNS[module]
    rows = []
    for i, correction in enumerate(load_feedback_corrections(module, artifact_dir)):
        rows.append(
            {
                "message_id": f"feedback-{module}-{i}",
                "sender_email": "",
                "subject_raw": correction["subject"],
                "body_text_raw": correction["body"],
                "received_at_raw": correction["created_at"] or datetime.now(UTC).isoformat(),
                "recipient_to_raw": "",
                label_column: correction["label"],
            }
        )
    return pd.DataFrame(rows, columns=[*_RAW_COLUMNS, label_column])


_RAW_COLUMNS = ("message_id", "sender_email", "subject_raw", "body_text_raw", "received_at_raw", "recipient_to_raw")


def augment_training_frame(
    train_df: pd.DataFrame, module: str, artifact_dir: Path | str | None = None
) -> tuple[pd.DataFrame, int]:
    """Returns (train_df + corrections, number of correction rows added).
    A no-op unless INCLUDE_FEEDBACK_CORRECTIONS is set."""
    if not feedback_enabled():
        return train_df, 0
    extra = feedback_training_frame(module, artifact_dir)
    if extra.empty:
        return train_df, 0
    return pd.concat([train_df, extra], ignore_index=True), len(extra)
