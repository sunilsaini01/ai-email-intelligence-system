"""DB-level tests for workflow_executions (Module 13 / Phase 12; Phase 16B
duration_ms / list_stale_running additions for FR-72)."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.repositories.workflow_execution_repository import WorkflowExecutionRepository
from app.database.session import Base
from app.models.workflow_execution import STATUS_COMPLETED, STATUS_PENDING, STATUS_RUNNING


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
async def test_create_defaults_to_pending(session):
    repo = WorkflowExecutionRepository(session)
    workflow = await repo.create(organization_id="default")
    assert workflow.status == STATUS_PENDING
    assert workflow.email_id is None


@pytest.mark.asyncio
async def test_get_by_id_is_scoped_to_organization(session):
    repo = WorkflowExecutionRepository(session)
    workflow = await repo.create(organization_id="org-a")

    assert await repo.get_by_id("org-a", workflow.id) is not None
    assert await repo.get_by_id("org-b", workflow.id) is None


@pytest.mark.asyncio
async def test_update_status_sets_completed_at_only_when_asked(session):
    repo = WorkflowExecutionRepository(session)
    workflow = await repo.create(organization_id="default")

    updated = await repo.update_status(workflow, "RUNNING")
    assert updated.status == "RUNNING"
    assert updated.completed_at is None

    finished = await repo.update_status(updated, STATUS_COMPLETED, mark_completed=True)
    assert finished.status == STATUS_COMPLETED
    assert finished.completed_at is not None


@pytest.mark.asyncio
async def test_update_status_computes_duration_ms_only_when_marking_completed(session):
    """Phase 16B / FR-72: duration_ms is the metric
    email_workflow_duration_seconds is built from (see
    app/agents/orchestrator.py's _finalize_workflow) -- must be None until
    a terminal status is actually reached, and must reflect the real
    elapsed time from started_at, not zero/None on completion."""
    repo = WorkflowExecutionRepository(session)
    workflow = await repo.create(organization_id="default")
    assert workflow.duration_ms is None

    still_running = await repo.update_status(workflow, STATUS_RUNNING)
    assert still_running.duration_ms is None

    finished = await repo.update_status(still_running, STATUS_COMPLETED, mark_completed=True)
    assert finished.duration_ms is not None
    assert finished.duration_ms >= 0
    # Sanity bound: this test runs in milliseconds, not hours -- catches a
    # unit mistake (e.g. accidentally storing microseconds or seconds
    # instead of milliseconds) without needing to control the clock.
    assert finished.duration_ms < 60_000


@pytest.mark.asyncio
async def test_list_stale_running_only_returns_old_running_workflows(session):
    """Phase 16B / FR-72: the query behind workflow_stuck_total (see
    app/agents/runner.py's _run_stuck_workflow_check) -- must exclude
    terminal-status workflows and RUNNING workflows that are still within
    the threshold, and must include only genuinely stale RUNNING ones."""
    repo = WorkflowExecutionRepository(session)

    stale_running = await repo.create(organization_id="default")
    stale_running.status = STATUS_RUNNING
    stale_running.started_at = datetime.now(UTC) - timedelta(minutes=30)
    await session.commit()

    fresh_running = await repo.create(organization_id="default")
    fresh_running.status = STATUS_RUNNING
    fresh_running.started_at = datetime.now(UTC)
    await session.commit()

    stale_but_completed = await repo.create(organization_id="default")
    stale_but_completed.status = STATUS_COMPLETED
    stale_but_completed.started_at = datetime.now(UTC) - timedelta(minutes=30)
    await session.commit()

    stale = await repo.list_stale_running(older_than_minutes=10)

    stale_ids = {w.id for w in stale}
    assert stale_running.id in stale_ids
    assert fresh_running.id not in stale_ids
    assert stale_but_completed.id not in stale_ids
