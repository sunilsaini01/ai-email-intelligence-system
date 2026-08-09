"""
Embedding input construction (Module 9 / Phase 9, Step 7).

What gets embedded: `subject` then `body`, separated by a blank line --
not blindly concatenated with any other field. Never includes database
IDs, timestamps, or other technical metadata (Step 7's explicit warning) --
those are stored as vector-store METADATA (app/models/email_record.py,
ChromaVectorStore's `metadata` argument), not baked into the text a model
turns into semantic content.

Cleaning uses EmailPreprocessor(SUMMARY_CONFIG) -- the same "strip HTML,
signatures, quoted-reply blocks; otherwise preserve natural phrasing"
config Module 6 already uses, and for the same reason: a semantic
embedding (whether TF-IDF or a transformer) needs natural, meaning-bearing
text, not lemmatized/stopword-stripped tokens -- that's a decision
individual embedders make internally if they want it (TfidfEmbedder's own
`TfidfVectorizer(stop_words="english")`), not something baked into the
shared input text every embedder receives.

PII strategy (docs/phase9_pii_embedding_strategy.md, confirmed with the
project owner): the RAW subject/body is what gets stored in
`emails.subject`/`emails.body` (Postgres) -- unchanged from every other
module's current stance. Only the text that actually gets embedded (and
is therefore corpus-wide searchable, a materially different exposure
profile than a per-request audit log) is anonymized first, via the
existing (previously unused) `app/security/pii_anonymizer.py`.
"""

from app.preprocessing.email_preprocessor import SUMMARY_CONFIG, EmailPreprocessor
from app.security.pii_anonymizer import anonymize_email_body

_preprocessor = EmailPreprocessor(SUMMARY_CONFIG)


def build_embedding_text(subject: str, body: str) -> tuple[str, list[str]]:
    """Returns (anonymized_text_ready_to_embed, pii_entity_types_found).
    The entity-type list is for observability/audit only (e.g. "this
    record's embedding input contained an EMAIL_ADDRESS") -- never the
    anonymized text itself is discarded after use, and never the raw PII
    values (only entity TYPE names, e.g. "PERSON", never "John Smith")."""
    subject = subject or ""
    body = body or ""
    cleaned = _preprocessor.process(f"{subject}\n\n{body}".strip())
    anonymized_text, entity_types = anonymize_email_body(cleaned)
    return anonymized_text, entity_types
