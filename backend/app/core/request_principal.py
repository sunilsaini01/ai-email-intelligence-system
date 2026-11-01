"""
Who is making this request, as cheaply as possible -- for middleware that
runs before (and outside) FastAPI's dependency injection: the audit log
line (PRD SS6.4 "all data access ... logged with user ID + timestamp") and
the per-organization rate limiter (PRD SS13.1).

Verifies the JWT signature (an unverified `org` claim would let a caller
spend another organization's rate-limit budget) but never touches the
database -- get_current_user still does the authoritative is_active
check for the request itself. Results are cached per token string, so
the two middlewares decoding the same token cost one verification.
"""

from dataclasses import dataclass
from functools import lru_cache

from app.core.security import decode_access_token


@dataclass(frozen=True)
class RequestPrincipal:
    user_id: str | None
    organization_id: str | None


ANONYMOUS = RequestPrincipal(user_id=None, organization_id=None)


@lru_cache(maxsize=2048)
def _principal_for_token(token: str) -> RequestPrincipal:
    try:
        payload = decode_access_token(token)
    except Exception:
        return ANONYMOUS
    return RequestPrincipal(user_id=payload.get("sub"), organization_id=payload.get("org"))


def principal_from_headers(headers) -> RequestPrincipal:
    """`headers` is any mapping with .get() -- Starlette Headers or a dict
    built from an ASGI scope."""
    authorization = headers.get("authorization") or ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return ANONYMOUS
    principal = _principal_for_token(token.strip())
    # Expiry is re-checked by get_current_user; a cached principal for a
    # token that has since expired only affects log attribution and the
    # rate-limit bucket, never authorization.
    return principal
