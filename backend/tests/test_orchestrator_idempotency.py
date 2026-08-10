"""
Regression test for a real bug found via code review (Module 13 / Phase
12): `Orchestrator._start_workflow` had no idempotency guard, unlike
every specialist agent (`app/agents/base.py`'s terminal-status check).

Under FR-65's at-least-once Kafka delivery, `email.processing.requested`
can be redelivered (e.g. the Orchestrator crashes after dispatching
agents but before its consumer offset commits). Without a guard,
`_start_workflow` would unconditionally re-dispatch spam/summarization
and reset `workflow_executions.status` back to RUNNING -- including for
a workflow that had ALREADY reached COMPLETED, with no way to ever
re-finalize it (the new in-memory tracker never receives completions for
an execution the specialist agents' own idempotency check has already
marked terminal and will not re-publish for).

Uses an in-memory SQLite session factory (monkeypatched into
app.agents.orchestrator's module namespace, mirroring the existing
per-test-SQLite convention) and a fake `publish_event` so this is a fast
unit test, not a real-infrastructure one.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import orchestrator as orchestrator_module
from app.agents.orchestrator import Orchestrator
from app.database.repositories.workflow_execution_repository import WorkflowExecutionRepository
from app.database.session import Base
from app.messaging import topics
from app.messaging.schemas import AgentEvent
from app.models.workflow_execution import STATUS_COMPLETED


@pytest_asyncio.fixture
async def session_factory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(orchestrator_module, "AsyncSessionLocal", factory)
    yield factory
    await engine.dispose()


@pytest.fixture
def fake_publish(monkeypatch):
    published = []

    async def _fake_publish_event(topic, event):
        published.append((topic, event))

    monkeypatch.setattr(orchestrator_module, "publish_event", _fake_publish_event)
    return published


@pytest.mark.asyncio
async def test_duplicate_email_processing_requested_does_not_reset_a_completed_workflow(
    session_factory, fake_publish
):
    async with session_factory() as session:
        workflow = await WorkflowExecutionRepository(session).create(organization_id="default")

    orch = Orchestrator()
    event = AgentEvent(
        job_id=workflow.id,
        email_id=workflow.id,
        event_type=topics.TOPIC_EMAIL_PROCESSING_REQUESTED,
        correlation_id=workflow.id,
        payload={"subject": "s", "body": "b", "sender_email": ""},
        metadata={"organization_id": "default"},
    )

    await orch.handle_message(event.to_kafka_value())
    assert workflow.id in orch._pending
    assert len(fake_publish) == 2  # spam + summarization dispatched

    # Simulate the workflow having already completed (as _finalize_workflow
    # would do), and the Orchestrator having restarted (losing _pending).
    async with session_factory() as session:
        repo = WorkflowExecutionRepository(session)
        wf = await repo.get_by_id("default", workflow.id)
        await repo.update_status(wf, STATUS_COMPLETED, mark_completed=True)
    orch._pending.clear()

    # Redelivery of the SAME email.processing.requested message.
    await orch.handle_message(event.to_kafka_value())

    assert len(fake_publish) == 2, "a duplicate start must NOT re-dispatch spam/summarization"
    assert workflow.id not in orch._pending, "a duplicate start must NOT recreate an in-memory tracker"

    async with session_factory() as session:
        wf = await WorkflowExecutionRepository(session).get_by_id("default", workflow.id)
        assert wf.status == STATUS_COMPLETED, "a duplicate start must NOT reset an already-completed workflow"


@pytest.mark.asyncio
async def test_first_delivery_of_email_processing_requested_dispatches_normally(session_factory, fake_publish):
    async with session_factory() as session:
        workflow = await WorkflowExecutionRepository(session).create(organization_id="default")

    orch = Orchestrator()
    event = AgentEvent(
        job_id=workflow.id,
        email_id=workflow.id,
        event_type=topics.TOPIC_EMAIL_PROCESSING_REQUESTED,
        correlation_id=workflow.id,
        payload={"subject": "s", "body": "b", "sender_email": ""},
        metadata={"organization_id": "default"},
    )

    await orch.handle_message(event.to_kafka_value())

    assert len(fake_publish) == 2
    dispatched_topics = {topic for topic, _ in fake_publish}
    assert dispatched_topics == {topics.requested_topic("spam"), topics.requested_topic("summarization")}
    assert workflow.id in orch._pending

    async with session_factory() as session:
        wf = await WorkflowExecutionRepository(session).get_by_id("default", workflow.id)
        assert wf.status == "RUNNING"
