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
    """
    `module` defaults to "spam" so every existing caller (which never passed
    it) is unaffected — see get_feedback_logger() below. Each module gets its
    own JSONL file (`{module}_feedback.jsonl`) rather than one shared file,
    so a corruption or growth issue in one module's feedback log can't affect
    another's, and each stays a simple, independently-inspectable append log.
    """

    def __init__(self, artifact_dir: str = _DEFAULT_ARTIFACT_DIR, module: str = "spam"):
        self.module = module
        self.path = Path(artifact_dir) / f"{module}_feedback.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log_correction(
        self,
        subject: str,
        body: str,
        predicted_label: str | list[str],
        corrected_label: str | list[str],
        comment: str | None = None,
    ) -> str:
        """
        `predicted_label`/`corrected_label` accept either a scalar string
        (spam/priority's single-label corrections) or a list of strings
        (category's multi-label corrections, FR-22) — additive widening,
        not a behavior change for existing callers: json.dumps handles
        both shapes identically, and every existing call site already
        passes a plain string.
        """
        feedback_id = str(uuid.uuid4())

        record = {
            "feedback_id": feedback_id,
            "module": self.module,
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

    def log_summary_feedback(
        self,
        original_text: str,
        generated_summary: str,
        accepted: bool,
        corrected_summary: str | None = None,
        quality_score: int | None = None,
        reason: str | None = None,
    ) -> str:
        """
        Summarization's feedback shape (accept/reject + optional correction
        + a 1-5 quality score) doesn't fit log_correction's predicted/
        corrected-label shape (built for swapping one discrete label for
        another, not a generation task with a graded quality judgment) — a
        parallel method, not a forced fit, writing to the same per-module
        JSONL file.

        Per this phase's Step 17: this ONLY records feedback — nothing in
        this codebase auto-retrains from a feedback file. Promoting
        corrected summaries into a future training set would be a
        separate, explicit, validated step, same stance already implicit
        for every other module's feedback path.
        """
        feedback_id = str(uuid.uuid4())

        record = {
            "feedback_id": feedback_id,
            "module": self.module,
            "original_text": original_text,
            "generated_summary": generated_summary,
            "accepted": accepted,
            "corrected_summary": corrected_summary,
            "quality_score": quality_score,
            "reason": reason,
            "created_at": datetime.now(UTC).isoformat(),
        }

        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        return feedback_id

    def log_routing_feedback(
        self,
        subject: str,
        body: str,
        predicted_department: str | None,
        corrected_department: str | None,
        predicted_action: str,
        corrected_action: str | None = None,
        comment: str | None = None,
    ) -> str:
        """
        Routing's feedback shape (department + action pair, not a single
        predicted/corrected label) doesn't fit log_correction's shape any
        more cleanly than summarization's did -- a parallel method, same as
        log_summary_feedback, writing to the same per-module JSONL file.

        Per Phase 8's brief SS24/RULE (FR-41's "adjust rule weights" is
        deliberately NOT implemented): this only records feedback. Nothing
        in this codebase auto-adjusts routing_rules.py's thresholds or
        rule set from a feedback file -- promoting corrected routing
        decisions into a rule change would be a separate, explicit, human-
        reviewed step, same stance every other module's feedback path
        already takes.
        """
        feedback_id = str(uuid.uuid4())

        record = {
            "feedback_id": feedback_id,
            "module": self.module,
            "subject": subject,
            "body": body,
            "predicted_department": predicted_department,
            "corrected_department": corrected_department,
            "predicted_action": predicted_action,
            "corrected_action": corrected_action,
            "comment": comment,
            "created_at": datetime.now(UTC).isoformat(),
        }

        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        return feedback_id

    def log_retrieval_feedback(
        self,
        query_subject: str,
        query_body: str,
        result_email_id: str | None,
        useful: bool,
        comment: str | None = None,
    ) -> str:
        """
        Retrieval's feedback shape (a query + which result + a relevance
        judgment) doesn't fit log_correction's predicted/corrected-label
        shape any more than routing's or summarization's did -- a parallel
        method, same as those two, writing to the same per-module JSONL
        file.

        Step 31/RULE (Phase 9 brief): this ONLY records feedback. Nothing
        in this codebase auto-retrains embeddings or adjusts vector-store
        weights from a feedback file -- promoting relevance judgments into
        actual training data (e.g. a future fine-tuned retriever) would be
        a separate, explicit, human-reviewed step, same stance every other
        module's feedback path already takes.
        """
        feedback_id = str(uuid.uuid4())

        record = {
            "feedback_id": feedback_id,
            "module": self.module,
            "query_subject": query_subject,
            "query_body": query_body,
            "result_email_id": result_email_id,
            "useful": useful,
            "comment": comment,
            "created_at": datetime.now(UTC).isoformat(),
        }

        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        return feedback_id


def get_feedback_logger() -> FeedbackLogger:
    return FeedbackLogger()


def get_priority_feedback_logger() -> FeedbackLogger:
    return FeedbackLogger(module="priority")


def get_category_feedback_logger() -> FeedbackLogger:
    return FeedbackLogger(module="category")


def get_summarization_feedback_logger() -> FeedbackLogger:
    return FeedbackLogger(module="summarization")


def get_sentiment_feedback_logger() -> FeedbackLogger:
    return FeedbackLogger(module="sentiment")


def get_intent_feedback_logger() -> FeedbackLogger:
    return FeedbackLogger(module="intent")


def get_routing_feedback_logger() -> FeedbackLogger:
    return FeedbackLogger(module="routing")


def get_retrieval_feedback_logger() -> FeedbackLogger:
    return FeedbackLogger(module="retrieval")
