"""
Human feedback logging (FR-14 / FR-15 — minimal version).

Why JSONL instead of the `feedback` Postgres table from the PRD schema:
    That table needs Module 1's email-ingestion/persistence layer (an
    `emails` table with real IDs) to be meaningful, and neither exists yet
    in this codebase. This gives corrections a durable, append-only home
    now; migrating to the Postgres table is a storage-layer swap behind the
    same `log_correction` call once ingestion lands, not a redesign.
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Same reasoning as spam_service._DEFAULT_ARTIFACT_DIR: anchor to this file,
# not the process's cwd, so feedback always lands in one place regardless of
# how the app or the test suite was started.
_DEFAULT_ARTIFACT_DIR = str(Path(__file__).resolve().parents[3] / "artifacts")


class FeedbackLogger:
    def __init__(self, artifact_dir: str = _DEFAULT_ARTIFACT_DIR):
        self.path = Path(artifact_dir) / "spam_feedback.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log_correction(
        self,
        subject: str,
        body: str,
        predicted_label: str,
        corrected_label: str,
        comment: str | None = None,
    ) -> str:
        feedback_id = str(uuid.uuid4())

        record = {
            "feedback_id": feedback_id,
            "module": "spam",
            "subject": subject,
            "body": body,
            "predicted_label": predicted_label,
            "corrected_label": corrected_label,
            "comment": comment,
            "created_at": datetime.now(UTC).isoformat(),
        }

        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        return feedback_id


def get_feedback_logger() -> FeedbackLogger:
    return FeedbackLogger()
