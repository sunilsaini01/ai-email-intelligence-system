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
from app.core.security import create_access_token, hash_password, verify_password
from app.database.repositories.user_repository import UserRepository
from app.database.session import get_db
from app.models.user import ROLE_ADMIN, ROLE_MEMBER, User
from app.schemas.auth import RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger("app.auth")


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, db: AsyncSession = Depends(get_db)) -> UserResponse:
    repo = UserRepository(db)
    if await repo.get_by_email(request.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")

    # Phase 19 (role-based authorization): the FIRST account registered for
    # an organization becomes its admin -- there is no admin yet to
    # promote anyone, so bootstrapping has to happen somewhere. Every
    # later registration for that same organization defaults to member
    # (UserRepository.create's own default). Two concurrent registrations
    # against a brand-new organization_id could both read count=0 and both
    # become admin -- a disclosed, accepted race: the outcome is "two
    # admins" for that org, not a privilege-escalation bug, so this isn't
    # worth a DB-level lock for.
    is_first_user_in_org = await repo.count_for_organization(request.organization_id) == 0
    user = await repo.create(
        email=request.email,
        hashed_password=hash_password(request.password),
        organization_id=request.organization_id,
        role=ROLE_ADMIN if is_first_user_in_org else ROLE_MEMBER,
    )
    logger.info("user_registered", extra={"user_id": str(user.id), "organization_id": user.organization_id})
    return UserResponse(
        id=user.id,
        email=user.email,
        organization_id=user.organization_id,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )


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
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        organization_id=current_user.organization_id,
        role=current_user.role,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
    )
