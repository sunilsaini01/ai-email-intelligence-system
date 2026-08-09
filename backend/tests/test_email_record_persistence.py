"""
DB-level tests for the canonical `emails` table (Module 9 / Phase 9) --
exercises EmailRepository directly against an in-memory SQLite engine, no
HTTP layer.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.repositories.email_repository import EmailRepository
from app.database.session import Base
from app.models.email_record import EmailRecord


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_creates_a_new_record(session):
    repo = EmailRepository(session)
    record, was_created = await repo.upsert_by_content_hash(
        organization_id="default",
        content_hash="abc123",
        subject="Refund",
        body="I want a refund.",
        sender_email="a@b.com",
        received_at=datetime.now(UTC),
        category="Billing",
        department="Billing",
    )
    assert was_created is True
    assert record.content_hash == "abc123"
    assert record.index_status == "PENDING"
    assert record.resolution_status == "OPEN"
    assert record.is_deleted is False


@pytest.mark.asyncio
async def test_upsert_same_content_hash_updates_not_duplicates(session):
    repo = EmailRepository(session)
    record1, created1 = await repo.upsert_by_content_hash(
        "default", "abc123", "Refund", "I want a refund.", "a@b.com", datetime.now(UTC), "Billing", "Billing"
    )
    record2, created2 = await repo.upsert_by_content_hash(
        "default", "abc123", "Refund (updated)", "I want a refund, updated.", "a@b.com", datetime.now(UTC), "Support", "Support"
    )

    assert created1 is True
    assert created2 is False
    assert record1.id == record2.id
    assert record2.subject == "Refund (updated)"
    assert record2.category == "Support"

    result = await session.execute(select(EmailRecord))
    assert len(result.scalars().all()) == 1  # exactly one row, not two


@pytest.mark.asyncio
async def test_same_content_hash_in_different_organizations_are_separate_records(session):
    repo = EmailRepository(session)
    record_a, _ = await repo.upsert_by_content_hash(
        "org-a", "abc123", "Refund", "body", "a@b.com", datetime.now(UTC), None, None
    )
    record_b, _ = await repo.upsert_by_content_hash(
        "org-b", "abc123", "Refund", "body", "a@b.com", datetime.now(UTC), None, None
    )
    assert record_a.id != record_b.id

    result = await session.execute(select(EmailRecord))
    assert len(result.scalars().all()) == 2


@pytest.mark.asyncio
async def test_mark_indexed_updates_status_and_embedding_fields(session):
    repo = EmailRepository(session)
    record, _ = await repo.upsert_by_content_hash(
        "default", "abc123", "Refund", "body", "a@b.com", datetime.now(UTC), None, None
    )
    updated = await repo.mark_indexed(record, "tfidf-v1", "email_embeddings_v1", "email_embeddings_v1")
    assert updated.index_status == "INDEXED"
    assert updated.embedding_model == "tfidf-v1"


@pytest.mark.asyncio
async def test_update_resolution_status(session):
    repo = EmailRepository(session)
    record, _ = await repo.upsert_by_content_hash(
        "default", "abc123", "Refund", "body", "a@b.com", datetime.now(UTC), None, None
    )
    updated = await repo.update_resolution_status("default", record.id, "RESOLVED")
    assert updated.resolution_status == "RESOLVED"


@pytest.mark.asyncio
async def test_update_resolution_status_returns_none_for_unknown_id(session):
    import uuid

    repo = EmailRepository(session)
    result = await repo.update_resolution_status("default", uuid.uuid4(), "RESOLVED")
    assert result is None


@pytest.mark.asyncio
async def test_soft_delete_excludes_from_get_by_id(session):
    repo = EmailRepository(session)
    record, _ = await repo.upsert_by_content_hash(
        "default", "abc123", "Refund", "body", "a@b.com", datetime.now(UTC), None, None
    )
    await repo.soft_delete("default", record.id)

    assert await repo.get_by_id("default", record.id) is None  # filtered out by is_deleted
