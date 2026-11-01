"""API contracts for the mailbox connect/callback/list/disconnect endpoints (Phase 18)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ImapConnectRequest(BaseModel):
    host: str = Field(..., min_length=1, max_length=255, description="IMAP server hostname, e.g. imap.fastmail.com.")
    port: int = Field(default=993, ge=1, le=65535, description="IMAP over TLS port (plaintext IMAP is not supported).")
    username: str = Field(..., min_length=1, max_length=320)
    password: str = Field(..., min_length=1, description="Use an app-specific password where the provider offers one.")


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
