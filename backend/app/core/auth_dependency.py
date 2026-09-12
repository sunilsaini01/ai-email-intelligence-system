"""
`get_current_user` -- the FastAPI dependency that gates every protected
route (Phase 17, real authentication).

Why a DB round-trip on every request instead of trusting the JWT's own
`org`/`role` claims: a token stays valid for
Settings.ACCESS_TOKEN_EXPIRE_MINUTES (default 24h) after issuance. If an
account is deactivated (`is_active = False`) mid-session, trusting the
token's claims alone would let it keep working until it expires --
re-fetching the user confirms `is_active` on every request, closing that
window. The `org`/`role` claims on the token itself are still used
directly by callers that only need identity, not the extra query (see
app/core/security.py's own comment on why they're carried on the token
at all) -- this function is for routes that need the full, live User row.

Separate from Settings.API_VERSION string interpolation on purpose: this
is imported by app/main.py before create_app() has a request-scoped
`settings`, and the login path is a fixed contract regardless of
API_VERSION drifting -- matches how `docs_url`/`redoc_url` are also
hardcoded in app/main.py rather than derived from settings.
"""

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.database.session import get_db
from app.models.user import ROLE_ADMIN, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if token is None:
        raise _CREDENTIALS_EXCEPTION

    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise _CREDENTIALS_EXCEPTION from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXCEPTION
    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Phase 19 (role-based authorization). Layered ON TOP of
    get_current_user (a route depending on this still goes through the
    full is_active/token check above) rather than duplicating it -- same
    "depend on the narrower thing, don't re-implement it" reasoning
    app/api/v1/router.py's protected_router already established for
    get_current_user itself. Routes that mutate organization-wide
    configuration (connecting a mailbox, and Phase 20's routing-rules
    admin API) depend on this instead of get_current_user; routes that
    only read or that any signed-in user should be able to act on
    (submitting feedback, viewing the dashboard) keep depending on
    get_current_user alone."""
    if current_user.role != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires an organization admin.",
        )
    return current_user
