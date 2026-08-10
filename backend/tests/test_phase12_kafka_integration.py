"""
Real, end-to-end integration test for the Multi-Agent Architecture
(Module 13 / Phase 12, FR-63-67) -- runs the actual Orchestrator + all 6
specialist agent consumers (app/agents/runner.py's own task set) against
a REAL Kafka broker and REAL Postgres database, submits real emails
through `POST /api/v1/email/process`'s underlying function, and polls
`GET /api/v1/workflows/{job_id}` until the workflow reaches a terminal
state.

Skipped by default -- every unit test elsewhere (test_messaging_retry.py,
test_messaging_schemas.py, test_agent_execution_repository.py,
test_workflow_execution_repository.py, test_routing_service_precomputed.py)
covers the individual pieces without needing Docker/network access. This
file is the one place that proves the PIECES work TOGETHER, for real --
"tests must prove FR-63-67 rather than merely test individual classes"
(master prompt section 19).

WHY container provisioning and env vars are NOT set from inside a pytest
fixture (a real ordering bug found while writing this file, not a
hypothetical): `tests/conftest.py` imports `app.main` at MODULE level,
and pytest loads conftest.py during COLLECTION -- before any fixture in
THIS file ever runs. `app.main`'s import chain calls
`app.core.config.get_settings()` (lru_cache'd) and binds
`app.database.session.engine` to whatever `POSTGRES_*` env vars exist AT
THAT MOMENT. A fixture in this file setting `os.environ["POSTGRES_PORT"]`
is provably too late -- confirmed by direct reproduction: an earlier
version of this file that set env vars inside an autouse fixture produced
`UndefinedTableError: relation "workflow_executions" does not exist`
(the real app engine, cached against the WRONG Postgres, one that was
never migrated) and `aiokafka.errors.KafkaConnectionError` (cached
against the wrong Kafka port). The fix is the one this file now uses:
env vars must be exported in the SHELL, before `python -m pytest` even
starts, exactly like `test_abstractive_summarizer_slow.py`'s
`RUN_SLOW_TESTS=1` convention already requires for its own reason.

WHY all three scenarios are ONE test function, not three (a second real
ordering bug found while writing this file): pytest-asyncio gives each
`async def test_*` its own event loop by default. `app.database.session`'s
`engine` is a module-level singleton with its own asyncpg connection
pool -- a connection (or the pool's internal state) created in test A's
event loop is not valid once that loop closes and test B's loop starts;
`engine.dispose()` between tests was tried and did NOT fully resolve it
(reproduced: `AttributeError: 'NoneType' object has no attribute 'send'`
deep inside asyncpg's connection teardown, triggered from the NEXT test's
loop). Running every scenario inside one `async def test_...` -- one
event loop, start to finish -- sidesteps the whole class of failure
rather than fighting it. A useful side effect: the six ML services are
`@lru_cache`'d singletons, so scenarios 2 and 3 also run warm (fast)
instead of re-paying each model's cold-load cost.

Run explicitly (PowerShell):
    docker run -d --name phase12_pg -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=email_intelligence -p 5557:5432 postgres:16-alpine
    docker run -d --name phase12_kafka -p 9096:9092 -e KAFKA_NODE_ID=1 -e KAFKA_PROCESS_ROLES=broker,controller -e KAFKA_LISTENERS=PLAINTEXT://localhost:29092,CONTROLLER://localhost:29093,PLAINTEXT_HOST://0.0.0.0:9092 -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://localhost:29092,PLAINTEXT_HOST://localhost:9096 -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@localhost:29093 -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER -e KAFKA_INTER_BROKER_LISTENER_NAME=PLAINTEXT -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 apache/kafka:3.9.0
    # wait for both to be ready, then:
    POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres POSTGRES_HOST=localhost POSTGRES_PORT=5557 POSTGRES_DB=email_intelligence python -m alembic upgrade head
    RUN_KAFKA_INTEGRATION_TESTS=1 POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres POSTGRES_HOST=localhost POSTGRES_PORT=5557 POSTGRES_DB=email_intelligence KAFKA_BOOTSTRAP_SERVERS=localhost:9096 KAFKA_CONSUMER_GROUP_PREFIX=pytest-phase12 python -m pytest tests/test_phase12_kafka_integration.py -v -s
    docker rm -f phase12_pg phase12_kafka

This exact sequence (with these exact ports) was run to verify this file
-- see PHASE_12_COMPLETION_REPORT.md's test results section for the
outcome.
"""

