"""
Entrypoint: `python -m app.agents.runner` (docker-compose's `agents`
service, see docker-compose.yml).

Why one process running seven consumer tasks (6 specialist agents +
Orchestrator) instead of seven separate containers/processes: at this
project's current scale (a local dev/demo deployment, zero production
traffic -- same standing status every other phase discloses), seven
processes would be seven times the memory footprint for loading each
ML module's artifacts, with no real concurrency benefit this codebase's
actual load justifies. Each agent still gets its OWN Kafka consumer group
(see messaging/consumer.py's build_consumer, `f"{prefix}-{agent_name}"`),
so splitting them into separate processes/containers later -- for real
horizontal scaling, when there's evidence it's needed -- is purely an
infrastructure change (run this same module N times with different
`AGENT_NAME` filters), not a code rewrite. Same "the layering exists now,
extraction later is a refactor, not a rewrite" philosophy
docs/architecture.md already established for the services/ layer.
"""

# Import-order workaround (Phase 9, restated for this SEPARATE entrypoint):
# this module is started directly (`python -m app.agents.runner`, see
# docker-compose.yml's `agents` service `command`), not via app/main.py --
# so app/main.py's own top-of-file `import pandas; import sklearn` guard
# (see that file's module docstring for the full explanation and the exact
# Windows fault it prevents: transformers' lazy-module `__getattr__`
# resolving a sklearn/pandas/pyarrow import for the first time when
# summarization and retrieval both end up in the same import sweep) does
# NOT run before this module imports every specialist agent below,
# including summarization_agent (pulls in transformers) alongside
# category_agent/priority_agent/etc. (pull in sklearn) and, via the
# Orchestrator, retrieval_service. Reproduced directly: omitting this
# caused a real segfault (exit 139) running this exact module standalone.
import asyncio
import logging
import signal
import uuid
from datetime import UTC, datetime, timedelta

import pandas  # noqa: F401,E402
import sklearn  # noqa: F401,E402

from app.agents.category_agent import CategoryAgent
from app.agents.intent_agent import IntentAgent
from app.agents.orchestrator import Orchestrator
from app.agents.priority_agent import PriorityAgent
from app.agents.sentiment_agent import SentimentAgent
from app.agents.spam_agent import SpamAgent
from app.agents.summarization_agent import SummarizationAgent
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.metrics import (
    MAILBOX_CONNECTIONS_ERRORED,
    MAILBOX_MESSAGES_INGESTED_TOTAL,
    STUCK_WORKFLOWS,
    start_metrics_server,
)
from app.core.token_encryption import TokenDecryptionError, decrypt_token, encrypt_token
from app.database.repositories.mailbox_connection_repository import MailboxConnectionRepository
from app.database.repositories.mailbox_ingested_message_repository import (
    MailboxIngestedMessageRepository,
)
from app.database.repositories.workflow_execution_repository import WorkflowExecutionRepository
from app.database.session import AsyncSessionLocal
from app.ingestion.mailbox_provider import MailboxAuthorizationError, MailboxProviderError
from app.ingestion.provider_factory import build_provider
from app.messaging import topics
from app.messaging.consumer import build_consumer, consume_forever
from app.messaging.producer import start_producer, stop_producer
from app.messaging.topic_admin import ensure_topics_exist
from app.models.mailbox_connection import STATUS_ACTIVE, MailboxConnection
from app.services import scheduled_jobs
from app.services.email_intake_service import EmailDispatchFailed, dispatch_email_for_processing

logger = logging.getLogger("app.agents.runner")

SPECIALIST_AGENTS = (
    SpamAgent,
    PriorityAgent,
    CategoryAgent,
    SentimentAgent,
    IntentAgent,
    SummarizationAgent,
)


async def _run_specialist(agent_cls) -> None:
    agent = agent_cls()
    settings = get_settings()
    consumer = build_consumer(
        topics.requested_topic(agent.agent_name),
        group_id=f"{settings.KAFKA_CONSUMER_GROUP_PREFIX}-{agent.agent_name}",
    )
    logger.info("agent_consumer_starting", extra={"agent": agent.agent_name})
    await consume_forever(consumer, agent.handle_message)


async def _run_orchestrator() -> None:
    orchestrator = Orchestrator()
    settings = get_settings()
    consumer = build_consumer(
        *orchestrator.consumer_topics(),
        group_id=f"{settings.KAFKA_CONSUMER_GROUP_PREFIX}-{orchestrator.consumer_group}",
    )
    logger.info("orchestrator_consumer_starting")
    await consume_forever(consumer, orchestrator.handle_message)


