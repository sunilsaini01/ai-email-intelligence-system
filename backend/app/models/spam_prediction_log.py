"""
Persistence for every spam classification decision (Module 10).

Why this table exists at all, separate from a future full `emails` table:
    The PRD's `email_classifications` table (docs/PRD §12.1) assumes an
    `emails` table with real ingested messages already exists — it doesn't
    yet (Module 1 / email ingestion is a later phase). Auditability of
    predictions shouldn't wait on that: FR-40/FR-59 style requirements
    ("every decision logged with reasoning", "every correction logged with
    original value") apply the moment predictions start happening, not once
    ingestion ships. This table stands alone now and becomes the spam-specific
    slice of `email_classifications` once that table exists — same columns,
    just joined to a real email_id instead of standing on its own.

Why store subject/body here at all (vs. just an email_id foreign key):
    Because there's no emails table to reference yet. This is a deliberate,
    temporary trade-off, not an oversight — see docs/model_cards/spam_detection.md
    "Limitations" for the migration path once ingestion lands.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.database.session import Base


class GUID(TypeDecorator):
    """
    UUID that works on both Postgres (native UUID) and SQLite (stored as
    CHAR(36)) — needed so the same model can be tested against SQLite
    without a live Postgres instance, and still get a real UUID column in
    production.
    """

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)


class SpamPredictionLog(Base):
    __tablename__ = "spam_prediction_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    subject: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text)

    is_spam: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(20))  # "quarantined" | "clear"
    spam_score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    threshold_used: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(100))
    processing_ms: Mapped[float] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