import asyncio
import os
import time
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_KAFKA_INTEGRATION_TESTS") != "1",
    reason="Requires real Postgres + Kafka, provisioned and pointed at via env vars BEFORE pytest starts "
    "(see this file's module docstring for the exact commands) -- opt in with RUN_KAFKA_INTEGRATION_TESTS=1",
)


async def _wait_for_terminal_status(get_workflow_status, job_id, session_factory, timeout=90.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        async with session_factory() as session:
            last = await get_workflow_status(job_id, "default", session)
        if last.status in ("COMPLETED", "FAILED", "PARTIAL"):
            return last
        await asyncio.sleep(1.0)
    return last


@pytest.mark.asyncio
async def test_multi_agent_pipeline_end_to_end():
    # Windows import-order workaround -- see app/main.py's module docstring.
    import pandas  # noqa: F401
    import sklearn  # noqa: F401

    from app.agents.runner import SPECIALIST_AGENTS, _run_orchestrator, _run_specialist
    from app.agents.spam_agent import SpamAgent
    from app.api.v1.endpoints.workflows import get_workflow_status, process_email
    from app.database.repositories.agent_execution_repository import AgentExecutionRepository
    from app.database.session import AsyncSessionLocal
    from app.messaging.producer import start_producer, stop_producer
    from app.messaging.schemas import AgentEvent
    from app.schemas.workflow import EmailProcessRequest

    await start_producer()
    tasks = [asyncio.create_task(_run_specialist(cls)) for cls in SPECIALIST_AGENTS]
    tasks.append(asyncio.create_task(_run_orchestrator()))
    await asyncio.sleep(5)  # let consumers join their groups

    try:
        # --- Scenario 1: full 6-agent dispatch for a non-spam email (FR-63/FR-64) ---
        async with AsyncSessionLocal() as session:
            response = await process_email(
                EmailProcessRequest(
                    subject="Meeting reschedule",
                    body="Hi team, can we move tomorrow's 3pm meeting to 4pm? Thanks.",
                    sender_email="colleague@example.com",
                    organization_id="default",
                ),
                session,
            )
        assert response.status == "PENDING"

        normal = await _wait_for_terminal_status(get_workflow_status, response.job_id, AsyncSessionLocal)

        assert normal is not None, "workflow never reached a terminal status within the timeout"
        assert normal.status in ("COMPLETED", "PARTIAL"), normal.status
        assert normal.email_id is not None, "routing+retrieval indexing should have produced a canonical email_id"

        agent_names = {a.agent_name for a in normal.agents}
        assert agent_names == {"spam", "priority", "category", "sentiment", "intent", "summarization"}
        for a in normal.agents:
            assert a.status == "COMPLETED", (a.agent_name, a.status, a.error_message)
            assert a.attempt_count >= 1

        # --- Scenario 2: R-SPAM-GATE short-circuit for an unambiguous spam email ---
        async with AsyncSessionLocal() as session:
            spam_response = await process_email(
                EmailProcessRequest(
                    subject="WIN A FREE PRIZE NOW",
                    body="CLICK HERE NOW to claim your free prize!!! Limited time offer, act now!!!",
                    sender_email="spammer@example.com",
                    organization_id="default",
                ),
                session,
            )

        spam = await _wait_for_terminal_status(get_workflow_status, spam_response.job_id, AsyncSessionLocal)

        assert spam is not None
        assert spam.status in ("COMPLETED", "PARTIAL"), spam.status
        spam_agent_names = {a.agent_name for a in spam.agents}
        assert spam_agent_names == {"spam", "summarization"}, (
            "R-SPAM-GATE should have prevented priority/category/sentiment/intent from ever dispatching"
        )

        # --- Scenario 3: duplicate Kafka delivery is idempotent (FR-65) ---
        dup_job_id = uuid.uuid4()
        dup_event = AgentEvent(
            job_id=dup_job_id,
            email_id=uuid.uuid4(),
            event_type="email.spam.requested",
            correlation_id=dup_job_id,
            payload={"subject": "hello", "body": "world"},
        )
        raw = dup_event.to_kafka_value()

        agent = SpamAgent()
        await agent.handle_message(raw)
        await agent.handle_message(raw)  # simulate redelivery of the exact same message

        async with AsyncSessionLocal() as session:
            repo = AgentExecutionRepository(session)
            rows = await repo.list_for_workflow(dup_job_id)

        assert len(rows) == 1, f"expected exactly one agent_executions row, got {len(rows)}"
        assert rows[0].status == "COMPLETED"
        assert rows[0].attempt_count == 1, "the second delivery must not have re-run the ML call"
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await stop_producer()
