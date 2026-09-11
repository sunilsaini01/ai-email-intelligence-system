"""DB-level tests for mailbox_connections (Phase 18)."""

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.repositories.mailbox_connection_repository import MailboxConnectionRepository
from app.database.session import Base
from app.models.mailbox_connection import STATUS_ACTIVE, STATUS_ERROR

USER_ID = uuid.uuid4()


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
async def test_upsert_creates_a_new_connection(session):
    repo = MailboxConnectionRepository(session)

    connection = await repo.upsert(
        organization_id="acme",
        connected_by_user_id=USER_ID,
        provider="gmail",
        email_address="support@acme.com",
        access_token_encrypted="enc-at",
        access_token_expires_at=datetime.now(UTC),
        refresh_token_encrypted="enc-rt",
    )

    assert connection.status == STATUS_ACTIVE
    assert connection.email_address == "support@acme.com"


@pytest.mark.asyncio
async def test_upsert_reconnecting_the_same_mailbox_updates_the_existing_row(session):
    repo = MailboxConnectionRepository(session)
    first = await repo.upsert(
        organization_id="acme",
        connected_by_user_id=USER_ID,
        provider="gmail",
        email_address="support@acme.com",
        access_token_encrypted="enc-at-1",
        access_token_expires_at=datetime.now(UTC),
        refresh_token_encrypted="enc-rt-1",
    )
    await repo.mark_error(first, "token expired")

    second = await repo.upsert(
        organization_id="acme",
        connected_by_user_id=USER_ID,
        provider="gmail",
        email_address="support@acme.com",
        access_token_encrypted="enc-at-2",
        access_token_expires_at=datetime.now(UTC),
        refresh_token_encrypted="enc-rt-2",
    )

    assert second.id == first.id
    assert second.refresh_token_encrypted == "enc-rt-2"
    assert second.status == STATUS_ACTIVE  # re-authorizing recovers from a prior error
    assert second.last_error is None

    all_connections = await repo.list_for_organization("acme")
    assert len(all_connections) == 1


@pytest.mark.asyncio
async def test_list_for_organization_is_scoped_and_excludes_soft_deleted(session):
    repo = MailboxConnectionRepository(session)
    org_a = await repo.upsert(
        organization_id="org-a",
        connected_by_user_id=USER_ID,
        provider="gmail",
        email_address="a@org-a.com",
        access_token_encrypted=None,
        access_token_expires_at=None,
        refresh_token_encrypted="rt",
    )
    await repo.upsert(
        organization_id="org-b",
        connected_by_user_id=USER_ID,
        provider="gmail",
        email_address="b@org-b.com",
        access_token_encrypted=None,
        access_token_expires_at=None,
        refresh_token_encrypted="rt",
    )

    assert [c.email_address for c in await repo.list_for_organization("org-a")] == ["a@org-a.com"]

    await repo.soft_delete(org_a)
    assert await repo.list_for_organization("org-a") == []


@pytest.mark.asyncio
async def test_list_all_active_excludes_errored_and_deleted_connections(session):
    repo = MailboxConnectionRepository(session)
    active = await repo.upsert(
        organization_id="org-a",
        connected_by_user_id=USER_ID,
        provider="gmail",
        email_address="active@org-a.com",
        access_token_encrypted=None,
        access_token_expires_at=None,
        refresh_token_encrypted="rt",
    )
    errored = await repo.upsert(
        organization_id="org-a",
        connected_by_user_id=USER_ID,
        provider="outlook",
        email_address="errored@org-a.com",
        access_token_encrypted=None,
        access_token_expires_at=None,
        refresh_token_encrypted="rt",
    )
    await repo.mark_error(errored, "boom")

    active_ids = {c.id for c in await repo.list_all_active()}
    assert active.id in active_ids
    assert errored.id not in active_ids
    assert await repo.count_errored() == 1


@pytest.mark.asyncio
async def test_update_tokens_keeps_existing_refresh_token_when_none_given(session):
    repo = MailboxConnectionRepository(session)
    connection = await repo.upsert(
        organization_id="acme",
        connected_by_user_id=USER_ID,
        provider="gmail",
        email_address="support@acme.com",
        access_token_encrypted="old-at",
        access_token_expires_at=datetime.now(UTC),
        refresh_token_encrypted="original-rt",
    )

    await repo.update_tokens(
        connection, access_token_encrypted="new-at", access_token_expires_at=datetime.now(UTC), refresh_token_encrypted=None
    )

    assert connection.access_token_encrypted == "new-at"
    assert connection.refresh_token_encrypted == "original-rt"


@pytest.mark.asyncio
async def test_get_by_id_is_scoped_to_organization(session):
    repo = MailboxConnectionRepository(session)
    connection = await repo.upsert(
        organization_id="org-a",
        connected_by_user_id=USER_ID,
        provider="gmail",
        email_address="a@org-a.com",
        access_token_encrypted=None,
        access_token_expires_at=None,
        refresh_token_encrypted="rt",
    )

    assert await repo.get_by_id("org-a", connection.id) is not None
    assert await repo.get_by_id("org-b", connection.id) is None
