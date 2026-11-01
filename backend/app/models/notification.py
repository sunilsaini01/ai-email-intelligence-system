"""
In-app notifications (FR-18: "Critical emails shall trigger immediate
notifications (in-app + configurable webhook)"; PRD Epic 2's SLA-at-risk
alerts).

Written by whichever process detects the condition (the agents process for
Critical emails and SLA sweeps, the API for anything synchronous) and read
by the API -- the table, not an in-process broadcaster, is what crosses
the process boundary. `webhook_status` records the outbound webhook
attempt on the same row so a failed delivery is visible, not just logged.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID

KIND_CRITICAL_EMAIL = "critical_email"
KIND_SLA_AT_RISK = "sla_at_risk"
KIND_SLA_BREACHED = "sla_breached"
KIND_MODEL_DRIFT = "model_drift"
KIND_RETRAINING = "retraining"

WEBHOOK_NOT_CONFIGURED = "not_configured"
WEBHOOK_DELIVERED = "delivered"
WEBHOOK_FAILED = "failed"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[str] = mapped_column(String(100), default=DEFAULT_ORGANIZATION_ID, index=True)

    kind: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(20), default="critical")  # critical | warning | info
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(Text, default="")

    email_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Dedup key -- e.g. f"sla_at_risk:{email_id}" -- so a periodic sweep
    # never notifies twice about the same condition.
    dedup_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    webhook_status: Mapped[str] = mapped_column(String(20), default=WEBHOOK_NOT_CONFIGURED)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
