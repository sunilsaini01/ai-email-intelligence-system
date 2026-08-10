"""
Repository for the canonical `emails` table (Module 9 / Phase 9).

`upsert_by_content_hash` is the idempotent-indexing mechanism (Step 3/
RULE 10): a portable select-then-insert-or-update, not a
Postgres-specific `ON CONFLICT` clause -- every other repository in this
codebase is dialect-agnostic (tested against SQLite), and this one stays
consistent with that rather than being the first to require Postgres-only
syntax. The `(organization_id, content_hash)` unique constraint on
`EmailRecord` is the actual guarantee; this method is just the
read-then-write path that respects it.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_record import INDEX_STATUS_PENDING, EmailRecord
from app.retrieval.resolution_status import RESOLVED


class EmailRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_by_content_hash(
        self,
        organization_id: str,
        content_hash: str,
        subject: str,
        body: str,
        sender_email: str,
        received_at: datetime,
        category: str | None,
        department: str | None,
        message_id: str | None = None,
        priority: str | None = None,
    ) -> tuple[EmailRecord, bool]:
        """Returns (record, was_created). Re-indexing the same content
        within one organization UPDATES the existing row (refreshed
        subject/body/category/department/received_at, index_status reset
        to PENDING so the caller knows to re-embed) rather than creating a
        second row -- see EmailRecord's module docstring."""
        existing = await self.session.execute(
            select(EmailRecord).where(
                EmailRecord.organization_id == organization_id,
                EmailRecord.content_hash == content_hash,
            )
        )
        record = existing.scalar_one_or_none()

        if record is None:
            record = EmailRecord(
                organization_id=organization_id,
                content_hash=content_hash,
                subject=subject,
                body=body,
                sender_email=sender_email,
                received_at=received_at,
                category=category,
                department=department,
                message_id=message_id,
                priority=priority,
                index_status=INDEX_STATUS_PENDING,
            )
            self.session.add(record)
            was_created = True
        else:
            record.subject = subject
            record.body = body
            record.sender_email = sender_email
            record.received_at = received_at
            record.category = category
            record.department = department
            record.message_id = message_id or record.message_id
            record.priority = priority
            record.index_status = INDEX_STATUS_PENDING
            was_created = False

        await self.session.commit()
        await self.session.refresh(record)
        return record, was_created

    async def mark_indexed(
        self, record: EmailRecord, embedding_model: str, embedding_version: str, vector_collection: str
    ) -> EmailRecord:
        record.index_status = "INDEXED"
        record.embedding_model = embedding_model
        record.embedding_version = embedding_version
        record.vector_collection = vector_collection
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def mark_failed(self, record: EmailRecord) -> EmailRecord:
        record.index_status = "FAILED"
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_by_content_hash(self, organization_id: str, content_hash: str) -> EmailRecord | None:
        result = await self.session.execute(
            select(EmailRecord).where(
                EmailRecord.organization_id == organization_id,
                EmailRecord.content_hash == content_hash,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, organization_id: str, email_id) -> EmailRecord | None:
        result = await self.session.execute(
            select(EmailRecord).where(
                EmailRecord.organization_id == organization_id,
                EmailRecord.id == email_id,
                EmailRecord.is_deleted == False,  # noqa: E712 -- SQLAlchemy requires `== False`, not `is False`
            )
        )
        return result.scalar_one_or_none()

    async def update_resolution_status(
        self, organization_id: str, email_id, resolution_status: str
    ) -> EmailRecord | None:
        record = await self.get_by_id(organization_id, email_id)
        if record is None:
            return None
        record.resolution_status = resolution_status
        # Phase 11: resolved_at is set exactly once, only on a transition
        # INTO RESOLVED -- deliberately not updated_at, which changes on
        # ANY field edit and would silently drift SLA "time to resolve"
        # every time something unrelated is re-indexed. Cleared back to
        # NULL if status moves off RESOLVED so a later re-resolution
        # recomputes it rather than keeping a stale prior timestamp.
        if resolution_status == RESOLVED:
            record.resolved_at = datetime.now(UTC)
        else:
            record.resolved_at = None
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def soft_delete(self, organization_id: str, email_id) -> EmailRecord | None:
        record = await self.get_by_id(organization_id, email_id)
        if record is None:
            return None
        record.is_deleted = True
        record.index_status = "STALE"
        await self.session.commit()
        await self.session.refresh(record)
        return record
