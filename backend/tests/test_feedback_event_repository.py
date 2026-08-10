"""
DB-level tests for `feedback_events` (Module 11 / Phase 11) -- exercises
FeedbackEventRepository directly against an in-memory SQLite engine, same
shape as tests/test_reply_draft_repository.py.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.repositories.feedback_event_repository import FeedbackEventRepository
from app.database.session import Base
from app.models.feedback_event import ACTION_CONFIRM, ACTION_CORRECTION


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
async def test_create_persists_a_feedback_event(session):
    repo = FeedbackEventRepository(session)
    event = await repo.create(
        module="spam",
        action=ACTION_CORRECTION,
        organization_id="default",
        original_value="ham",
        corrected_value="spam",
        confidence=0.4,
        reviewer_id="agent_1",
    )
    assert event.id is not None
    assert event.module == "spam"
    assert event.action == ACTION_CORRECTION


@pytest.mark.asyncio
async def test_count_corrections_since_none_counts_all_time(session):
    repo = FeedbackEventRepository(session)
    await repo.create(module="priority", action=ACTION_CORRECTION, organization_id="default")
    await repo.create(module="priority", action=ACTION_CORRECTION, organization_id="default")
    await repo.create(module="priority", action=ACTION_CONFIRM, organization_id="default")
    await repo.create(module="category", action=ACTION_CORRECTION, organization_id="default")

    count = await repo.count_corrections_since("priority", since=None)
    assert count == 2


@pytest.mark.asyncio
async def test_count_corrections_since_a_timestamp_excludes_earlier_rows(session):
    import asyncio
    from datetime import UTC, datetime

    repo = FeedbackEventRepository(session)
    await repo.create(module="priority", action=ACTION_CORRECTION, organization_id="default")
    cutoff = datetime.now(UTC)
    await asyncio.sleep(0.01)
    await repo.create(module="priority", action=ACTION_CORRECTION, organization_id="default")

    count = await repo.count_corrections_since("priority", since=cutoff)
    assert count == 1


@pytest.mark.asyncio
async def test_get_reviewed_prediction_ids_returns_only_this_modules_ids(session):
    repo = FeedbackEventRepository(session)
    pid_spam = uuid.uuid4()
    pid_priority = uuid.uuid4()
    await repo.create(module="spam", action=ACTION_CORRECTION, organization_id="default", prediction_id=pid_spam)
    await repo.create(module="priority", action=ACTION_CORRECTION, organization_id="default", prediction_id=pid_priority)
    # No prediction_id -- must not appear in results (excluded by IS NOT NULL).
    await repo.create(module="spam", action=ACTION_CORRECTION, organization_id="default")

    reviewed = await repo.get_reviewed_prediction_ids("spam", "default")
    assert reviewed == {pid_spam}


@pytest.mark.asyncio
async def test_get_reviewed_prediction_ids_is_organization_scoped(session):
    repo = FeedbackEventRepository(session)
    pid = uuid.uuid4()
    await repo.create(module="spam", action=ACTION_CORRECTION, organization_id="other_org", prediction_id=pid)

    reviewed = await repo.get_reviewed_prediction_ids("spam", "default")
    assert reviewed == set()
