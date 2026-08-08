"""
Persistence for every category classification decision (Module 4).

Same rationale as app/models/priority_prediction_log.py: stands alone ahead
of the PRD's `email_classifications` table (needs Module 1's email ingestion
first), stores subject/body directly since there's no `emails` table to
reference yet. Differs from priority/spam's log tables in one structural way:
`predicted_categories`/`confidences` are JSON columns, not scalar strings —
a multi-label decision doesn't fit a single VARCHAR column. Generic
SQLAlchemy `JSON` (not `postgresql.JSONB`) is used deliberately for
portability: this table is exercised against SQLite in-memory in the test
suite (tests/test_category_prediction_log.py, mirroring
test_priority_prediction_log.py) as well as real Postgres, and JSONB has no
SQLite equivalent.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID


class CategoryPredictionLog(Base):
    __tablename__ = "category_prediction_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    subject: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text)

    predicted_categories: Mapped[list[str]] = mapped_column(JSON)  # e.g. ["Legal", "Billing"]
    confidences: Mapped[dict] = mapped_column(JSON)  # {"Legal": 0.75, "Billing": 1.0}
    # SYNTHETIC_DATA=True flags rows produced while category_baseline.joblib
    # was trained on data/processed/category_synthetic_v1 (see
    # docs/data_audit_categorization.md) — same disclosure mechanism as
    # PriorityPredictionLog.synthetic_model.
    synthetic_model: Mapped[bool] = mapped_column(Boolean, default=True)
    model_version: Mapped[str] = mapped_column(String(100))
    processing_ms: Mapped[float] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
