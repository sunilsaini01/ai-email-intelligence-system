"""API contracts for the mailbox connect/callback/list/disconnect endpoints (Phase 18)."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class MailboxConnectResponse(BaseModel):
    authorization_url: str


class MailboxConnectionResponse(BaseModel):
    id: uuid.UUID
    provider: str
    email_address: str
    status: str
    last_synced_at: datetime | None
    last_error: str | None
    created_at: datetime


class MailboxConnectionListResponse(BaseModel):
    connections: list[MailboxConnectionResponse]
