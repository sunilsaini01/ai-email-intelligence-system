"""
Per-organization configuration (FR-18 webhook, FR-23 category taxonomy,
FR-41 learned routing thresholds, FR-42 assignment strategy, GDPR
retention, FR-56 scheduled reports).

One JSON document per organization rather than a column per setting:
these are small, independently-optional knobs edited together from one
admin screen, and none of them is ever queried across organizations. The
accepted keys and their defaults live in app/services/organization_settings_service.py
(DEFAULT_SETTINGS) -- that module, not this table, is the contract.
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class OrganizationSettings(Base):
    __tablename__ = "organization_settings"

    organization_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_by_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
