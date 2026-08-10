"""
Persistence for generated auto-reply drafts (Module 10 / Phase 10,
FR-48 to FR-52).

One table, not four (Step 9's own "do not create unnecessary tables"):
`retrieved_email_ids` is a JSON array column, not a join table -- the
relationship is write-once at generation time, read-rarely, same
denormalized-JSON precedent Routing's `routing_decision_logs` already set
for "rules fired" rather than a separate rules-fired table. Feedback
(FR-52) reuses the existing `FeedbackLogger` JSONL pattern
(app/services/feedback_service.py:log_auto_reply_feedback), not a new
table -- consistent with every other module's feedback path.

Written even on generation failure (Step 8's audit-trail requirement) --
`status`/`generation_policy` distinguish a real draft from a recorded
failure; there is no separate "failure log" table.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID

# Draft lifecycle (Step 8).
STATUS_GENERATED = "GENERATED"
STATUS_EDITED = "EDITED"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
STATUS_FAILED = "FAILED"  # generation itself did not produce a draft -- see generation_policy

DRAFT_STATUSES = (STATUS_GENERATED, STATUS_EDITED, STATUS_APPROVED, STATUS_REJECTED, STATUS_FAILED)

# Generation policy (Step 7) -- recorded on every attempt, success or failure.
POLICY_NORMAL_REPLY = "NORMAL_REPLY"
POLICY_NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
POLICY_INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
POLICY_UNSAFE_CONTENT = "UNSAFE_CONTENT"
POLICY_LLM_FAILURE = "LLM_FAILURE"
POLICY_TIMEOUT = "TIMEOUT"
POLICY_NO_SIMILAR_EMAILS = "NO_SIMILAR_EMAILS"

GENERATION_POLICIES = (
    POLICY_NORMAL_REPLY,
    POLICY_NEEDS_HUMAN_REVIEW,
    POLICY_INSUFFICIENT_CONTEXT,
    POLICY_UNSAFE_CONTENT,
    POLICY_LLM_FAILURE,
    POLICY_TIMEOUT,
    POLICY_NO_SIMILAR_EMAILS,
)


class ReplyDraft(Base):
    __tablename__ = "reply_drafts"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    organization_id: Mapped[str] = mapped_column(String(100), default=DEFAULT_ORGANIZATION_ID)

    # Nullable: the source email is not required to already be a canonical
    # EmailRecord (Phase 9's indexing isn't auto-wired -- see
    # docs/architecture_rag.md "Not Auto-Wired"); subject/body are kept
    # directly so the draft is self-contained regardless.
    source_email_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    source_subject: Mapped[str] = mapped_column(Text, default="")
    source_body: Mapped[str] = mapped_column(Text)

    retrieved_email_ids: Mapped[list] = mapped_column(JSON, default=list)
    retrieved_context_count: Mapped[int] = mapped_column(Integer, default=0)

    generated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Levenshtein distance (app/nlp/edit_distance.py) between generated_text
    # and edited_text -- only set on an EDIT transition (Post-Phase-10 fix #2,
    # FR-52's "Average Edit Distance" secondary metric). NULL for a draft
    # that was approved/rejected without editing, not 0 -- 0 would falsely
    # claim "edited with zero changes."
    edit_distance: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default=STATUS_GENERATED)
    generation_policy: Mapped[str] = mapped_column(String(30))
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    llm_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    retrieval_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    reviewer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)  # no real auth yet -- caller-supplied

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
