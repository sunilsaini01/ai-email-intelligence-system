"""
Multi-agent workflow endpoints (Module 13 / Phase 12, FR-63).

`POST /email/process` is the new top-level trigger this codebase never
had before Phase 12 (PHASE_12_AUDIT_REPORT.md's headline finding: every
prior module was invoked independently by an external caller, nothing
chained them). It returns `job_id` immediately (202 Accepted) -- actual
processing happens asynchronously via the Orchestrator/agents
(app/agents/), matching PRD section 17's own suggested shape rather than
inventing a different one. `GET /workflows/{job_id}` is the durable status
read, backed by Postgres (workflow_executions/agent_executions), never
reconstructed from Kafka -- see app/models/workflow_execution.py's module
docstring.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependency import get_current_user
from app.database.repositories.agent_execution_repository import AgentExecutionRepository
from app.database.repositories.workflow_execution_repository import WorkflowExecutionRepository
from app.database.session import get_db
from app.models.user import User
from app.schemas.workflow import (
    AgentExecutionStatus,
    EmailProcessRequest,
    EmailProcessResponse,
    WorkflowStatusResponse,
)
from app.services.email_intake_service import EmailDispatchFailed, dispatch_email_for_processing

router = APIRouter(tags=["Multi-Agent Workflows"])


@router.post("/email/process", response_model=EmailProcessResponse, status_code=202)
async def process_email(
    request: EmailProcessRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EmailProcessResponse:
    try:
        workflow = await dispatch_email_for_processing(
            db,
            organization_id=current_user.organization_id,
            subject=request.subject,
            body=request.body,
            sender_email=request.sender_email,
        )
    except EmailDispatchFailed as e:
        raise HTTPException(status_code=503, detail="Could not dispatch email for processing.") from e

    return EmailProcessResponse(job_id=workflow.id, status=workflow.status)


@router.get("/workflows/{job_id}", response_model=WorkflowStatusResponse)
async def get_workflow_status(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowStatusResponse:
    workflow_repo = WorkflowExecutionRepository(db)
    workflow = await workflow_repo.get_by_id(current_user.organization_id, job_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    agent_repo = AgentExecutionRepository(db)
    executions = await agent_repo.list_for_workflow(job_id)

    return WorkflowStatusResponse(
        job_id=workflow.id,
        status=workflow.status,
        email_id=workflow.email_id,
        started_at=workflow.started_at,
        completed_at=workflow.completed_at,
        agents=[
            AgentExecutionStatus(
                agent_name=e.agent_name,
                status=e.status,
                attempt_count=e.attempt_count,
                duration_ms=e.duration_ms,
                error_type=e.error_type,
                error_message=e.error_message,
                model_version=e.model_version,
            )
            for e in executions
        ],
    )
