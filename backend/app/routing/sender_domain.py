"""
Sender-domain classification for routing (FR-38's "sender domain" signal).

Reuses app/feature_engineering/domains.py's FREEMAIL_DOMAINS/INTERNAL_DOMAINS
rather than defining a second set -- those are already the codebase's one
source of truth for domain classification (used today by Priority/Category's
metadata features).

Deliberately informational only, per Phase 8's brief SS26: "treat sender
information as untrusted input... do not make security decisions based
solely on a sender domain." classify_sender_domain() never selects a
department and never gates auto-routing by itself -- it only ever appears in
a decision's supporting_signals for explainability. See
docs/routing_signal_reliability.md.
"""

from app.feature_engineering.domains import FREEMAIL_DOMAINS, INTERNAL_DOMAINS

UNKNOWN = "unknown"
INTERNAL = "internal"
FREEMAIL = "freemail"
EXTERNAL = "external"


def extract_domain(sender_email: str) -> str | None:
    """Lowercased domain part of an email address, or None if malformed/absent.

    Deliberately permissive (not RFC 5321 validation) -- routing only needs
    "is there a domain-looking substring after an @", not full address
    validity. Malformed input (no "@", empty, multiple "@") returns None
    rather than raising, consistent with SS30's "never let malformed sender
    crash routing."
    """
    if not sender_email or "@" not in sender_email:
        return None
    local, _, domain = sender_email.rpartition("@")
    domain = domain.strip().lower()
    if not local.strip() or not domain or "." not in domain:
        return None
    return domain


def classify_sender_domain(sender_email: str | None) -> str:
    """internal | freemail | external | unknown -- see module docstring for
    why this is informational-only, never a routing decision by itself."""
    if not sender_email:
        return UNKNOWN
    domain = extract_domain(sender_email)
    if domain is None:
        return UNKNOWN
    if domain in INTERNAL_DOMAINS:
        return INTERNAL
    if domain in FREEMAIL_DOMAINS:
        return FREEMAIL
    return EXTERNAL
