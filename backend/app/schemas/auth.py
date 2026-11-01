"""API contracts for registration/login (Phase 17, real authentication)
and organization membership (invitations)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import ROLE_AGENT, USER_ROLES

_PASSWORD = Field(..., min_length=8, description="Minimum 8 characters -- no other complexity rule enforced; the PRD names none.")


class RegisterRequest(BaseModel):
    """Creates a NEW organization with the caller as its admin.

    `extra="forbid"`: older clients sent `organization_id` to join an
    existing organization. That is exactly the hole this contract closes,
    so such a request is rejected with 422 instead of being silently
    ignored (and quietly creating a different organization than the
    caller expected). Joining an existing organization goes through
    POST /auth/invitations/accept."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = _PASSWORD
    organization_name: str = Field(..., min_length=1, max_length=200)


class AcceptInvitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=16, max_length=200)
    email: EmailStr = Field(description="Must be the address the invitation was issued to.")
    password: str = _PASSWORD


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    organization_id: str
    role: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 -- an OAuth2 field name, not a credential


class InvitationCreateRequest(BaseModel):
    # The organization is always the inviting admin's own; an
    # `organization_id` field is rejected rather than ignored.
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: str = Field(default=ROLE_AGENT, description=f"One of {USER_ROLES}.")
    expires_in_hours: int = Field(default=72, ge=1, le=24 * 30)


class InvitationResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    status: str  # pending | accepted | expired | revoked
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None


class InvitationCreatedResponse(InvitationResponse):
    """The only response that ever contains the token. It is not stored
    and cannot be retrieved again -- hand it to the invitee directly (no
    email is sent by this system)."""

    token: str
    accept_path: str


class InvitationListResponse(BaseModel):
    invitations: list[InvitationResponse]


__all__ = [
    "AcceptInvitationRequest",
    "InvitationCreateRequest",
    "InvitationCreatedResponse",
    "InvitationListResponse",
    "InvitationResponse",
    "RegisterRequest",
    "TokenResponse",
    "UserResponse",
]
