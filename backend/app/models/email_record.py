"""
Canonical email entity (Module 9 / Phase 9, Step 2/Step 3).

The first shared identity across modules in this codebase -- every prior
module (Spam through Routing) logs to its OWN independent audit table with
its own fresh UUID per request; nothing links "this category-log row" and
"this routing-log row" as being about the same email. FR-46's filtering
requirement (category/department/resolution_status) structurally needs
that link, which is why this table exists: NOT a general-purpose "email
ingestion" system (no Message-ID parsing, no thread reconstruction, no
attachment storage -- those remain out of scope), just the minimum
canonical record Phase 9's own retrieval needs.

`category`/`department` are SNAPSHOTS supplied by the caller at index
time (from whatever CategoryService/RoutingService call already happened
upstream) -- this table does NOT call those services itself. Avoids
Phase 9 becoming a second orchestrator duplicating Phase 8's job; see
docs/architecture_rag.md "Why Category/Department Are Caller-Supplied".

Identity: `(organization_id, content_hash)` is UNIQUE -- the DB-level
enforcement of idempotent indexing (Step 3/RULE 10). Re-indexing the same
(subject, body) within one organization updates the existing row rather
than creating a duplicate; see app/retrieval/identity.py for how
content_hash is computed and app/database/repositories/email_repository.py
for the upsert logic built on this constraint.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID
from app.retrieval.resolution_status import DEFAULT_RESOLUTION_STATUS
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID

# Index lifecycle states (Step 19/29) -- Postgres and the vector store are
# separate systems; this column is the one place that tracks whether
# they're currently consistent for a given email.
INDEX_STATUS_PENDING = "PENDING"
INDEX_STATUS_INDEXED = "INDEXED"
INDEX_STATUS_FAILED = "FAILED"
INDEX_STATUS_STALE = "STALE"


class EmailRecord(Base):
    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("organization_id", "content_hash", name="uq_emails_org_content_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    organization_id: Mapped[str] = mapped_column(String(100), default=DEFAULT_ORGANIZATION_ID)
    content_hash: Mapped[str] = mapped_column(String(64))  # sha256 hex, see identity.py

    # Kept for a future real-ingestion path -- not used for identity today
    # (see app/retrieval/identity.py's module docstring for why).
    message_id: Mapped[str | None] = mapped_column(String(512), nullable=True)

    subject: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text)  # RAW, unanonymized -- see docs/phase9_pii_embedding_strategy.md
    sender_email: Mapped[str] = mapped_column(String(320), default="")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # Caller-supplied snapshots, nullable -- an email indexed before
    # Category/Routing ran (or without them at all) has no category/
    # department yet, which is a legitimate, filterable ("unknown") state,
    # not an error.
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)

    resolution_status: Mapped[str] = mapped_column(String(20), default=DEFAULT_RESOLUTION_STATUS)

    index_status: Mapped[str] = mapped_column(String(20), default=INDEX_STATUS_PENDING)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vector_collection: Mapped[str | None] = mapped_column(String(100), nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)  # soft delete, Step 20

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
