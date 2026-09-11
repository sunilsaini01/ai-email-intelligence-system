"""
Signed OAuth `state` parameter for the mailbox connect flow (Phase 18).

Why this exists at all: the OAuth callback (`GET /mailbox/{provider}/callback`)
is hit by the user's BROWSER being redirected by Google/Microsoft, not by
an API client presenting a Bearer token -- there is no Authorization
header to run through get_current_user (app/core/auth_dependency.py) on
that request. `state` is the one value both providers guarantee to round-
trip back completely unmodified, so it is used to carry a signed claim of
WHO initiated the connection (and for which organization), verified at the
callback -- this is standard OAuth CSRF-protection use of `state`, extended
here to also carry identity instead of just a random nonce, since this
project has no server-side session store to look a nonce up against.

Deliberately NOT reusing app/core/security.py's create_access_token/
decode_access_token: those are the login-session token contract (`type:
"access"`, ACCESS_TOKEN_EXPIRE_MINUTES-long lived). Mixing this short-
lived, single-purpose state token into that same function would make it
possible to accidentally accept one in place of the other wherever `type`
isn't re-checked. A distinct `type` claim and a short, fixed expiry
(mailbox connect flows complete in seconds, not hours) keep the two
contracts from ever being confused.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import get_settings

TOKEN_TYPE_MAILBOX_OAUTH_STATE = "mailbox_oauth_state"  # noqa: S105 -- a JWT claim value, not a credential
STATE_EXPIRE_MINUTES = 10


class InvalidOAuthState(RuntimeError):
    """The `state` parameter Google/Microsoft echoed back could not be
    verified -- expired, tampered with, or was never issued by this app."""


def build_state(*, organization_id: str, user_id: uuid.UUID, provider: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "org": organization_id,
        "user_id": str(user_id),
        "provider": provider,
        "type": TOKEN_TYPE_MAILBOX_OAUTH_STATE,
        "iat": now,
        "exp": now + timedelta(minutes=STATE_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_state(token: str, *, expected_provider: str) -> tuple[str, uuid.UUID]:
    """Returns (organization_id, user_id). Raises InvalidOAuthState on any
    failure -- expired, wrong provider (a state minted for /gmail/callback
    presented to /outlook/callback), or malformed."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != TOKEN_TYPE_MAILBOX_OAUTH_STATE:
            raise InvalidOAuthState("state token is not a mailbox OAuth state token.")
        if payload.get("provider") != expected_provider:
            raise InvalidOAuthState("state token was issued for a different provider.")
        return payload["org"], uuid.UUID(payload["user_id"])
    except (jwt.PyJWTError, KeyError, ValueError) as e:
        raise InvalidOAuthState(f"Could not verify OAuth state: {e}") from e
