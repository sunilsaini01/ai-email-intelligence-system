"""
Regression tests for a real bug found while manually testing the running
Docker stack: the six specialist agents (app/agents/*_agent.py) computed a
correct ML result and handed it to the Orchestrator, but never wrote it
into the same `*_prediction_logs` table their own HTTP endpoint
(app/api/v1/endpoints/*.py) already writes to on every direct
`/spam/predict`-style call. Since app/services/dashboard_service.py reads
exclusively from those tables, the dashboard was structurally blind to
every email processed via POST /email/process or the mailbox poller --
the two paths this project actually wants used going forward.

Two things are tested here: each agent's persist_result() override writes
the same row its own endpoint would (unit-level, direct calls, no Kafka
needed), and BaseAgent.handle_message itself actually calls
persist_result with the organization_id carried on the Kafka event's
metadata (not the six agents' own responsibility -- that wiring lives in
base.py).
"""

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import base as base_module
from app.agents.base import BaseAgent
from app.agents.category_agent import CategoryAgent
from app.agents.intent_agent import IntentAgent
from app.agents.priority_agent import PriorityAgent
from app.agents.sentiment_agent import SentimentAgent
from app.agents.spam_agent import SpamAgent
from app.agents.summarization_agent import SummarizationAgent
from app.database.session import Base
from app.messaging.schemas import AgentEvent
from app.models.category_prediction_log import CategoryPredictionLog
from app.models.intent_prediction_log import IntentPredictionLog
from app.models.priority_prediction_log import PriorityPredictionLog
from app.models.sentiment_prediction_log import SentimentPredictionLog
from app.models.spam_prediction_log import SpamPredictionLog
from app.models.summary_log import SummaryLog


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


PAYLOAD = {"subject": "Test subject", "body": "Test body", "sender_email": "a@b.com"}


@pytest.mark.asyncio
async def test_spam_agent_persists_a_row_matching_its_own_endpoints_shape(session_factory):
    result = {
        "is_spam": True,
        "status": "quarantined",
        "spam_score": 0.92,
        "confidence": 0.92,
        "threshold_used": 0.06,
        "model_version": "spam-v1",
        "processing_ms": 12.3,
    }
    async with session_factory() as session:
        await SpamAgent().persist_result(session, "acme", PAYLOAD, result)
        rows = (await session.execute(select(SpamPredictionLog))).scalars().all()

    assert len(rows) == 1
    assert rows[0].organization_id == "acme"
    assert rows[0].is_spam is True
    assert rows[0].subject == "Test subject"


@pytest.mark.asyncio
async def test_priority_agent_persists_a_row_matching_its_own_endpoints_shape(session_factory):
    result = {"priority": "Critical", "confidence": 0.8, "model_version": "priority-v1", "processing_ms": 5.0}
    async with session_factory() as session:
        await PriorityAgent().persist_result(session, "acme", PAYLOAD, result)
        rows = (await session.execute(select(PriorityPredictionLog))).scalars().all()

    assert len(rows) == 1
    assert rows[0].organization_id == "acme"
    assert rows[0].predicted_priority == "Critical"


@pytest.mark.asyncio
async def test_category_agent_persists_a_row_matching_its_own_endpoints_shape(session_factory):
    result = {
        "categories": [{"category": "Billing", "confidence": 0.7}, {"category": "Support", "confidence": 0.3}],
        "model_version": "category-v1",
        "processing_ms": 8.0,
    }
    async with session_factory() as session:
        await CategoryAgent().persist_result(session, "acme", PAYLOAD, result)
        rows = (await session.execute(select(CategoryPredictionLog))).scalars().all()

    assert len(rows) == 1
    assert rows[0].organization_id == "acme"
    assert rows[0].predicted_categories == ["Billing", "Support"]
    assert rows[0].confidences == {"Billing": 0.7, "Support": 0.3}


@pytest.mark.asyncio
async def test_sentiment_agent_persists_a_row_matching_its_own_endpoints_shape(session_factory):
    result = {"sentiment": "Negative", "confidence": 0.6, "model_version": "vader-v1", "processing_ms": 1.0}
    async with session_factory() as session:
        await SentimentAgent().persist_result(session, "acme", PAYLOAD, result)
        rows = (await session.execute(select(SentimentPredictionLog))).scalars().all()

    assert len(rows) == 1
    assert rows[0].organization_id == "acme"
    assert rows[0].predicted_sentiment == "Negative"


