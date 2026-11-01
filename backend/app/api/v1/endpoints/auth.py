"""
Registration/login endpoints (Phase 17, real authentication).

Login accepts OAuth2's standard form-encoded `username`/`password`
fields (via OAuth2PasswordRequestForm), not a JSON body -- this is what
makes FastAPI's own Swagger UI "Authorize" button work against this
endpoint with zero extra configuration, the standard reason every
FastAPI auth tutorial does it this way. `username` holds the user's
email; there is no separate username concept in this project.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependency import get_current_user
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.database.repositories.user_repository import UserRepository
from app.database.session import get_db
from app.models.user import User
from app.schemas.auth import AcceptInvitationRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.membership_service import (
    EmailAlreadyRegistered,
    InvalidInvitation,
    accept_invitation,
    create_organization_with_admin,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger("app.auth")


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, db: AsyncSession = Depends(get_db)) -> UserResponse:
    """Creates a NEW organization (server-generated ID) with the caller as
    its admin, atomically. This used to take a caller-chosen
    `organization_id` and drop the new account into it -- anyone could
    join any existing organization, and the first account to name a fresh
    ID became its admin by a user count. Joining an existing organization
    now requires an admin's invitation (POST /auth/invitations/accept)."""
    if not get_settings().ALLOW_PUBLIC_ORGANIZATION_SIGNUP:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Public sign-up is disabled; ask an admin for an invitation.")
    try:
        _, user = await create_organization_with_admin(
            db, request.organization_name, request.email, hash_password(request.password)
        )
    except EmailAlreadyRegistered as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.") from exc
    logger.info("user_registered", extra={"user_id": str(user.id), "organization_id": user.organization_id})
    return _user_response(user)


@router.post("/invitations/accept", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def accept_organization_invitation(
    request: AcceptInvitationRequest, db: AsyncSession = Depends(get_db)
) -> UserResponse:
    """Creates the invited account in the inviting organization with the
    invited role. One generic 400 for every invalid-invitation reason --
    see app/services/membership_service.py InvalidInvitation."""
    try:
        user = await accept_invitation(db, request.token, request.email, hash_password(request.password))
    except InvalidInvitation as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation is invalid, expired, already used, or was issued to a different email.",
        ) from exc
    except EmailAlreadyRegistered as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.") from exc
    return _user_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    repo = UserRepository(db)
    user = await repo.get_by_email(form_data.username)

    # Deliberately the SAME error for "no such user" and "wrong password"
    # -- distinguishing them lets an attacker enumerate valid emails one
    # request at a time. Not a hypothetical: this is OWASP's own named
    # authentication-failure disclosure pitfall.
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise invalid_credentials
    if not user.is_active:
        raise invalid_credentials

    token = create_access_token(subject=str(user.id), organization_id=user.organization_id, role=user.role)
    logger.info("user_logged_in", extra={"user_id": str(user.id)})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return _user_response(current_user)


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        organization_id=user.organization_id,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )
