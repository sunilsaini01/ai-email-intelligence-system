"""API contracts for registration/login (Phase 17, real authentication)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.user import ROLE_MEMBER
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, description="Minimum 8 characters -- no other complexity rule enforced; the PRD names none.")
    organization_id: str = Field(default=DEFAULT_ORGANIZATION_ID)


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


__all__ = ["RegisterRequest", "TokenResponse", "UserResponse", "ROLE_MEMBER"]