@pytest.mark.asyncio
async def test_intent_agent_persists_a_row_matching_its_own_endpoints_shape(session_factory):
    result = {
        "intents": [{"intent": "Refund", "confidence": 0.9}],
        "entities": {"ORDER_ID": ["#123"]},
        "model_version": "intent-v1",
        "processing_ms": 4.0,
    }
    async with session_factory() as session:
        await IntentAgent().persist_result(session, "acme", PAYLOAD, result)
        rows = (await session.execute(select(IntentPredictionLog))).scalars().all()

    assert len(rows) == 1
    assert rows[0].organization_id == "acme"
    assert rows[0].predicted_intents == ["Refund"]
    assert rows[0].confidences == {"Refund": 0.9}
    assert rows[0].entities == {"ORDER_ID": ["#123"]}


@pytest.mark.asyncio
async def test_summarization_agent_persists_a_row_matching_its_own_endpoints_shape(session_factory):
    result = {
        "summary": "A short summary.",
        "summary_type": "extractive",
        "skipped_short_input": False,
        "input_word_count": 200,
        "entity_preservation_rate": 0.95,
        "model_version": "textrank-v1",
        "processing_ms": 15.0,
    }
    async with session_factory() as session:
        await SummarizationAgent().persist_result(session, "acme", PAYLOAD, result)
        rows = (await session.execute(select(SummaryLog))).scalars().all()

    assert len(rows) == 1
    assert rows[0].organization_id == "acme"
    assert rows[0].summary == "A short summary."


# --- BaseAgent.handle_message wiring: does the org actually get threaded through? ---


class _FakeAgent(BaseAgent):
    """Minimal concrete BaseAgent -- records exactly what handle_message
    passed to persist_result, without any real ML call or repository."""

    agent_name = "fake"

    def __init__(self):
        self.persist_calls: list[tuple] = []

    async def run_ml_call(self, payload: dict) -> dict:
        return {"model_version": "fake-v1"}

    async def persist_result(self, session, organization_id, payload, result) -> None:
        self.persist_calls.append((organization_id, payload, result))


@pytest_asyncio.fixture(autouse=True)
async def _patch_agents_session(session_factory, monkeypatch):
    monkeypatch.setattr(base_module, "AsyncSessionLocal", session_factory)


@pytest.fixture(autouse=True)
def _fake_publish(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(base_module, "publish_event", _noop)
    monkeypatch.setattr(base_module, "publish_dead_letter", _noop)


@pytest.mark.asyncio
async def test_handle_message_calls_persist_result_with_the_events_organization_id():
    agent = _FakeAgent()
    event = AgentEvent(
        job_id=uuid.uuid4(),
        email_id=uuid.uuid4(),
        event_type="email.fake.requested",
        correlation_id=uuid.uuid4(),
        payload={"subject": "s", "body": "b"},
        metadata={"organization_id": "acme"},
    )

    await agent.handle_message(event.to_kafka_value())

    assert len(agent.persist_calls) == 1
    organization_id, payload, result = agent.persist_calls[0]
    assert organization_id == "acme"
    assert payload == {"subject": "s", "body": "b"}
    assert result == {"model_version": "fake-v1"}


@pytest.mark.asyncio
async def test_handle_message_falls_back_to_default_organization_when_metadata_has_none():
    """Defensive only -- every real caller (workflows.py, orchestrator.py)
    always sets organization_id on the event metadata; this just confirms
    a missing one degrades to the same DEFAULT_ORGANIZATION_ID every other
    model in this codebase falls back to, rather than crashing."""
    agent = _FakeAgent()
    event = AgentEvent(
        job_id=uuid.uuid4(),
        email_id=uuid.uuid4(),
        event_type="email.fake.requested",
        correlation_id=uuid.uuid4(),
        payload={"subject": "s", "body": "b"},
        metadata={},
    )

    await agent.handle_message(event.to_kafka_value())

    assert agent.persist_calls[0][0] == "default"


@pytest.mark.asyncio
async def test_handle_message_does_not_call_persist_result_when_the_ml_call_fails():
    from app.messaging.retry import PermanentAgentError

    class _FailingAgent(_FakeAgent):
        async def run_ml_call(self, payload: dict) -> dict:
            # PERMANENT -- fails on the first attempt with no retry
            # backoff delay, unlike an unclassified exception (which
            # app/messaging/retry.py's own docstring says defaults to
            # TRANSIENT and would sleep through real retries here).
            raise PermanentAgentError("boom")

    agent = _FailingAgent()
    event = AgentEvent(
        job_id=uuid.uuid4(),
        email_id=uuid.uuid4(),
        event_type="email.fake.requested",
        correlation_id=uuid.uuid4(),
        payload={"subject": "s", "body": "b"},
        metadata={"organization_id": "acme"},
    )

    await agent.handle_message(event.to_kafka_value())

    assert agent.persist_calls == []
