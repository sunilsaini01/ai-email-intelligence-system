"""
Persistence for every sentiment analysis decision (Module 6 / Phase 7A).

Same rationale as priority_prediction_log.py: stands alone ahead of the
PRD's `email_classifications` table (needs Module 1's email ingestion
first), stores subject/body directly because there's no `emails` table to
reference yet.

`synthetic_model` is always True here for a different reason than
priority/category's column of the same name: it's not flagging "trained on
synthetic labels" (VaderSentimentPredictor isn't trained on anything), it's
flagging "not validated against real human-labelled email sentiment" --
see docs/data_audit_sentiment.md. Named identically to the other three
modules' column for the same downstream-query reason (a future analytics
migration can filter `WHERE synthetic_model = true` across all four
prediction-log tables uniformly), not because the underlying reason is
identical.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID


class SentimentPredictionLog(Base):
    __tablename__ = "sentiment_prediction_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    # Phase 11 addition -- see spam_prediction_log.py's identical column
    # for the full rationale (model-level default, no endpoint change).
    organization_id: Mapped[str] = mapped_column(String(100), default=DEFAULT_ORGANIZATION_ID)

    subject: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text)

    predicted_sentiment: Mapped[str] = mapped_column(String(20))  # one of FR-29's 5 classes
    confidence: Mapped[float] = mapped_column(Float)
    synthetic_model: Mapped[bool] = mapped_column(Boolean, default=True)
    model_version: Mapped[str] = mapped_column(String(100))
    processing_ms: Mapped[float] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
