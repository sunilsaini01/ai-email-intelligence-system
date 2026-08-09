# Email Identity & Deduplication (Module 9 / Phase 9, Step 3)

## The Problem

No reliable Message-ID exists anywhere in this system. Every module from
Phase 3 through Phase 8 accepts a bare `{subject, body}` pair via an API
call — nothing parses or persists real RFC 822 email headers. A vector
retrieval system needs a stable identity to avoid re-embedding (and
re-storing) the same email every time it's processed, and to support
idempotent re-indexing (Step 3, RULE 10).

## Decision: Content Hash, Not Message-ID

`app/retrieval/identity.py:compute_content_hash(subject, body)` — a
normalized (whitespace-collapsed, lowercased) SHA-256 of `subject + body`,
scoped per-organization via a `UNIQUE (organization_id, content_hash)`
constraint on the `emails` table
(`app/models/email_record.py`).

`message_id` is still a column on `emails` — kept for a **future** real
email-ingestion path, where a genuine Message-ID would become available —
but it plays no role in identity or deduplication today. This is
explicitly disclosed, not silently ignored: a real ingestion pipeline
would need to decide how content-hash identity and Message-ID identity
interact (e.g., a forwarded email has a new Message-ID but often
near-identical content) — out of scope for this phase, which only has
API-supplied `{subject, body}` to work with.

## What Idempotent Indexing Actually Means Here

- **Vector identity == content_hash.** `RetrievalService.index_email()`
  uses `content_hash` as the vector store's `vector_id` directly (not a
  database-generated UUID) — see
  `app/services/retrieval_service.py`'s module docstring for the full
  reasoning. Re-indexing identical `(subject, body)` within one
  organization produces the exact same `vector_id`, so the vector store's
  `upsert` naturally overwrites rather than duplicates.
- **DB identity is enforced at the constraint level, not just in
  application code.** `EmailRepository.upsert_by_content_hash()` does a
  portable select-then-insert-or-update (not Postgres-only `ON CONFLICT`
  syntax, to stay testable against SQLite like every other repository in
  this codebase) — but the actual guarantee is the `UNIQUE
  (organization_id, content_hash)` constraint, verified directly against
  a real Postgres container: a second `INSERT` with the same
  `(organization_id, content_hash)` is rejected by Postgres itself, not
  just by the application's read-before-write logic.

## Handled Cases (Step 3's explicit list)

| Case | Behavior |
|---|---|
| Duplicate emails (same content submitted twice) | Same content_hash → same row updated, same vector overwritten. Verified: `tests/test_retrieval_endpoint.py::test_index_is_idempotent` |
| Replayed ingestion (retry after a timeout, etc.) | Same as above — retries are naturally safe |
| Same email processed twice by different callers | Same as above, PROVIDED both calls use the same `organization_id` |
| Forwarded emails | Content differs (forward headers/prefix change the body) → different content_hash → a NEW record. This is a disclosed limitation, not a bug: this phase has no thread/forward-relationship model at all (Module 6's `ThreadNormalizer` builds a narrative for summarization but doesn't persist a thread_id anywhere retrieval could reuse) |
| Re-indexing with updated category/department | Same content_hash → same vector_id → the existing vector's metadata is overwritten with the new values, no special-case code needed (see `app/services/retrieval_service.py`'s docstring) |
| Cross-organization identical content | Different `organization_id` → different row, different vector — verified: `tests/test_email_record_persistence.py::test_same_content_hash_in_different_organizations_are_separate_records` |

## What This Does NOT Solve

- **Near-duplicate detection** (e.g., the same complaint reworded slightly)
  is not attempted — content_hash requires exact (normalized) match.
  Two emails that are 95% identical get two separate records. A future
  near-duplicate pass (e.g., a similarity threshold against existing
  vectors before indexing) is a reasonable Phase 10+ enhancement, not
  built here.
- **Cross-thread deduplication** (a reply quoting the original) is not
  attempted — see the "Forwarded emails" row above.
