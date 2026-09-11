"""
A connected Gmail/Outlook mailbox to poll for new mail (Phase 18,
FR-01/FR-02/FR-03).

One row per (organization, provider, mailbox) -- an organization may
connect more than one mailbox (e.g. both support@ and sales@), each
polled independently. `connected_by_user_id` is audit-only (who
authorized this connection), not an access-control boundary: any
authenticated user in the organization can see/manage every connection
belonging to it, same organization-scoping model every other table in
this codebase uses (users.role's admin/member distinction is not
enforced anywhere yet -- see README's Roadmap).

access_token/refresh_token are stored ENCRYPTED (app/core/
token_encryption.py), never in plaintext -- see that module's docstring
for why. access_token_encrypted is nullable because it is genuinely
short-lived (typically ~1h) and gets refreshed via refresh_token well
before most polls need it; refresh_token_encrypted is the one credential
this row cannot function without.

`sync_cursor` is deliberately an opaque string, not a structured column:
Gmail's cursor is a historyId (a plain string), Outlook's is a full
deltaLink (a URL) -- two different shapes from two different providers,
with no shared structure worth modeling. See app/ingestion/mailbox_provider.py
for how each provider interprets its own cursor.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID

PROVIDER_GMAIL = "gmail"
PROVIDER_OUTLOOK = "outlook"
MAILBOX_PROVIDERS = (PROVIDER_GMAIL, PROVIDER_OUTLOOK)

STATUS_ACTIVE = "active"  # noqa: S105 -- a connection lifecycle state, not a credential
STATUS_ERROR = "error"
STATUS_REVOKED = "revoked"
MAILBOX_CONNECTION_STATUSES = (STATUS_ACTIVE, STATUS_ERROR, STATUS_REVOKED)


class MailboxConnection(Base):
    __tablename__ = "mailbox_connections"
    __table_args__ = (
        # One connection per mailbox address per provider per org --
        # reconnecting the same mailbox updates the existing row (fresh
        # tokens) instead of creating a duplicate poller for it.
        UniqueConstraint("organization_id", "provider", "email_address", name="uq_mailbox_org_provider_address"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    organization_id: Mapped[str] = mapped_column(String(100), default=DEFAULT_ORGANIZATION_ID)
    connected_by_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"))

    provider: Mapped[str] = mapped_column(String(20))
    email_address: Mapped[str] = mapped_column(String(320))

    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text)

    sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default=STATUS_ACTIVE)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)  # soft delete, same convention as EmailRecord

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
