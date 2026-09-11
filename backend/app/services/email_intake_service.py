"""
Shared "hand this email to the multi-agent pipeline" logic.

Extracted out of app/api/v1/endpoints/workflows.py's original
`process_email` (Phase 12) so that a manual `POST /email/process` call
and the Phase 18 mailbox poller (app/agents/runner.py's
`_run_mailbox_poll`) dispatch through the exact same code -- two entry
points into one pipeline was already this codebase's stated design (see
README's "Architecture" section); this is that same principle applied one
layer down, so the two callers can't silently drift into two different
dispatch implementations.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.workflow_execution_repository import WorkflowExecutionRepository
from app.messaging import topics
from app.messaging.producer import publish_event
from app.messaging.schemas import AgentEvent
from app.models.workflow_execution import STATUS_FAILED, WorkflowExecution

logger = logging.getLogger("app.email_intake")


class EmailDispatchFailed(RuntimeError):
    """The workflow row was created in Postgres but publishing to Kafka
    failed. What a caller should do about it differs by caller -- the API
    endpoint returns a 503 to whoever called it; the poller (which has no
    caller to answer) logs it and simply leaves the source message
    un-advanced past its cursor, so the SAME message is retried on the
    next poll cycle instead of being silently dropped."""


async def dispatch_email_for_processing(
    db: AsyncSession,
    *,
    organization_id: str,
    subject: str,
    body: str,
    sender_email: str,
) -> WorkflowExecution:
    repo = WorkflowExecutionRepository(db)
    workflow = await repo.create(organization_id=organization_id)

    event = AgentEvent(
        job_id=workflow.id,
        email_id=workflow.id,  # no canonical email_id yet -- see app/agents/orchestrator.py's _dispatch docstring
        event_type=topics.TOPIC_EMAIL_PROCESSING_REQUESTED,
        correlation_id=workflow.id,
        payload={"subject": subject, "body": body, "sender_email": sender_email},
        metadata={"organization_id": organization_id},
    )
    try:
        await publish_event(topics.TOPIC_EMAIL_PROCESSING_REQUESTED, event)
    except Exception as e:
        logger.error("email_process_dispatch_failed", exc_info=True, extra={"job_id": str(workflow.id)})
        await repo.update_status(workflow, STATUS_FAILED, mark_completed=True)
        raise EmailDispatchFailed(str(e)) from e

    logger.info("email_process_dispatched", extra={"job_id": str(workflow.id)})
    return workflow
