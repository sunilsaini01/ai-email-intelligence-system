# Embedding & Index Versioning (Module 9 / Phase 9, Step 17/Step 18)

## Why This Is Mandatory

If the embedding model changes, old vectors and new query vectors become
semantically inconsistent — a query embedded with MiniLM compared against
vectors stored with TF-IDF (different dimensions, different semantic
space entirely) would silently produce meaningless similarity scores, not
an error.

## Embedding Versioning

Every `emails` row records, at index time
(`app/database/repositories/email_repository.py:mark_indexed()`):

- `embedding_model` — the specific embedder version string
  (`TfidfEmbedder.model_version`, e.g.
  `"tfidf_baseline-20260809-130541"`, or `MiniLmEmbedder.model_version`,
  `"all-MiniLM-L6-v2-via-transformers-v1"`). Distinct model FAMILIES get
  distinct version strings; re-fitting the TF-IDF vectorizer produces a
  new timestamped version, same pattern every other module's
  `*_baseline_metrics.json`-derived `model_version` already uses.
- `embedding_version` — reused to carry the vector-store collection name
  (`"email_embeddings_v1"`) an email's vector currently lives in — see
  "Index Versioning" below for why collection name is the index-version
  signal, not a separate numeric field.

Every `RetrievalIndexResponse`/`RetrievalSearchResponse` also carries
`embedding_model` — a caller comparing scores across two responses can
tell whether they came from the same model (and are therefore
comparable) or not, per RULE 5/Step 13.

## Index Versioning

`VECTOR_COLLECTION = "email_embeddings_v1"`
(`app/services/retrieval_service.py`) — the version lives directly in the
Chroma collection name, not a separate config value. A future embedding
model upgrade (e.g. switching the default to MiniLM, or a newer MiniLM
release) would introduce `email_embeddings_v2` as a **new, additional**
collection — `chromadb.get_or_create_collection()` creates it
automatically on first use, and `v1` is never destroyed or rewritten in
place. This directly satisfies Step 18's "a future model upgrade should
allow v2 without destroying v1 first."

## What "Support Migration" Means Here (Architecturally, Not Fully Automated)

Not implemented: an automated re-embed-everything-into-v2 migration job.
What exists: the **means** to do one safely, without data loss —

1. Deploy the new embedder version (new `VECTOR_COLLECTION` value, or a
   parallel `RetrievalService` instance pointed at a new collection name).
2. Re-run indexing for existing `emails` rows through the new embedder —
   idempotent by construction (same `content_hash` → same `vector_id`
   within the new collection), so a partial/interrupted migration can
   simply be re-run.
3. Cut over `VECTOR_COLLECTION` to the new name once migration is
   verified; `v1` remains queryable (not deleted) until confidence is
   established, then can be dropped via Chroma's own collection-delete
   API (not built into this codebase — a future, explicit operational
   step, not automated).

This is disclosed as **architectural readiness**, not a built,
automated pipeline — RULE 14/Step 27 caution against building
infrastructure (e.g. a migration-orchestration job) without evidence it's
needed yet; no embedding model has actually been upgraded in this
project's lifetime.

## Verified

`tests/test_email_record_persistence.py::test_mark_indexed_updates_status_and_embedding_fields`
confirms `embedding_model`/`embedding_version` are correctly persisted;
`app/routing/rules.py`-style versioning discipline (a single, bumped
string, not a formal semver scheme) is intentionally the same lightweight
convention this codebase already uses for `routing_rules_v1`/
`routing_keywords_v1`.
