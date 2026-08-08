"""
Persistence for summarization requests (Module 5).

Deliberately DIFFERENT from spam/priority/category's audit-log pattern:
those three store subject+body directly (see spam_prediction_log.py's
docstring for why — no `emails` table exists yet to reference). This table
does NOT store the source body, per Step 16's explicit instruction ("Do
not store full email content unnecessarily. Avoid sensitive-content
duplication.") — a summarization log's entire job is to record what was
PRODUCED, not to be a second copy of what was submitted. The `summary`
field itself is stored (it's the actual output and the thing feedback
correction targets), along with size/performance metadata for
observability, but not the raw input.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID


class SummaryLog(Base):
    __tablename__ = "summary_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    summary: Mapped[str] = mapped_column(Text)
    summary_type: Mapped[str] = mapped_column(String(20))  # "extractive" | "abstractive"
    skipped_short_input: Mapped[bool] = mapped_column(default=False)
    input_word_count: Mapped[int] = mapped_column(Integer)
    entity_preservation_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_version: Mapped[str] = mapped_column(String(100))
    processing_ms: Mapped[float] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
