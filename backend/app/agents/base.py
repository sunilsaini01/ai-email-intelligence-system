"""
Base Kafka-agent abstraction (Module 13 / Phase 12, FR-64/FR-66/FR-67).

Each specialist agent (spam_agent.py, priority_agent.py, ...) is a thin
subclass supplying only `agent_name` and `run_ml_call()` -- calling the
EXISTING, unmodified service method (SpamService.classify(), etc.).
Everything else common to every agent (idempotency, retry/backoff,
structured logging, DB state transitions, publishing
completed/failed/DLQ) lives here exactly once, per Critical Rule #6 (no
ML logic duplicated) and the master prompt's own "reuse wherever possible"
instruction.

Retries happen INSIDE one handler invocation (in-process backoff sleep),
not by re-publishing to Kafka per attempt -- see
app/models/agent_execution.py's module docstring for why. This keeps
FR-66 simple and testable without needing a second round-trip through the
broker for something that's really "the ML call/DB write failed
transiently while we already have the message in hand," not "Kafka itself
is unavailable" (if Kafka were unavailable, this handler would never have
been invoked at all).
"""

import abc
import asyncio
import logging
import time
import uuid

from app.core.config import get_settings
from app.database.repositories.agent_execution_repository import AgentExecutionRepository
from app.database.session import AsyncSessionLocal
from app.messaging import topics
from app.messaging.producer import publish_dead_letter, publish_event
from app.messaging.retry import PERMANENT, classify_exception, compute_backoff_seconds
from app.messaging.schemas import AgentEvent, DeadLetterEnvelope
from app.models.agent_execution import STATUS_COMPLETED, STATUS_FAILED

logger = logging.getLogger("app.agents")


class BaseAgent(abc.ABC):
    agent_name: str

    @abc.abstractmethod
    async def run_ml_call(self, payload: dict) -> dict:
        """Calls the existing, unmodified service method for this module.
        Must offload any synchronous/CPU-bound service call via
        `asyncio.to_thread` -- these services are the same synchronous
        classes the HTTP endpoints already wrap with `run_in_threadpool`
        (app/api/v1/endpoints/*.py); this is the same reasoning applied
        outside a FastAPI request context, not a new pattern."""
        raise NotImplementedError

    async def handle_message(self, raw: bytes) -> None:
        """The handler passed to messaging.consumer.consume_forever."""
        event = AgentEvent.from_kafka_value(raw)
        settings = get_settings()

        async with AsyncSessionLocal() as session:
            repo = AgentExecutionRepository(session)
            execution = await repo.get_or_create(event.job_id, self.agent_name, event.event_id)

            if execution.status in (STATUS_COMPLETED, STATUS_FAILED):
                # Idempotent replay: FR-65's at-least-once delivery means a
                # message can be redelivered (e.g. a crash between handler
                # success and offset commit -- see messaging/consumer.py's
                # module docstring). This agent already reached a terminal
                # state for this (workflow, agent) pair; re-running the ML
                # call or re-publishing would double-count it downstream
                # (Phase 11's feedback_events/dashboard counts, in
                # particular). Nothing further to do.
                logger.info(
                    "agent_duplicate_event_skipped",
                    extra={
                        "job_id": str(event.job_id),
                        "agent": self.agent_name,
                        "existing_status": execution.status,
                    },
                )
                return

            result, error_type, error_message = await self._execute_with_retry(
                execution, event, repo, settings
            )

        if error_message is None:
            await publish_event(
                topics.completed_topic(self.agent_name),
                self._build_result_event(event, result or {}),
            )
        else:
            failed_event = self._build_result_event(event, {}, error_message=error_message)
            await publish_event(topics.failed_topic(self.agent_name), failed_event)
            await publish_event(topics.TOPIC_AGENT_FAILED, failed_event)
            await publish_dead_letter(
                topics.TOPIC_DEAD_LETTER,
                DeadLetterEnvelope(
                    original_event=event,
                    source_topic=topics.requested_topic(self.agent_name),
                    agent=self.agent_name,
                    failure_reason=error_message,
                    error_type=error_type or "transient",
                    retry_count=event.retry_count,
                    correlation_id=event.correlation_id,
                ),
            )

    async def _execute_with_retry(
        self, execution, event: AgentEvent, repo: AgentExecutionRepository, settings
    ) -> tuple[dict | None, str | None, str | None]:
        max_attempts = settings.AGENT_MAX_ATTEMPTS
        last_error_type = "transient"
        last_error_message = "unknown error"

        for attempt in range(1, max_attempts + 1):
            execution = await repo.mark_running(execution)
            start = time.perf_counter()
            log_extra = {
                "job_id": str(event.job_id),
                "event_id": str(event.event_id),
                "correlation_id": str(event.correlation_id),
                "agent": self.agent_name,
                "attempt": attempt,
            }
            logger.info("agent_execution_started", extra=log_extra)

            try:
                result = await self.run_ml_call(event.payload)
            except Exception as exc:  # noqa: BLE001 -- classified below, not swallowed
                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                error_type = classify_exception(exc)
                last_error_type, last_error_message = error_type, str(exc)
                logger.warning(
                    "agent_execution_failed",
                    exc_info=True,
                    extra={**log_extra, "duration_ms": duration_ms, "error_type": error_type},
                )

                is_last_attempt = attempt == max_attempts
                if error_type == PERMANENT or is_last_attempt:
                    execution = await repo.mark_failed(
                        execution, error_type, last_error_message, duration_ms=duration_ms
                    )
                    return None, error_type, last_error_message

                execution = await repo.mark_retrying(execution, last_error_message)
                backoff = compute_backoff_seconds(attempt, settings.AGENT_RETRY_BACKOFF_BASE_SECONDS)
                logger.info("agent_execution_retry_scheduled", extra={**log_extra, "backoff_seconds": backoff})
                # Deliberately blocks this one agent's consumer loop for the
                # backoff window, not the whole process -- see
                # app/agents/runner.py's module docstring for why each
                # agent runs its own asyncio task, so one agent backing off
                # doesn't stall the other five.
                await asyncio.sleep(backoff)
                continue
            else:
                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                model_version = result.get("model_version") if isinstance(result, dict) else None
                execution = await repo.mark_completed(execution, duration_ms, model_version=model_version)
                logger.info(
                    "agent_execution_completed",
                    extra={**log_extra, "duration_ms": duration_ms, "status": "COMPLETED"},
                )
                return result, None, None

        # Unreachable given the loop above always returns, kept only as an
        # explicit fallback rather than relying on implicit None-return.
        return None, last_error_type, last_error_message

    def _build_result_event(
        self, source_event: AgentEvent, result: dict, error_message: str | None = None
    ) -> AgentEvent:
        payload = {"result": result} if error_message is None else {"error": error_message}
        return AgentEvent(
            event_id=uuid.uuid4(),
            job_id=source_event.job_id,
            email_id=source_event.email_id,
            event_type=(
                topics.completed_topic(self.agent_name)
                if error_message is None
                else topics.failed_topic(self.agent_name)
            ),
            agent=self.agent_name,
            correlation_id=source_event.correlation_id,
            retry_count=source_event.retry_count,
            payload=payload,
            metadata=source_event.metadata,
        )
