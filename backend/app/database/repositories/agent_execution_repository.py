"""
Repository for agent_executions (Module 13 / Phase 12, FR-63/FR-66/FR-67).

`get_or_create` is the idempotency primitive every agent's handler calls
first (see app/agents/base.py): check-then-insert against the
`(workflow_id, agent_name)` unique constraint, same shape Phase 11's
Review Queue duplicate-confirm guard already uses
(docs/error_analysis_dashboard.md #3) -- a disclosed, narrow race window
(two concurrent get_or_create calls for a brand-new row can both pass the
SELECT before either commits), not a claimed-airtight atomic guarantee,
consistent with how that prior instance was disclosed rather than
overstated.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_execution import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RETRYING,
    STATUS_RUNNING,
    AgentExecution,
)


class AgentExecutionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, workflow_id: uuid.UUID, agent_name: str) -> AgentExecution | None:
        result = await self.session.execute(
            select(AgentExecution).where(
                AgentExecution.workflow_id == workflow_id, AgentExecution.agent_name == agent_name
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self, workflow_id: uuid.UUID, agent_name: str, event_id: uuid.UUID
    ) -> AgentExecution:
        existing = await self.get(workflow_id, agent_name)
        if existing is not None:
            return existing

        record = AgentExecution(
            workflow_id=workflow_id, agent_name=agent_name, event_id=event_id, status=STATUS_PENDING
        )
        self.session.add(record)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.get(workflow_id, agent_name)
            if existing is None:
                raise  # a genuinely different failure, not the race this guards against
            return existing
        await self.session.refresh(record)
        return record

    async def mark_running(self, execution: AgentExecution) -> AgentExecution:
        execution.status = STATUS_RUNNING
        execution.started_at = execution.started_at or datetime.now(UTC)
        execution.attempt_count += 1
        await self.session.commit()
        await self.session.refresh(execution)
        return execution

    async def mark_retrying(self, execution: AgentExecution, error_message: str) -> AgentExecution:
        execution.status = STATUS_RETRYING
        execution.error_type = "transient"
        execution.error_message = error_message
        await self.session.commit()
        await self.session.refresh(execution)
        return execution

    async def mark_completed(
        self, execution: AgentExecution, duration_ms: float, model_version: str | None = None
    ) -> AgentExecution:
        execution.status = STATUS_COMPLETED
        execution.completed_at = datetime.now(UTC)
        execution.duration_ms = duration_ms
        execution.model_version = model_version
        execution.error_type = None
        execution.error_message = None
        await self.session.commit()
        await self.session.refresh(execution)
        return execution

    async def mark_failed(
        self, execution: AgentExecution, error_type: str, error_message: str, duration_ms: float | None = None
    ) -> AgentExecution:
        execution.status = STATUS_FAILED
        execution.completed_at = datetime.now(UTC)
        execution.error_type = error_type
        execution.error_message = error_message
        if duration_ms is not None:
            execution.duration_ms = duration_ms
        await self.session.commit()
        await self.session.refresh(execution)
        return execution

    async def list_for_workflow(self, workflow_id: uuid.UUID) -> list[AgentExecution]:
        result = await self.session.execute(
            select(AgentExecution).where(AgentExecution.workflow_id == workflow_id)
        )
        return list(result.scalars().all())
