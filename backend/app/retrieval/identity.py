"""
Canonical email identity (Module 9 / Phase 9, Step 3).

No reliable Message-ID exists anywhere in this system today -- nothing in
Phases 1-8 parses or persists real email headers; every module's input is
a bare {subject, body} pair via an API call. `message_id` is kept as an
optional field on the `emails` table for a future real-ingestion path
(app/models/email_record.py), but the identity this module actually
computes and uses for deduplication is a content hash -- the only thing
reliably computable from what this system actually has today.

See docs/email_identity_and_deduplication.md for the full design record
(why content-hash, not Message-ID; how idempotent re-indexing works; what
happens on same-content-different-Message-ID and vice versa).
"""

import hashlib
import re


def compute_content_hash(subject: str, body: str) -> str:
    """
    Deterministic identity for (subject, body) within one organization.
    Normalizes whitespace and case before hashing so cosmetic differences
    (extra spaces, a re-wrapped line, different capitalization) don't
    silently create a duplicate record for what's actually the same email
    -- the same normalization philosophy
    app/routing/keyword_matcher.py's `_normalize()` already uses, applied
    here to identity instead of keyword matching.

    NOT a security/cryptographic use of SHA-256 -- collision resistance
    isn't the goal, a stable, well-distributed identity is.
    """
    normalized = re.sub(r"\s+", " ", f"{subject}\n{body}".strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
