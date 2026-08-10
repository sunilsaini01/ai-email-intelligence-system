"""Repository for workflow_executions (Module 13 / Phase 12, FR-63)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow_execution import STATUS_PENDING, WorkflowExecution


class WorkflowExecutionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, organization_id: str, email_id: uuid.UUID | None = None) -> WorkflowExecution:
        record = WorkflowExecution(organization_id=organization_id, email_id=email_id, status=STATUS_PENDING)
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_by_id(self, organization_id: str, job_id: uuid.UUID) -> WorkflowExecution | None:
        result = await self.session.execute(
            select(WorkflowExecution).where(
                WorkflowExecution.id == job_id, WorkflowExecution.organization_id == organization_id
            )
        )
        return result.scalar_one_or_none()

    async def update_status(
        self, workflow: WorkflowExecution, status: str, mark_completed: bool = False
    ) -> WorkflowExecution:
        workflow.status = status
        if mark_completed:
            workflow.completed_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(workflow)
        return workflow
