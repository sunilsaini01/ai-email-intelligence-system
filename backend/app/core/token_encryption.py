"""
Symmetric encryption for mailbox OAuth tokens at rest (Phase 18, FR-01/
FR-02). A stolen `mailbox_connections` row (DB backup, misconfigured
replica, etc.) must not hand an attacker a live Gmail/Outlook refresh
token -- the same "encrypt the credential, not just the transport"
reasoning app/core/security.py already applies to login passwords via
bcrypt, applied here to a different kind of long-lived secret.

Why Fernet (`cryptography`), not a hand-rolled AES call: Fernet bundles
authenticated encryption (AES-128-CBC + HMAC) with a fixed, versioned
token format -- exactly the "don't build bespoke crypto" stance this
codebase already took choosing bcrypt over a hand-rolled hash. `cryptography`
is a new dependency (see requirements.txt), justified by there being no
existing dependency in this project that already provides authenticated
symmetric encryption.

Why derive the Fernet key from MAILBOX_TOKEN_ENCRYPTION_KEY via SHA-256
instead of requiring an already-base64 32-byte key: Settings.SECRET_KEY
and every other secret in this codebase's .env.example is an arbitrary
string (`secrets.token_urlsafe(32)`, but not required to be), not
specifically Fernet's own base64url-encoded-32-bytes format. Hashing
first accepts any non-empty string as the configured secret while still
producing a valid Fernet key, at the cost of the operator's configured
secret only ever landing in this file, never directly in Fernet's API.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class TokenDecryptionError(RuntimeError):
    """Raised when a stored token cannot be decrypted -- wrong/rotated
    MAILBOX_TOKEN_ENCRYPTION_KEY, or corrupted data. Callers should treat
    this the same as "connection needs to be reconnected", never crash the
    poll loop for every OTHER connection over one bad row."""


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    digest = hashlib.sha256(settings.MAILBOX_TOKEN_ENCRYPTION_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_token(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        raise TokenDecryptionError("Stored mailbox token could not be decrypted.") from e
