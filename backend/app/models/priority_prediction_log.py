"""
Persistence for every priority classification decision (Module 3).

Same rationale as app/models/spam_prediction_log.py: stands alone ahead of
the PRD's `email_classifications` table (which needs Module 1's email
ingestion to exist first), and stores subject/body directly because there's
no `emails` table to reference yet. See that file's docstring for the exact
migration path once ingestion lands — this table follows the identical plan.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID


class PriorityPredictionLog(Base):
    __tablename__ = "priority_prediction_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    subject: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text)

    predicted_priority: Mapped[str] = mapped_column(String(20))  # Critical | High | Medium | Low
    confidence: Mapped[float] = mapped_column(Float)
    # SYNTHETIC_DATA=True flags rows produced while priority_baseline.joblib
    # was trained on data/processed/priority_synthetic_v1 (see
    # docs/data_audit_priority.md) — lets a future migration or analytics
    # query cleanly exclude pre-annotation-era predictions rather than
    # silently mixing them with predictions from a real, annotated model.
    synthetic_model: Mapped[bool] = mapped_column(Boolean, default=True)
    model_version: Mapped[str] = mapped_column(String(100))
    processing_ms: Mapped[float] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
