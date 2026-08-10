"""
Orchestrator Agent (Module 13 / Phase 12, FR-63).

Single long-lived Kafka consumer (see app/agents/runner.py) subscribed to
`email.processing.requested` plus every module's `*.completed`/`*.failed`
topic. Tracks in-memory, per-`job_id` state for workflows currently in
flight (`_pending`) and advances each one as agent results arrive --
`workflow_executions`/`agent_executions` in Postgres remain the durable
source of truth (PHASE_12_AUDIT_REPORT.md section 6.1); `_pending` is a
process-local index into "which workflows am I still waiting on," lost on
restart, same disclosed single-process limitation Phase 11's
DashboardBroadcaster already carries (docs/dashboard_performance.md) --
not a new kind of gap this phase introduces.

Dependency graph (PHASE_12_AUDIT_REPORT.md section 13):
  - Spam and Summarization dispatch immediately, in parallel, no
    dependencies on anything.
  - R-SPAM-GATE: once Spam resolves, Priority/Category/Sentiment/Intent
    are dispatched ONLY if `is_spam` is not True -- mirrors
    RoutingService.route()'s own existing gate
    (`if not is_spam:` around those same four calls) exactly, so this
    doesn't silently regress an already-shipped optimization. A FAILED/
    unavailable spam result is treated the same way RoutingService
    already treats it: `is_spam` is `None`, which is falsy, so the gate
    stays open (fail-open toward more processing, not less) -- the exact
    same semantics, not a new policy invented for Kafka.
  - Once every dispatched module has reported (completed or failed),
    Routing's resolve_routing() runs in-process via
    RoutingService.route()'s new precomputed_* kwargs (see
    app/services/routing_service.py) -- REUSING the already-computed
    agent results, never re-running the five ML calls a second time.
  - Retrieval indexing runs in-process afterward, mirroring
    app/api/v1/endpoints/retrieval.py's own index_email sequence (the
    same "each orchestration point keeps its own short, mirrored
    sequence rather than a forced shared abstraction" precedent
    app/api/v1/endpoints/reply.py's `_fetch_resolved_context` already
    established for its own retrieval-adjacent logic).

Why Auto-Reply Is Not Included:
    AutoReplyService.generate() makes a real, billed Groq API call
    (docs/architecture_auto_reply.md). Auto-triggering it for every
    processed email would silently turn Phase 12 into an uncontrolled
    increase in real API spend and external-service dependency -- not a
    FR-63-67 requirement, and not something to do without being asked.
    Auto-Reply remains a separate, explicit action via its existing
    `/reply/generate` endpoint. See PHASE_12_AUDIT_REPORT.md section 6 and
    docs/architecture_multi_agent.md "Scope Boundary".

Known, disclosed limitation: there is no per-workflow timeout that force-
finalizes a workflow whose expected agent(s) never report at all (as
opposed to reporting *.failed, which DOES finalize normally -- see
FR-66's retry/DLQ path). A workflow in that state stays RUNNING
indefinitely in this implementation. A real fix needs a scheduled sweep
job this codebase has no scheduler for yet (same class of gap Phase 11's
"no scheduled report generation" already disclosed) -- documented here
rather than silently left unmentioned. See docs/failure_handling.md.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.database.repositories.email_repository import EmailRepository
from app.database.repositories.workflow_execution_repository import WorkflowExecutionRepository
from app.database.session import AsyncSessionLocal
from app.messaging import topics
from app.messaging.producer import publish_event
from app.messaging.schemas import AgentEvent
from app.models.workflow_execution import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_PENDING,
    STATUS_RUNNING,
)
from app.retrieval.identity import compute_content_hash
from app.services.retrieval_service import get_retrieval_service
from app.services.routing_service import get_routing_service

logger = logging.getLogger("app.agents.orchestrator")

GATED_MODULES = ("priority", "category", "sentiment", "intent")
UNGATED_MODULES = ("summarization",)


@dataclass
class WorkflowTracker:
    organization_id: str
    subject: str
    body: str
    sender_email: str
    correlation_id: uuid.UUID
    expected: set[str] = field(default_factory=lambda: {"spam", "summarization"})
    results: dict[str, dict | None] = field(default_factory=dict)
    gate_resolved: bool = False


class Orchestrator:
    consumer_group = "orchestrator"

    def __init__(self) -> None:
        self._pending: dict[uuid.UUID, WorkflowTracker] = {}

    def consumer_topics(self) -> list[str]:
        topics_list = [topics.TOPIC_EMAIL_PROCESSING_REQUESTED]
        for module in topics.AGENT_MODULES:
            topics_list += [topics.completed_topic(module), topics.failed_topic(module)]
        return topics_list

    async def handle_message(self, raw: bytes) -> None:
        event = AgentEvent.from_kafka_value(raw)

        if event.event_type == topics.TOPIC_EMAIL_PROCESSING_REQUESTED:
            await self._start_workflow(event)
            return

        module = self._module_from_event_type(event.event_type)
        if module is None:
            logger.warning("orchestrator_unrecognized_event_type", extra={"event_type": event.event_type})
            return

        tracker = self._pending.get(event.job_id)
        if tracker is None:
            # Either this job_id was already finalized (a duplicate/late
            # message under at-least-once delivery -- see
            # messaging/consumer.py) or the orchestrator restarted and lost
            # its in-memory tracker (the disclosed limitation in this
            # module's docstring). Either way there's nothing safe to do
            # but drop it -- workflow_executions/agent_executions in
            # Postgres remain the durable record regardless.
            logger.info(
                "orchestrator_result_for_unknown_workflow",
                # "agent_name", not "module" -- `module` is a reserved
                # stdlib LogRecord attribute (auto-populated with the
                # calling module's name); passing it via `extra` raises
                # `KeyError: "Attempt to overwrite 'module' in LogRecord"`
                # at the FIRST call site that hit this path, a real bug
                # found via this phase's own real-Kafka integration test
                # (see docs/testing_strategy_phase12.md).
                extra={"job_id": str(event.job_id), "agent_name": module},
            )
            return

        succeeded = event.event_type == topics.completed_topic(module)
        tracker.results[module] = event.payload.get("result") if succeeded else None

        if module == "spam" and not tracker.gate_resolved:
            await self._resolve_gate(event.job_id, tracker)

        if tracker.gate_resolved and set(tracker.results.keys()) >= tracker.expected:
            await self._finalize_workflow(event.job_id, tracker)

    @staticmethod
    def _module_from_event_type(event_type: str) -> str | None:
        for module in topics.AGENT_MODULES:
            if event_type in (topics.completed_topic(module), topics.failed_topic(module)):
                return module
        return None

    async def _start_workflow(self, event: AgentEvent) -> None:
        organization_id = event.metadata.get("organization_id", "default")

        async with AsyncSessionLocal() as session:
            repo = WorkflowExecutionRepository(session)
            workflow = await repo.get_by_id(organization_id, event.job_id)
            if workflow is None:
                logger.warning(
                    "orchestrator_start_workflow_row_missing", extra={"job_id": str(event.job_id)}
                )
                return
            if workflow.status != STATUS_PENDING:
                # Idempotency guard (a real bug found via code review, not
                # caught by the E2E test, which never exercises redelivery
                # of THIS specific topic): email.processing.requested can
                # be redelivered under FR-65's at-least-once semantics
                # (e.g. the Orchestrator crashes after dispatching agents
                # but before its consumer offset commits). Without this
                # check, a redelivery would overwrite `_pending[job_id]`
                # with a brand-new tracker and re-dispatch spam/
                # summarization -- at best wasted duplicate work (absorbed
                # by the specialist agents' own idempotency check, which
                # then does NOT re-publish *.completed for an already-
                # terminal execution), at worst silently resetting an
                # ALREADY-COMPLETED workflow's status back to RUNNING with
                # no way to ever re-finalize it, since the new tracker
                # never receives the completions it's waiting for. See
                # docs/failure_handling.md.
                logger.info(
                    "orchestrator_duplicate_start_skipped",
                    extra={"job_id": str(event.job_id), "status": workflow.status},
                )
                return
            await repo.update_status(workflow, STATUS_RUNNING)

        tracker = WorkflowTracker(
            organization_id=organization_id,
            subject=event.payload.get("subject", ""),
            body=event.payload.get("body", ""),
            sender_email=event.payload.get("sender_email", ""),
            correlation_id=event.correlation_id,
        )
        self._pending[event.job_id] = tracker

        for module in ("spam", *UNGATED_MODULES):
            await self._dispatch(event.job_id, tracker, module)

    async def _resolve_gate(self, job_id: uuid.UUID, tracker: WorkflowTracker) -> None:
        spam_result = tracker.results.get("spam")
        is_spam = spam_result["is_spam"] if spam_result else None
        tracker.gate_resolved = True
        if not is_spam:
            tracker.expected |= set(GATED_MODULES)
            for module in GATED_MODULES:
                await self._dispatch(job_id, tracker, module)

    async def _dispatch(self, job_id: uuid.UUID, tracker: WorkflowTracker, module: str) -> None:
        event = AgentEvent(
            job_id=job_id,
            email_id=job_id,  # no canonical email_id exists yet at dispatch time -- assigned at indexing (see _finalize_workflow); job_id is a stable, unique key for THIS workflow's Kafka partitioning in the meantime.
            event_type=topics.requested_topic(module),
            correlation_id=tracker.correlation_id,
            payload={"subject": tracker.subject, "body": tracker.body, "sender_email": tracker.sender_email},
            metadata={"organization_id": tracker.organization_id},
        )
        await publish_event(topics.requested_topic(module), event)
        # "agent_name", not "module" -- see the identical fix/comment above
        # in handle_message; `module` is a reserved stdlib LogRecord
        # attribute.
        logger.info("orchestrator_dispatched", extra={"job_id": str(job_id), "agent_name": module})

    async def _finalize_workflow(self, job_id: uuid.UUID, tracker: WorkflowTracker) -> None:
        del self._pending[job_id]

        routing_service = get_routing_service()
        decision = await asyncio.to_thread(
            routing_service.route,
            tracker.subject,
            tracker.body,
            tracker.sender_email,
            precomputed_spam=tracker.results.get("spam"),
            precomputed_category=tracker.results.get("category"),
            precomputed_intent=tracker.results.get("intent"),
            precomputed_sentiment=tracker.results.get("sentiment"),
            precomputed_priority=tracker.results.get("priority"),
        )
        category = (decision.get("supporting_signals", {}).get("category") or {}).get("top")
        department = decision.get("department")
        priority_result = tracker.results.get("priority")
        priority_label = priority_result.get("priority") if priority_result else None

        any_dispatched_failure = any(v is None for v in tracker.results.values())

        async with AsyncSessionLocal() as session:
            email_repo = EmailRepository(session)
            content_hash = compute_content_hash(tracker.subject, tracker.body)
            index_failed = False
            record = None
            try:
                record, _was_created = await email_repo.upsert_by_content_hash(
                    organization_id=tracker.organization_id,
                    content_hash=content_hash,
                    subject=tracker.subject,
                    body=tracker.body,
                    sender_email=tracker.sender_email,
                    received_at=datetime.now(UTC),
                    category=category,
                    department=department,
                    priority=priority_label,
                )
                retrieval_service = get_retrieval_service()
                index_result = await asyncio.to_thread(
                    retrieval_service.index_email,
                    content_hash=content_hash,
                    subject=tracker.subject,
                    body=tracker.body,
                    category=category,
                    department=department,
                    organization_id=tracker.organization_id,
                )
                record = await email_repo.mark_indexed(
                    record,
                    embedding_model=index_result["embedding_model"],
                    embedding_version=index_result["collection"],
                    vector_collection=index_result["collection"],
                )
            except Exception:
                logger.error("orchestrator_indexing_failed", exc_info=True, extra={"job_id": str(job_id)})
                index_failed = True
                if record is not None:
                    await email_repo.mark_failed(record)

            workflow_repo = WorkflowExecutionRepository(session)
            workflow = await workflow_repo.get_by_id(tracker.organization_id, job_id)
            if workflow is not None:
                if index_failed:
                    status = STATUS_FAILED
                elif any_dispatched_failure:
                    status = STATUS_PARTIAL
                else:
                    status = STATUS_COMPLETED
                if record is not None:
                    workflow.email_id = record.id
                await workflow_repo.update_status(workflow, status, mark_completed=True)

        logger.info(
            "orchestrator_workflow_finalized",
            extra={
                "job_id": str(job_id),
                "department": department,
                "index_failed": index_failed,
                "any_dispatched_failure": any_dispatched_failure,
            },
        )

        await publish_event(
            topics.TOPIC_WORKFLOW_COMPLETED,
            AgentEvent(
                job_id=job_id,
                email_id=record.id if record is not None else job_id,
                event_type=topics.TOPIC_WORKFLOW_COMPLETED,
                correlation_id=tracker.correlation_id,
                payload={"decision": decision, "index_failed": index_failed},
                metadata={"organization_id": tracker.organization_id},
            ),
        )
