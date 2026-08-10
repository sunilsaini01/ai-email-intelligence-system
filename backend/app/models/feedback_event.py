"""
Unified feedback/review event log (Module 11 / Phase 11, FR-58 to FR-62).

Why this table exists alongside the pre-existing JSONL feedback files
(app/services/feedback_service.py), not instead of them: every
`*/feedback` endpoint's JSONL write stays exactly as it was before this
phase (backward compatible with anything already depending on those
files) -- this table is an ADDITIONAL, queryable write from the same
endpoints, the same dual-write shape Phase 10's `_log_review_action`
already established (DB column + structured log, here DB row + JSONL).
FR-57/60/61/62 all need to aggregate feedback (correction rate over time,
by confidence bucket, threshold crossings) -- a write-only, unindexed
JSONL-per-module file cannot answer those queries without reading and
parsing every file on every dashboard request.

`action` exists specifically to make FR-62's correction-rate formula
computable at all: `corrections / reviewed_predictions` needs a
denominator, and nothing before this phase ever recorded "an agent
reviewed this and confirmed it was correct" -- only corrections were ever
logged. CONFIRM is the new action the Phase 11 Review Queue writes when
an agent inspects a low-confidence item and leaves it unchanged; without
it, the only available denominator would silently become "all
predictions ever made," which docs/architecture_dashboard.md's
Correction Rate section explicitly says not to do.

`prediction_id` is nullable and NOT a hard foreign key -- it references
whichever `*_prediction_logs.id` (or `reply_drafts.id` for auto_reply)
the feedback is about, but different modules' predictions live in
different tables, so a single-column FK is not expressible without a
polymorphic association this phase does not need. The `module` column is
what disambiguates which table `prediction_id` refers to, same
denormalized-reference precedent `reply_drafts.retrieved_email_ids`
already set for "cheap, rarely-joined reference" fields.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID

ACTION_CORRECTION = "CORRECTION"
ACTION_CONFIRM = "CONFIRM"
ACTION_ACCEPT = "ACCEPT"
ACTION_REJECT = "REJECT"
ACTION_RELEVANCE = "RELEVANCE"

FEEDBACK_ACTIONS = (ACTION_CORRECTION, ACTION_CONFIRM, ACTION_ACCEPT, ACTION_REJECT, ACTION_RELEVANCE)


class FeedbackEvent(Base):
    __tablename__ = "feedback_events"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    module: Mapped[str] = mapped_column(String(30))
    organization_id: Mapped[str] = mapped_column(String(100), default=DEFAULT_ORGANIZATION_ID)
    prediction_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    action: Mapped[str] = mapped_column(String(20))

    original_value: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)
    corrected_value: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)

    # The ORIGINAL prediction's confidence, carried onto the feedback row
    # at write time -- lets FR-62's confidence-bucket correction-rate
    # query group directly on this table, with no join back to whichever
    # source table `prediction_id` points into.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Caller-supplied, unauthenticated -- same trust model as
    # reply_drafts.reviewer_id since Phase 10, extended consistently here,
    # not a new or stronger identity claim. See docs/dashboard_security.md.
    reviewer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
