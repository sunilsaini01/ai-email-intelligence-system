"""
Persistence for every intent detection decision (Module 7 / Phase 7B).

Same JSON-column pattern as category_prediction_log.py for the multi-label
`predicted_intents`/`confidences` pair, plus a THIRD JSON column
(`entities`) this module has that category doesn't -- FR-35's extracted
entities (order IDs, dates, amounts, names) are part of what this endpoint
produces and are audit-logged alongside the intent decision itself, same
"log what was produced" principle as every other module's audit table.
Generic `JSON` (not `postgresql.JSONB`), same portability reason as
category's table -- exercised against SQLite in tests.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID


class IntentPredictionLog(Base):
    __tablename__ = "intent_prediction_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    # Phase 11 addition -- see spam_prediction_log.py's identical column
    # for the full rationale (model-level default, no endpoint change).
    organization_id: Mapped[str] = mapped_column(String(100), default=DEFAULT_ORGANIZATION_ID)

    subject: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text)

    predicted_intents: Mapped[list[str]] = mapped_column(JSON)  # e.g. ["Cancel", "Refund"], may be []
    confidences: Mapped[dict] = mapped_column(JSON)  # {"Cancel": 0.81, "Refund": 0.64}
    entities: Mapped[dict] = mapped_column(JSON)  # {"order_ids": [...], "dates": [...], ...}
    synthetic_model: Mapped[bool] = mapped_column(Boolean, default=True)
    model_version: Mapped[str] = mapped_column(String(100))
    processing_ms: Mapped[float] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