async def _run_stuck_workflow_check() -> None:
    """Phase 16B / FR-72: periodic poll, not event-driven -- a stuck
    workflow is defined by the ABSENCE of an event (nothing ever reports
    to move it past RUNNING), so there is no event to react to. Detection
    only, sets a Gauge; does not touch workflow state. See
    WorkflowExecutionRepository.list_stale_running's docstring for why
    recovery stays out of scope."""
    settings = get_settings()
    while True:
        try:
            async with AsyncSessionLocal() as session:
                repo = WorkflowExecutionRepository(session)
                stale = await repo.list_stale_running(settings.STUCK_WORKFLOW_THRESHOLD_MINUTES)
            STUCK_WORKFLOWS.set(len(stale))
            if stale:
                logger.warning(
                    "stuck_workflows_detected",
                    extra={"count": len(stale), "job_ids": [str(w.id) for w in stale]},
                )
        except Exception:
            # A failed check shouldn't crash the whole agents process --
            # same graceful-degradation stance as every warmup step in
            # app/main.py's lifespan.
            logger.error("stuck_workflow_check_failed", exc_info=True)
        await asyncio.sleep(settings.STUCK_WORKFLOW_CHECK_INTERVAL_SECONDS)


# Refresh a bit before actual expiry -- avoids a token that's technically
# still valid when read but expires mid-flight against a slow provider
# response.
_ACCESS_TOKEN_REFRESH_MARGIN = timedelta(minutes=2)


async def _poll_mailbox_connection(connection_id: uuid.UUID) -> None:
    """One connection, one session, one poll cycle. Isolated per-connection
    on purpose: one connection stuck in an error state must never prevent
    every OTHER connection's poll turn -- same "one bad row doesn't sink
    the loop" stance as _run_stuck_workflow_check above."""
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        connection = await session.get(MailboxConnection, connection_id)
        if connection is None or connection.is_deleted or connection.status != STATUS_ACTIVE:
            return

        connection_repo = MailboxConnectionRepository(session)
        try:
            provider = build_provider(connection.provider)
        except Exception:
            logger.error("mailbox_provider_unavailable", exc_info=True, extra={"connection_id": str(connection_id)})
            return

        access_token = None
        now = datetime.now(UTC)
        # SQLite (used by this function's own unit tests, see
        # tests/test_mailbox_poll.py) drops tzinfo on round-trip even for a
        # DateTime(timezone=True) column -- confirmed by direct
        # reproduction (TypeError: can't subtract/compare offset-naive and
        # offset-aware datetimes), same issue
        # WorkflowExecutionRepository.update_status already documents and
        # normalizes for. Real Postgres (timestamptz) does not have this
        # problem, but normalizing here costs nothing and is correct
        # regardless of backend.
        expires_at = connection.access_token_expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if connection.access_token_encrypted and expires_at and expires_at > now + _ACCESS_TOKEN_REFRESH_MARGIN:
            try:
                access_token = decrypt_token(connection.access_token_encrypted)
            except TokenDecryptionError:
                access_token = None  # fall through to a refresh below

        if access_token is None:
            try:
                refresh_token = decrypt_token(connection.refresh_token_encrypted)
                tokens = await asyncio.to_thread(provider.refresh_access_token, refresh_token)
            except TokenDecryptionError as e:
                await connection_repo.mark_error(connection, f"Stored refresh token could not be decrypted: {e}")
                return
            except MailboxAuthorizationError as e:
                await connection_repo.mark_error(connection, f"Refresh token was rejected -- reconnect this mailbox: {e}")
                return
            except MailboxProviderError as e:
                logger.warning("mailbox_token_refresh_failed", extra={"connection_id": str(connection_id), "error": str(e)})
                return  # transient -- try again next cycle

            access_token = tokens.access_token
            await connection_repo.update_tokens(
                connection,
                access_token_encrypted=encrypt_token(tokens.access_token),
                access_token_expires_at=tokens.expires_at,
                refresh_token_encrypted=encrypt_token(tokens.refresh_token) if tokens.refresh_token else None,
            )

        try:
            page = await asyncio.to_thread(
                provider.fetch_new_messages, access_token, connection.sync_cursor, settings.MAILBOX_MAX_MESSAGES_PER_POLL
            )
        except MailboxAuthorizationError as e:
            await connection_repo.mark_error(connection, f"Access token was rejected during fetch -- reconnect this mailbox: {e}")
            return
        except MailboxProviderError as e:
            logger.warning("mailbox_fetch_failed", extra={"connection_id": str(connection_id), "error": str(e)})
            return  # transient -- cursor untouched, retried next cycle

        ingested_repo = MailboxIngestedMessageRepository(session)
        all_dispatched = True
        for message in page.messages:
            if await ingested_repo.is_already_ingested(connection.id, message.message_id):
                MAILBOX_MESSAGES_INGESTED_TOTAL.labels(provider=connection.provider, outcome="duplicate").inc()
                continue
            try:
                workflow = await dispatch_email_for_processing(
                    session,
                    organization_id=connection.organization_id,
                    subject=message.subject,
                    body=message.body_text,
                    sender_email=message.sender_email,
                )
            except EmailDispatchFailed:
                # Leaves this message un-recorded and, below, the cursor
                # un-advanced -- see MailboxIngestedMessage's own module
                # docstring for why this is what makes a retry safe rather
                # than a duplicate-dispatch risk.
                all_dispatched = False
                MAILBOX_MESSAGES_INGESTED_TOTAL.labels(provider=connection.provider, outcome="error").inc()
                logger.warning(
                    "mailbox_message_dispatch_failed",
                    extra={"connection_id": str(connection_id), "message_id": message.message_id},
                )
                continue
            await ingested_repo.record(connection.id, message.message_id, workflow.id)
            MAILBOX_MESSAGES_INGESTED_TOTAL.labels(provider=connection.provider, outcome="success").inc()

        if all_dispatched:
            await connection_repo.update_sync_cursor(connection, page.next_cursor)


