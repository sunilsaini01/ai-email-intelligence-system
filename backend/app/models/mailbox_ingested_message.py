"""
Dedup ledger for the mailbox poller (Phase 18).

Why this table exists: the poller (app/agents/runner.py's
`_poll_mailbox_connection`) can dispatch some messages in a page
successfully and then fail on a later one (a transient Kafka publish
failure, say). If the connection's `sync_cursor` were advanced
unconditionally, the failed message would be silently skipped forever
(the cursor already moved past it). If the cursor were instead left
UNCHANGED on any partial failure, the next poll re-fetches the same page
-- and without this table, would re-dispatch the messages that already
succeeded, creating duplicate `workflow_executions` rows for them. This
table is the guard: `(connection_id, provider_message_id)` is checked
before every dispatch, so a retried page only ever dispatches the
messages that are actually still pending. Same "make redelivery a no-op
via a unique constraint" idea as workflow_executions/agent_executions'
own `(workflow_id, agent_name)` constraint (Phase 12) applied to this
different redelivery source (a re-fetched provider page instead of a
redelivered Kafka message).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID


class MailboxIngestedMessage(Base):
    __tablename__ = "mailbox_ingested_messages"
    __table_args__ = (
        UniqueConstraint("connection_id", "provider_message_id", name="uq_mailbox_ingested_connection_message"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("mailbox_connections.id"))
    provider_message_id: Mapped[str] = mapped_column(String(255))
    workflow_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("workflow_executions.id"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
