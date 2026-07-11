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


# Configure this according to your organization.
# Leave empty for now.
INTERNAL_DOMAINS: set[str] = set()