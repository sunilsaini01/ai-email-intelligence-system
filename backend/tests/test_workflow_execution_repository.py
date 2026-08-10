"""DB-level tests for workflow_executions (Module 13 / Phase 12)."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.repositories.workflow_execution_repository import WorkflowExecutionRepository
from app.database.session import Base
from app.models.workflow_execution import STATUS_COMPLETED, STATUS_PENDING


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
