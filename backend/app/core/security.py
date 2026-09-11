"""
Password hashing + JWT issuance/verification (Phase 17, real authentication).

Why bcrypt via passlib, not a hand-rolled hash: bcrypt is deliberately
slow (adaptive cost factor) specifically to resist brute-force attacks
against a stolen password-hash table -- a plain sha256(password) hash
(fast by design) is the single most common real-world password-storage
mistake. passlib's CryptContext also handles algorithm migration for
free (verify() still accepts an old scheme's hash after the configured
scheme changes) -- not used yet, but the reason this project reaches for
passlib instead of calling `bcrypt` directly.

Why JWT, not server-side sessions: this API has no session store (no
Redis, no sticky-session requirement) and `api-deployment.yaml` already
runs 2 stateless replicas by design (FR-69, see that file's own
comment) -- a JWT is self-contained and verifiable by any replica
without a shared session backend, consistent with the stateless-service
architecture Phase 14 already committed to.

Why HS256 (symmetric), not RS256 (asymmetric): this API is both the
issuer and the only verifier of its own tokens -- no separate service
needs to verify a token without also being able to issue one, so an
asymmetric keypair buys nothing here. Revisit if a genuinely separate
verifying service (e.g. a gateway) is ever introduced.
"""

from datetime import UTC, datetime, timedelta

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TOKEN_TYPE_ACCESS = "access"  # noqa: S105 -- a JWT claim value, not a credential


def hash_password(plain_password: str) -> str:
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(*, subject: str, organization_id: str, role: str) -> str:
    """`subject` is the user's id (str(uuid)) -- the JWT `sub` claim,
    standard practice, not this project's own invention. organization_id
    and role are carried in the token itself so get_current_user (see
    app/core/auth_dependency.py) never needs a DB round-trip just to know
    which tenant a request belongs to -- the same "cheap, denormalized
    field on the token" tradeoff app/models/reply_draft.py's
    retrieved_email_ids comment already established for a different
    table, applied here to a token payload instead of a row."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "org": organization_id,
        "role": role,
        "type": TOKEN_TYPE_ACCESS,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError (expired, malformed, bad signature) on
    anything invalid -- the caller (get_current_user) is responsible for
    turning that into a 401, this function stays a pure decode step with
    no HTTP awareness, same separation-of-concerns app/services/ already
    keeps from app/api/."""
    settings = get_settings()
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("type") != TOKEN_TYPE_ACCESS:
        raise jwt.InvalidTokenError("not an access token")
    return payload