async def _run_mailbox_poll() -> None:
    """Phase 18, FR-01/FR-02/FR-03. Periodic poll, not push -- see
    Settings.MAILBOX_POLL_INTERVAL_SECONDS's own comment on why neither
    Gmail Pub/Sub nor Graph webhooks are reachable from this deployment.
    Connections are polled sequentially, not concurrently: at this
    project's scale (a handful of connected mailboxes, same standing
    "no production traffic yet" status every phase discloses), the
    simplicity of one loop outweighs the latency benefit of fanning them
    out -- a slow connection delays the NEXT connection's turn within this
    cycle, but never blocks the six Kafka consumer tasks running
    alongside this one (each `await asyncio.to_thread(...)` call above
    yields the event loop back to them)."""
    settings = get_settings()
    while True:
        try:
            async with AsyncSessionLocal() as session:
                connection_repo = MailboxConnectionRepository(session)
                connection_ids = [c.id for c in await connection_repo.list_all_active()]
                errored_count = await connection_repo.count_errored()
            MAILBOX_CONNECTIONS_ERRORED.set(errored_count)

            for connection_id in connection_ids:
                await _poll_mailbox_connection(connection_id)
        except Exception:
            # A failed poll cycle shouldn't crash the whole agents process
            # -- same graceful-degradation stance as every other periodic
            # task in this module.
            logger.error("mailbox_poll_cycle_failed", exc_info=True)
        await asyncio.sleep(settings.MAILBOX_POLL_INTERVAL_SECONDS)


async def _run_periodic(name: str, job, interval_seconds: int) -> None:
    """Phase 22: generic loop for app/services/scheduled_jobs.py -- one
    session per pass, failures logged and retried next interval, same
    stance as _run_stuck_workflow_check above."""
    while True:
        try:
            async with AsyncSessionLocal() as session:
                await job(session)
        except Exception:
            logger.error(f"{name}_failed", exc_info=True)
        await asyncio.sleep(interval_seconds)


async def main() -> None:
    setup_logging()
    settings = get_settings()
    start_metrics_server(settings.METRICS_PORT)
    logger.info("metrics_server_started", extra={"port": settings.METRICS_PORT})
    await ensure_topics_exist()
    await start_producer()

    tasks = [asyncio.create_task(_run_specialist(cls)) for cls in SPECIALIST_AGENTS]
    tasks.append(asyncio.create_task(_run_orchestrator()))
    tasks.append(asyncio.create_task(_run_stuck_workflow_check()))
    tasks.append(asyncio.create_task(_run_mailbox_poll()))
    for name, job, interval in (
        ("sla_sweep", scheduled_jobs.sla_sweep, settings.SLA_SWEEP_INTERVAL_SECONDS),
        ("drift_check", scheduled_jobs.drift_check, settings.DRIFT_CHECK_INTERVAL_SECONDS),
        ("retraining", scheduled_jobs.run_retraining, settings.RETRAINING_POLL_INTERVAL_SECONDS),
        ("weekly_reports", scheduled_jobs.generate_weekly_reports, settings.REPORT_CHECK_INTERVAL_SECONDS),
        ("retention_purge", scheduled_jobs.purge_retention, settings.RETENTION_PURGE_INTERVAL_SECONDS),
    ):
        tasks.append(asyncio.create_task(_run_periodic(name, job, interval)))

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # Windows local dev (non-Docker `python -m app.agents.runner`) -- Ctrl+C still raises KeyboardInterrupt

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("agents_runner_shutting_down")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await stop_producer()


if __name__ == "__main__":
    asyncio.run(main())
