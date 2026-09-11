"""
Unit tests for the mailbox poller's per-connection logic (Phase 18,
app/agents/runner.py's `_poll_mailbox_connection`). Same "fake
publish_event, real Postgres logic against in-memory SQLite" pattern as
tests/test_orchestrator_idempotency.py -- fast, deterministic, no real
Kafka broker needed.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.token_encryption import encrypt_token
from app.database.repositories.mailbox_connection_repository import MailboxConnectionRepository
from app.database.repositories.mailbox_ingested_message_repository import MailboxIngestedMessageRepository
from app.database.repositories.workflow_execution_repository import WorkflowExecutionRepository
from app.database.session import Base
from app.ingestion.fake_mailbox_provider import FakeMailboxProvider, make_message
from app.ingestion.mailbox_provider import MailboxAuthorizationError, MessagePage
from app.models.mailbox_connection import STATUS_ERROR
from app.models.workflow_execution import WorkflowExecution

USER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _import_runner():
    # Windows import-order workaround -- see app/main.py's module
    # docstring, mirrored by tests/test_phase12_kafka_integration.py for
    # this exact same reason.
    import pandas  # noqa: F401
    import sklearn  # noqa: F401

    from app.agents import runner

    return runner


@pytest_asyncio.fixture(autouse=True)
async def _fake_kafka_publish(monkeypatch):
    async def _fake_publish_event(topic, event):
        return None

    import app.services.email_intake_service as email_intake_module

    monkeypatch.setattr(email_intake_module, "publish_event", _fake_publish_event)


async def _make_active_connection(session_factory, provider="gmail", cursor=None):
    async with session_factory() as session:
        repo = MailboxConnectionRepository(session)
        connection = await repo.upsert(
            organization_id="acme",
            connected_by_user_id=USER_ID,
            provider=provider,
            email_address="support@acme.com",
            access_token_encrypted=encrypt_token("valid-access-token"),
            access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
            refresh_token_encrypted=encrypt_token("valid-refresh-token"),
        )
        if cursor is not None:
            await repo.update_sync_cursor(connection, cursor)
        return connection.id


@pytest.mark.asyncio
async def test_first_poll_establishes_a_cursor_and_dispatches_nothing(monkeypatch, session_factory):
    runner = _import_runner()
    monkeypatch.setattr(runner, "AsyncSessionLocal", session_factory)
    connection_id = await _make_active_connection(session_factory, cursor=None)

    fake = FakeMailboxProvider(pages=[MessagePage(messages=[], next_cursor="cursor-1")])
    monkeypatch.setattr(runner, "build_provider", lambda provider: fake)

    await runner._poll_mailbox_connection(connection_id)

    async with session_factory() as session:
        connection = await MailboxConnectionRepository(session).get_by_id("acme", connection_id)
    assert connection.sync_cursor == "cursor-1"
    assert fake.fetch_calls == [(None, runner.get_settings().MAILBOX_MAX_MESSAGES_PER_POLL)]


@pytest.mark.asyncio
async def test_poll_dispatches_new_messages_and_advances_the_cursor(monkeypatch, session_factory):
    runner = _import_runner()
    monkeypatch.setattr(runner, "AsyncSessionLocal", session_factory)
    connection_id = await _make_active_connection(session_factory, cursor="cursor-0")

    message = make_message(message_id="gmail-msg-1", subject="Help", body_text="I need help")
    fake = FakeMailboxProvider(pages=[MessagePage(messages=[message], next_cursor="cursor-1")])
    monkeypatch.setattr(runner, "build_provider", lambda provider: fake)

    await runner._poll_mailbox_connection(connection_id)

    async with session_factory() as session:
        connection = await MailboxConnectionRepository(session).get_by_id("acme", connection_id)
        assert connection.sync_cursor == "cursor-1"

        workflows = (await session.execute(select(WorkflowExecution))).scalars().all()
        assert len(workflows) == 1

        already_ingested = await MailboxIngestedMessageRepository(session).is_already_ingested(connection_id, "gmail-msg-1")
        assert already_ingested is True


@pytest.mark.asyncio
async def test_poll_does_not_advance_cursor_when_a_dispatch_fails(monkeypatch, session_factory):
    runner = _import_runner()
    monkeypatch.setattr(runner, "AsyncSessionLocal", session_factory)
    connection_id = await _make_active_connection(session_factory, cursor="cursor-0")

    message = make_message(message_id="gmail-msg-1")
    fake = FakeMailboxProvider(pages=[MessagePage(messages=[message], next_cursor="cursor-1")])
    monkeypatch.setattr(runner, "build_provider", lambda provider: fake)

    async def _failing_publish_event(topic, event):
        raise RuntimeError("kafka is down")

    import app.services.email_intake_service as email_intake_module

    monkeypatch.setattr(email_intake_module, "publish_event", _failing_publish_event)

    await runner._poll_mailbox_connection(connection_id)

    async with session_factory() as session:
        connection = await MailboxConnectionRepository(session).get_by_id("acme", connection_id)
        assert connection.sync_cursor == "cursor-0"  # unchanged -- retried next cycle
        already_ingested = await MailboxIngestedMessageRepository(session).is_already_ingested(connection_id, "gmail-msg-1")
        assert already_ingested is False


@pytest.mark.asyncio
async def test_poll_skips_a_message_already_recorded_as_ingested(monkeypatch, session_factory):
    runner = _import_runner()
    monkeypatch.setattr(runner, "AsyncSessionLocal", session_factory)
    connection_id = await _make_active_connection(session_factory, cursor="cursor-0")

    message = make_message(message_id="gmail-msg-1")
    fake = FakeMailboxProvider(pages=[MessagePage(messages=[message], next_cursor="cursor-1")])
    monkeypatch.setattr(runner, "build_provider", lambda provider: fake)

    async with session_factory() as session:
        workflow = await WorkflowExecutionRepository(session).create(organization_id="acme")
        await MailboxIngestedMessageRepository(session).record(connection_id, "gmail-msg-1", workflow.id)

    dispatch_calls = []

    async def _tracking_publish_event(topic, event):
        dispatch_calls.append(event)

    import app.services.email_intake_service as email_intake_module

    monkeypatch.setattr(email_intake_module, "publish_event", _tracking_publish_event)

    await runner._poll_mailbox_connection(connection_id)

    assert dispatch_calls == []  # never re-dispatched
    async with session_factory() as session:
        connection = await MailboxConnectionRepository(session).get_by_id("acme", connection_id)
        assert connection.sync_cursor == "cursor-1"  # still advances -- nothing was pending


@pytest.mark.asyncio
async def test_poll_refreshes_an_expired_access_token_before_fetching(monkeypatch, session_factory):
    runner = _import_runner()
    monkeypatch.setattr(runner, "AsyncSessionLocal", session_factory)

    async with session_factory() as session:
        repo = MailboxConnectionRepository(session)
        connection = await repo.upsert(
            organization_id="acme",
            connected_by_user_id=USER_ID,
            provider="gmail",
            email_address="support@acme.com",
            access_token_encrypted=encrypt_token("stale-access-token"),
            access_token_expires_at=datetime.now(UTC) - timedelta(minutes=5),  # already expired
            refresh_token_encrypted=encrypt_token("valid-refresh-token"),
        )
        await repo.update_sync_cursor(connection, "cursor-0")
        connection_id = connection.id

    fake = FakeMailboxProvider(pages=[MessagePage(messages=[], next_cursor="cursor-1")])
    monkeypatch.setattr(runner, "build_provider", lambda provider: fake)

    await runner._poll_mailbox_connection(connection_id)

    assert fake.refresh_calls == ["valid-refresh-token"]


@pytest.mark.asyncio
async def test_poll_marks_connection_errored_when_refresh_token_is_rejected(monkeypatch, session_factory):
    runner = _import_runner()
    monkeypatch.setattr(runner, "AsyncSessionLocal", session_factory)

    async with session_factory() as session:
        repo = MailboxConnectionRepository(session)
        connection = await repo.upsert(
            organization_id="acme",
            connected_by_user_id=USER_ID,
            provider="gmail",
            email_address="support@acme.com",
            access_token_encrypted=None,
            access_token_expires_at=None,
            refresh_token_encrypted=encrypt_token("revoked-refresh-token"),
        )
        connection_id = connection.id

    fake = FakeMailboxProvider()

    def _raise_auth_error(refresh_token):
        raise MailboxAuthorizationError("revoked")

    fake.refresh_access_token = _raise_auth_error
    monkeypatch.setattr(runner, "build_provider", lambda provider: fake)

    await runner._poll_mailbox_connection(connection_id)

    async with session_factory() as session:
        connection = await MailboxConnectionRepository(session).get_by_id("acme", connection_id)
        assert connection.status == STATUS_ERROR
        assert connection.last_error is not None


@pytest.mark.asyncio
async def test_poll_skips_a_connection_that_is_already_in_an_error_state(monkeypatch, session_factory):
    runner = _import_runner()
    monkeypatch.setattr(runner, "AsyncSessionLocal", session_factory)

    async with session_factory() as session:
        repo = MailboxConnectionRepository(session)
        connection = await repo.upsert(
            organization_id="acme",
            connected_by_user_id=USER_ID,
            provider="gmail",
            email_address="support@acme.com",
            access_token_encrypted=None,
            access_token_expires_at=None,
            refresh_token_encrypted=encrypt_token("rt"),
        )
        await repo.mark_error(connection, "previously failed")
        connection_id = connection.id

    build_provider_calls = []
    monkeypatch.setattr(runner, "build_provider", lambda provider: build_provider_calls.append(provider))

    await runner._poll_mailbox_connection(connection_id)

    assert build_provider_calls == []  # never even attempted -- status != active short-circuits
