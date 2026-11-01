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

Why RS256 (asymmetric) since Phase 22: PRD SS6.4 names it, and the
PRD's own architecture (SS10.1) puts an API gateway doing "JWT Auth" in
front of the API -- a gateway should be able to VERIFY tokens with a
public key without holding the private key that can MINT them. Phase 17
shipped HS256 because no separate verifier existed yet; JWT_ALGORITHM=HS256
remains supported (signs with SECRET_KEY) for anyone relying on it.

Key sourcing (_jwt_keys): explicit PEMs from Settings win. Without them,
production refuses to start issuing tokens (fail fast, not silently
insecure); development/test generates a 2048-bit keypair once and
persists it under JWT_KEY_DIR so tokens survive a restart. Two API
replicas MUST share configured keys -- a per-replica generated key would
make each replica reject the other's tokens (k8s/secrets.example.yaml).
"""

import logging
import os
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from passlib.context import CryptContext

from app.core.config import get_settings

logger = logging.getLogger("app.security")

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TOKEN_TYPE_ACCESS = "access"  # noqa: S105 -- a JWT claim value, not a credential


_PRIVATE_KEY_FILE = "jwt_private.pem"


def _unescape_pem(value: str) -> str:
    return value.replace("\\n", "\n").strip() + "\n"


def _public_pem_for(private_pem: str) -> str:
    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()


def _generate_dev_keypair(key_dir: Path) -> tuple[str, str]:
    """Only the private key is stored; the public key is derived from it,
    so there is no window where one file exists without the other.

    Concurrency: several processes (two API replicas, the agents process)
    can start at once against the same shared directory. Each writes its
    own candidate to a temp file and hard-links it into place, which
    fails atomically if another process got there first -- the loser
    then reads the winner's key, so every process ends up signing and
    verifying with the same keypair."""
    private_path = key_dir / _PRIVATE_KEY_FILE
    if private_path.exists():
        private_pem = private_path.read_text(encoding="utf-8")
        return private_pem, _public_pem_for(private_pem)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    try:
        key_dir.mkdir(parents=True, exist_ok=True)
        candidate = key_dir / f".{_PRIVATE_KEY_FILE}.{os.getpid()}"
        candidate.write_text(private_pem, encoding="utf-8")
        try:
            os.link(candidate, private_path)
        except FileExistsError:
            private_pem = private_path.read_text(encoding="utf-8")
        finally:
            candidate.unlink(missing_ok=True)
        logger.warning("jwt_dev_keypair_in_use", extra={"key_dir": str(key_dir)})
    except OSError:
        # Unwritable directory: the keypair still works for this process,
        # but won't survive a restart or be shared with other replicas --
        # which is why production must configure JWT_PRIVATE_KEY/JWT_PUBLIC_KEY.
        logger.warning("jwt_dev_keypair_not_persisted", exc_info=True)
    return private_pem, _public_pem_for(private_pem)


@lru_cache
def _jwt_keys() -> tuple[str, str]:
    """(signing_key, verifying_key) for Settings.JWT_ALGORITHM."""
    settings = get_settings()
    if settings.JWT_ALGORITHM.upper().startswith("HS"):
        return settings.SECRET_KEY, settings.SECRET_KEY

    if settings.JWT_PRIVATE_KEY and settings.JWT_PUBLIC_KEY:
        return _unescape_pem(settings.JWT_PRIVATE_KEY), _unescape_pem(settings.JWT_PUBLIC_KEY)

    if settings.APP_ENV == "production":
        raise RuntimeError(
            "JWT_PRIVATE_KEY and JWT_PUBLIC_KEY must be configured for "
            f"{settings.JWT_ALGORITHM} in production."
        )
    return _generate_dev_keypair(Path(settings.JWT_KEY_DIR))


def sign_jwt(payload: dict) -> str:
    """Shared by access tokens (below) and the mailbox OAuth `state`
    parameter (app/ingestion/oauth_state.py) -- one key configuration,
    not two."""
    signing_key, _ = _jwt_keys()
    return jwt.encode(payload, signing_key, algorithm=get_settings().JWT_ALGORITHM)


def verify_jwt(token: str) -> dict:
    _, verifying_key = _jwt_keys()
    return jwt.decode(token, verifying_key, algorithms=[get_settings().JWT_ALGORITHM])


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
    return sign_jwt(payload)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError (expired, malformed, bad signature) on
    anything invalid -- the caller (get_current_user) is responsible for
    turning that into a 401, this function stays a pure decode step with
    no HTTP awareness, same separation-of-concerns app/services/ already
    keeps from app/api/."""
    payload = verify_jwt(token)
    if payload.get("type") != TOKEN_TYPE_ACCESS:
        raise jwt.InvalidTokenError("not an access token")
    return payload
