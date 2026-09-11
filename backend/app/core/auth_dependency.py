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
from app.models.user import User

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
