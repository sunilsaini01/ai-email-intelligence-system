"""
Per-agent execution record within one workflow (Module 13 / Phase 12,
FR-63/FR-66/FR-67).

One row per (workflow_id, agent_name) -- NOT one row per Kafka message or
per retry attempt. Reasoning: FR-66's retries happen INSIDE one agent
handler invocation (see app/agents/base.py -- the handler retries the
underlying service call itself, in-process, rather than re-publishing to
Kafka per attempt), so "how many retries occurred" is a counter on this
one row (`attempt_count`), not a series of rows to aggregate. This also
makes the idempotency check (app/agents/base.py) a single indexed lookup:
"does a COMPLETED row already exist for (workflow_id, agent_name)?"
instead of a scan.

`event_id` is still stored (the requested-event's id that triggered this
row) so a duplicate-delivery of the SAME Kafka message is distinguishable
from a legitimate re-publish of a new attempt for the same agent -- see
docs/error_analysis... no, this is Phase 12's own first duplicate-handling
case, not inherited from Phase 11's Review Queue guard, though it follows
the identical check-then-insert shape.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID

STATUS_PENDING = "PENDING"
STATUS_RUNNING = "RUNNING"
STATUS_RETRYING = "RETRYING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"

AGENT_EXECUTION_STATUSES = (STATUS_PENDING, STATUS_RUNNING, STATUS_RETRYING, STATUS_COMPLETED, STATUS_FAILED)


class AgentExecution(Base):
    __tablename__ = "agent_executions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "agent_name", name="uq_agent_executions_workflow_agent"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    workflow_id: Mapped[uuid.UUID] = mapped_column(GUID())  # references workflow_executions.id
    agent_name: Mapped[str] = mapped_column(String(30))  # e.g. "spam" -- see messaging/topics.py AGENT_MODULES
    event_id: Mapped[uuid.UUID] = mapped_column(GUID())  # the triggering *.requested event's id

    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Never raw email content -- see app/core/logging.py's own module
    # docstring PII discipline, applied identically here.
    error_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "transient" | "permanent"
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
