"""
Known email domains used for metadata feature extraction.
"""

# Common free email providers
FREEMAIL_DOMAINS = frozenset({
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "protonmail.com",
    "icloud.com",
    "aol.com",
    "mail.com",
})


# Configure this according to your organization. "enron.com" is populated
# because it's the corpus backing the Phase 4 priority bootstrap dataset
# (docs/data_audit_priority.md) — a real fact about that dataset's sender
# domain, not a stand-in for a real deployment's internal domain list, which
# must be reconfigured per-organization before production use.
INTERNAL_DOMAINS: set[str] = {"enron.com"}