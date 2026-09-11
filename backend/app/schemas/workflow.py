"""
API contracts for the multi-agent workflow surface (Module 13 / Phase 12,
FR-63). Additive: every pre-existing `*/predict` endpoint contract is
unchanged (PRD section 17's explicit backward-compatibility requirement).

`EmailProcessRequest` no longer accepts `organization_id` from the caller
(Phase 17, real authentication) -- a caller-supplied value here would let
any authenticated user read/write into an org they don't belong to, just
by sending a different string. It's derived from the authenticated
user's own token instead; see app/api/v1/endpoints/workflows.py.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class EmailProcessRequest(BaseModel):
    subject: str = Field(default="", description="Raw email subject line.")
    body: str = Field(..., description="Raw email body.")
    sender_email: str = Field(default="")


class EmailProcessResponse(BaseModel):
    job_id: uuid.UUID
    status: str


class AgentExecutionStatus(BaseModel):
    agent_name: str
    status: str
    attempt_count: int
    duration_ms: float | None
    error_type: str | None
    error_message: str | None
    model_version: str | None


class WorkflowStatusResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    email_id: uuid.UUID | None
    started_at: datetime
    completed_at: datetime | None
    agents: list[AgentExecutionStatus]
