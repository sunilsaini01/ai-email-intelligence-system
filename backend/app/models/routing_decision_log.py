"""
Persistence for every routing decision (Module 8 / Phase 8, FR-40: "All
routing decisions shall be logged with the reasoning").

Same JSON-column, GUID-portability pattern every prior prediction-log model
uses (see intent_prediction_log.py) -- generic `JSON`, not
`postgresql.JSONB`, exercised against SQLite in tests.

`synthetic_model` keeps the same column name every other log table uses,
but its meaning here is necessarily broader than "this row came from a
not-yet-annotated model": routing has no model of its own. For routing it
means "at least one upstream signal this decision used is synthetic-labelled
or unvalidated" -- true for every decision today, since Category/Priority/
Intent are all synthetic-labelled and Sentiment is unvalidated (see
docs/ml_data_maturity_roadmap.md). Kept as a plain Boolean (always True
today) rather than a new differently-named column, so cross-module
"how much of what we've served is provisional" queries keep working
uniformly -- see docs/routing_signal_reliability.md for the per-signal
detail this single flag necessarily collapses.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID


class RoutingDecisionLog(Base):
    __tablename__ = "routing_decision_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    subject: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text)

    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[float] = mapped_column(Float)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text)
    matched_rules: Mapped[list[str]] = mapped_column(JSON)  # e.g. ["R-CATEGORY-AUTO-ROUTE"]
    supporting_signals: Mapped[dict] = mapped_column(JSON)
    model_versions: Mapped[dict] = mapped_column(JSON)
    routing_rules_version: Mapped[str] = mapped_column(String(50))
    keyword_matcher_version: Mapped[str] = mapped_column(String(50))
    upstream_failures: Mapped[list[str]] = mapped_column(JSON)  # e.g. [], or ["intent"]

    synthetic_model: Mapped[bool] = mapped_column(Boolean, default=True)
    processing_ms: Mapped[float] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
