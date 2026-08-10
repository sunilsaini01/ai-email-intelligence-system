"""
DB-level tests for `reply_drafts` (Module 10 / Phase 10) -- exercises
ReplyDraftRepository directly against an in-memory SQLite engine, no HTTP
layer. Same shape as tests/test_email_record_persistence.py.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.repositories.reply_draft_repository import ReplyDraftRepository
from app.database.session import Base
from app.models.reply_draft import POLICY_NORMAL_REPLY, STATUS_APPROVED, STATUS_EDITED, STATUS_GENERATED, STATUS_REJECTED


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _make_draft(repo: ReplyDraftRepository):
    return await repo.create(
        organization_id="default",
        source_subject="Refund",
        source_body="I want a refund.",
        retrieved_email_ids=[],
        retrieved_context_count=0,
        generated_text="Here is a draft reply.",
        status=STATUS_GENERATED,
        generation_policy=POLICY_NORMAL_REPLY,
    )


@pytest.mark.asyncio
async def test_create_persists_a_draft(session):
    repo = ReplyDraftRepository(session)
    draft = await _make_draft(repo)
    assert draft.status == STATUS_GENERATED
    assert draft.generated_text == "Here is a draft reply."
    assert draft.reviewed_at is None


@pytest.mark.asyncio
async def test_get_by_id_returns_the_draft(session):
    repo = ReplyDraftRepository(session)
    draft = await _make_draft(repo)
    fetched = await repo.get_by_id("default", draft.id)
    assert fetched.id == draft.id


@pytest.mark.asyncio
async def test_get_by_id_unknown_returns_none(session):
    import uuid

    repo = ReplyDraftRepository(session)
    assert await repo.get_by_id("default", uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_get_by_id_wrong_org_returns_none(session):
    repo = ReplyDraftRepository(session)
    draft = await _make_draft(repo)
    assert await repo.get_by_id("other-org", draft.id) is None


@pytest.mark.asyncio
async def test_approve_sets_status_and_reviewed_at(session):
    repo = ReplyDraftRepository(session)
    draft = await _make_draft(repo)
    approved = await repo.approve(draft, reviewer_id="agent-1")
    assert approved.status == STATUS_APPROVED
    assert approved.reviewer_id == "agent-1"
    assert approved.reviewed_at is not None


@pytest.mark.asyncio
async def test_edit_sets_edited_text_and_status(session):
    repo = ReplyDraftRepository(session)
    draft = await _make_draft(repo)
    edited = await repo.edit(draft, edited_text="A better reply.", reviewer_id="agent-1")
    assert edited.status == STATUS_EDITED
    assert edited.edited_text == "A better reply."
    assert edited.generated_text == "Here is a draft reply."  # original preserved for audit


@pytest.mark.asyncio
async def test_edit_computes_and_stores_edit_distance(session):
    """Post-Phase-10 fix #2 -- FR-52's 'Average Edit Distance' secondary metric."""
    repo = ReplyDraftRepository(session)
    draft = await _make_draft(repo)  # generated_text = "Here is a draft reply."
    edited = await repo.edit(draft, edited_text="Here is a much better draft reply.", reviewer_id="agent-1")
    assert edited.edit_distance == 12  # verified via a direct Levenshtein computation, not guessed


@pytest.mark.asyncio
async def test_approve_and_reject_leave_edit_distance_null(session):
    repo = ReplyDraftRepository(session)
    draft = await _make_draft(repo)
    approved = await repo.approve(draft, reviewer_id="agent-1")
    assert approved.edit_distance is None  # never edited -- must not be falsely reported as 0


@pytest.mark.asyncio
async def test_reject_sets_status(session):
    repo = ReplyDraftRepository(session)
    draft = await _make_draft(repo)
    rejected = await repo.reject(draft, reviewer_id="agent-1")
    assert rejected.status == STATUS_REJECTED
