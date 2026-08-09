# PII & Embedding Strategy (Module 9 / Phase 9, Step 6)

## The Options Considered

| Option | Description |
|---|---|
| A | Embed raw email body |
| B | Embed PII-scrubbed email body |
| C | Embed subject + body (raw) |
| D | Embed a structured representation |
| E | Embedding only + database reference (no text re-derivable from the vector) |

## Decision: B, With Raw Text Kept Separately in Postgres

Confirmed with the project owner before implementation: **only the text
that gets embedded is PII-scrubbed; the raw `subject`/`body` stored in
Postgres (`emails.subject`/`emails.body`) is unchanged from every other
module's current stance (no anonymization applied to what's persisted as
the canonical record).**

### Why This Split, Not "Anonymize Everything" or "Anonymize Nothing"

- **Every other module in this codebase currently stores raw subject/body
  in its own audit table** (`spam_prediction_logs`, `intent_prediction_logs`,
  `routing_decision_logs`, ...) with no anonymization — an already-disclosed,
  project-wide gap (`docs/data_audit_*.md` files don't relitigate this per
  module, but none of them anonymize either). Retroactively anonymizing
  Postgres storage for `emails` alone, while every other table stays raw,
  would be an inconsistent, partial fix that doesn't actually close the
  gap — it would just create two different storage policies with no
  clear reasoning for why `emails` is special on the *storage* axis.
- **The vector store IS structurally different, though** — a
  corpus-wide, similarity-searchable index is a fundamentally different
  exposure profile than a per-request audit-log row a caller has to
  already know the ID of to retrieve. This is *why* Phase 9, specifically,
  is the first phase to actually wire in `app/security/pii_anonymizer.py`
  (present in this codebase since early on, imported nowhere until now) —
  not because retrieval invented a new PII concern, but because it's the
  first component whose failure mode (a name/phone/email number surfacing
  in an unrelated caller's similarity search results) is qualitatively
  worse than "this PII is sitting in a table only someone with the exact
  row ID would query."

### What Gets Anonymized, Precisely

`app/retrieval/embedding_input.py:build_embedding_text()` — cleans
(`EmailPreprocessor(SUMMARY_CONFIG)`, strips HTML/signatures) then
anonymizes (`app/security/pii_anonymizer.py:anonymize_email_body()`,
Presidio-backed: PERSON, EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, and a
DEFAULT catch-all replaced with typed placeholders like `<PERSON>`) before
the result ever reaches an embedder. The anonymized text itself is
**never persisted anywhere** — it exists only transiently to produce the
embedding vector. Only the entity TYPE names detected (e.g. `["PERSON",
"EMAIL_ADDRESS"]`), never the raw values, are returned in
`RetrievalIndexResponse.pii_entity_types_found` and logged — for
observability ("this record's embedding input contained PII of these
kinds"), not for re-identifying anything.

## Trade-offs Against the Other Options

| Axis | This decision (B) | A (raw) | E (embedding only, no text) |
|---|---|---|---|
| Security | PII never enters the searchable index | PII directly searchable/leakable via similarity | Best, but... |
| Retrieval quality | Preserved — anonymization replaces PII with typed placeholders, not deletion, so structural/semantic content survives | Best (nothing altered) | N/A — no debuggability at all |
| Debuggability | Raw text still in Postgres for a human to inspect the "why" behind a match | Best | Worst — no way to inspect what actually got embedded |
| Storage | One extra Presidio pass at index time; no extra storage (anonymized text isn't kept) | No extra cost | N/A |
| Latency | ~36ms/call measured directly (`scripts/benchmark_embedding_models.py`'s adjacent finding, `tests/test_retrieval_security.py`'s bound) — a real, disclosed cost, not negligible relative to FR-45's 500ms budget but far from consuming it | No extra cost | Depends on what "embedding only" even means operationally |
| Future RAG quality | Preserves the option to later decide whether a downstream LLM sees raw or anonymized text — this phase doesn't generate any LLM prompt yet | Best raw-fidelity for a future LLM, worst leakage risk | Unusable for RAG context (no text to show the LLM at all) |

Option D (a structured representation, e.g. entity-extracted fields
instead of prose) was not pursued — no evidence this phase's retrieval
quality needs are better served by structure over cleaned natural-language
text, and it would add real complexity (a schema for "structured email
representation" this codebase doesn't otherwise have) without a
demonstrated need.
