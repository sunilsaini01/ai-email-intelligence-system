"""
Multi-agent workflow state (Module 13 / Phase 12, FR-63).

One row per `POST /api/v1/email/process` call. This is the durable system
of record the master prompt explicitly requires ("Do not rely exclusively
on Kafka messages as durable workflow state") -- Kafka topics are
transport with short retention (docs/kafka_architecture.md "Retention"),
this table is what `GET /api/v1/workflows/{job_id}` actually reads.

Status model, deliberately the smallest set that answers every question
the master prompt lists (which agents completed/failed/pending, current
status): PENDING (created, orchestrator hasn't started dispatching yet) ->
RUNNING (at least one agent task published) -> COMPLETED (every required
agent finished successfully) | FAILED (a required agent exhausted
retries) | PARTIAL (some optional agents failed but the workflow still
produced a usable result -- see docs/failure_handling.md).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID

STATUS_PENDING = "PENDING"
STATUS_RUNNING = "RUNNING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_PARTIAL = "PARTIAL"

WORKFLOW_STATUSES = (STATUS_PENDING, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED, STATUS_PARTIAL)


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)  # == job_id

    organization_id: Mapped[str] = mapped_column(String(100), default=DEFAULT_ORGANIZATION_ID)
    email_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)  # references emails.id once indexed

    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
