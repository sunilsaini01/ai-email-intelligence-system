"""DB-level tests for agent_executions (Module 13 / Phase 12) -- same
in-memory-SQLite shape as tests/test_feedback_event_repository.py.
Exercises the idempotency primitive (get_or_create) and the status-
transition methods every agent's handler (app/agents/base.py) relies on."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.repositories.agent_execution_repository import AgentExecutionRepository
from app.database.session import Base
from app.models.agent_execution import STATUS_COMPLETED, STATUS_FAILED, STATUS_PENDING, STATUS_RUNNING


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
async def test_get_or_create_creates_a_pending_row(session):
    repo = AgentExecutionRepository(session)
    workflow_id = uuid.uuid4()
    execution = await repo.get_or_create(workflow_id, "spam", uuid.uuid4())

    assert execution.status == STATUS_PENDING
    assert execution.attempt_count == 0
    assert execution.workflow_id == workflow_id
    assert execution.agent_name == "spam"


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent_for_the_same_workflow_and_agent(session):
    """The exact idempotency guarantee FR-65's at-least-once delivery
    requires (app/agents/base.py) -- a redelivered message for a
    (workflow, agent) pair that already has a row must get that SAME row
    back, never a second one."""
    repo = AgentExecutionRepository(session)
    workflow_id = uuid.uuid4()
    event_id = uuid.uuid4()

    first = await repo.get_or_create(workflow_id, "spam", event_id)
    second = await repo.get_or_create(workflow_id, "spam", uuid.uuid4())  # even with a DIFFERENT event_id

    assert first.id == second.id


@pytest.mark.asyncio
async def test_different_agents_in_the_same_workflow_get_different_rows(session):
    repo = AgentExecutionRepository(session)
    workflow_id = uuid.uuid4()

    spam = await repo.get_or_create(workflow_id, "spam", uuid.uuid4())
    priority = await repo.get_or_create(workflow_id, "priority", uuid.uuid4())

    assert spam.id != priority.id


@pytest.mark.asyncio
async def test_mark_running_increments_attempt_count(session):
    repo = AgentExecutionRepository(session)
    execution = await repo.get_or_create(uuid.uuid4(), "spam", uuid.uuid4())

    execution = await repo.mark_running(execution)
    assert execution.status == STATUS_RUNNING
    assert execution.attempt_count == 1

    execution = await repo.mark_running(execution)
    assert execution.attempt_count == 2


@pytest.mark.asyncio
async def test_mark_completed_clears_any_prior_error_state(session):
    repo = AgentExecutionRepository(session)
    execution = await repo.get_or_create(uuid.uuid4(), "spam", uuid.uuid4())
    execution = await repo.mark_running(execution)
    execution = await repo.mark_retrying(execution, "transient timeout")
    assert execution.error_message == "transient timeout"

    execution = await repo.mark_completed(execution, duration_ms=12.5, model_version="svm-v1")
    assert execution.status == STATUS_COMPLETED
    assert execution.error_type is None
    assert execution.error_message is None
    assert execution.model_version == "svm-v1"


@pytest.mark.asyncio
async def test_mark_failed_records_error_type_and_message(session):
    repo = AgentExecutionRepository(session)
    execution = await repo.get_or_create(uuid.uuid4(), "spam", uuid.uuid4())

    execution = await repo.mark_failed(execution, "permanent", "malformed payload", duration_ms=3.0)
    assert execution.status == STATUS_FAILED
    assert execution.error_type == "permanent"
    assert execution.error_message == "malformed payload"


@pytest.mark.asyncio
async def test_list_for_workflow_returns_every_agent_execution(session):
    repo = AgentExecutionRepository(session)
    workflow_id = uuid.uuid4()
    await repo.get_or_create(workflow_id, "spam", uuid.uuid4())
    await repo.get_or_create(workflow_id, "priority", uuid.uuid4())
    await repo.get_or_create(uuid.uuid4(), "spam", uuid.uuid4())  # different workflow -- must not appear

    rows = await repo.list_for_workflow(workflow_id)
    assert {r.agent_name for r in rows} == {"spam", "priority"}
