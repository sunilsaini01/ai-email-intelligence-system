"""
Auto-generated analytics reports (FR-56: "auto-generate weekly email
analytics reports exportable as PDF and CSV").

The bytes live in Postgres, not on a local disk: the agents process
generates them and any API replica must be able to serve them, and a
weekly PDF/CSV pair is a few tens of KB.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID


class GeneratedReport(Base):
    __tablename__ = "generated_reports"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[str] = mapped_column(String(100), default=DEFAULT_ORGANIZATION_ID, index=True)

    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    report_format: Mapped[str] = mapped_column(String(10))  # csv | pdf
    content: Mapped[bytes] = mapped_column(LargeBinary)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
