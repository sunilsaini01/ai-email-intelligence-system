# Similar Email Retrieval / RAG Foundation — Architecture (Phase 9)

> **Data status**: Retrieval quality is unvalidated against real ground
> truth (no labelled retrieval dataset exists) — see
> `docs/error_analysis_retrieval.md` before trusting any retrieval-quality
> claim. The canonical `emails` entity and PII anonymization introduced
> here are new infrastructure, not carried-over caveats from Phases 1–8.

## What This Module Establishes

The ninth production module, and the first with genuinely new
infrastructure this codebase didn't have at all before: a vector store
(none existed), a canonical cross-module email entity (none existed — see
"The Email Entity Problem" below), and the first wired-in use of PII
anonymization (existed as dead code since early in this project, never
imported until now).

## Request Flow — Indexing

```
POST /api/v1/retrieval/index {subject?, body, sender_email?, category?, department?}
        │
        ▼
content_hash = compute_content_hash(subject, body)
        │
        ▼
EmailRepository.upsert_by_content_hash()  -- Postgres, index_status=PENDING
        │
        ▼
RetrievalService.index_email()  (run_in_threadpool)
        │  anonymized_text, pii_types = build_embedding_text(subject, body)
        │  embedding = embedder.embed(anonymized_text)
        │  vector_store.upsert(collection, org_id, vector_id=content_hash, embedding, metadata)
        ▼
EmailRepository.mark_indexed()  -- index_status=INDEXED, embedding_model/version recorded
        │
        ▼
RetrievalIndexResponse {email_id, content_hash, was_created, index_status, ...}
```

## Request Flow — Search

```
POST /api/v1/retrieval/search {subject?, body, top_k=5, category?, department?, resolution_status?}
        │
        ▼
RetrievalService.search()  (run_in_threadpool)
        │  anonymized_text, _ = build_embedding_text(subject, body)
        │  embedding = embedder.embed(anonymized_text)
        │  matches = vector_store.query(collection, org_id, embedding, top_k=OVERFETCH, where={category, department})
        ▼
For each candidate (over-fetched, see docs/vector_index_consistency.md):
        EmailRepository.get_by_content_hash() -- fresh Postgres lookup
        skip if record is None, is_deleted, or resolution_status doesn't match
        truncate to requested top_k
        ▼
RetrievalSearchResponse {query_id, results: [SimilarEmailMatch, ...], embedding_model, ...}
```

## The Email Entity Problem (Step 2)

Repository audit (before any code was written) confirmed: every prior
module logs to its own independent audit table with its own fresh UUID
per request — nothing links "this category-log row" and "this
routing-log row" as being about the same email. FR-46's filtering
requirement structurally needs that link. `app/models/email_record.py`
(`emails` table) is the minimum canonical record this need requires — NOT
a general email-ingestion system (no Message-ID parsing, no attachment
storage, no thread reconstruction).

## Why Category/Department Are Caller-Supplied, Not Recomputed

`RetrievalService` does **not** call `CategoryService`/`RoutingService`
itself. `POST /retrieval/index` accepts `category`/`department` as
optional fields the caller already obtained from those endpoints. This
avoids Phase 9 becoming a second orchestrator duplicating Phase 8's job
(RoutingService already composes Category; a third layer re-composing the
same signals would be a real, unjustified duplicate abstraction) and
matches the PRD's own data-flow ordering (§10.2: classify → route →
store) — indexing happens *after* classification, consuming its output,
not re-deriving it.

## Not Auto-Wired to Upstream Endpoints

FR-43 says "every processed email" — this phase provides the *capability*
to index any email, but does not modify `/spam/predict`, `/category/
predict`, or `/routing/predict` to automatically call `/retrieval/index`
as a side effect. Wiring that up is a small, mechanical follow-up
(call `RetrievalService.index_email()` from those endpoints, or a future
orchestration layer) deliberately left undone this phase — RULE 1 (don't
prematurely build the full pipeline) and the "retrieval infrastructure,
not RAG/Auto-Reply" scope boundary both argue for shipping the retrieval
primitive first and wiring automatic triggering only once it's proven.

## Composition Boundary

Same in-process, no-HTTP boundary `docs/architecture_routing.md`
established for Module 8 — `RetrievalService` never makes an HTTP call to
another endpoint in this same application. Unlike `RoutingService`,
`RetrievalService` composes exactly one upstream dependency conceptually
(an embedder) plus the vector store, not five ML services — its
orchestration complexity comes from spanning two persistence systems
(Postgres + Chroma), not from composing many signals.

## Security

- **PII**: see `docs/phase9_pii_embedding_strategy.md` — anonymized before
  embedding, raw text unchanged in Postgres (consistent with every other
  module's current storage stance).
- **Cross-tenant leakage**: structurally prevented, not just tested for —
  see `docs/vector_tenant_isolation.md`.
- **Prompt-injection preparedness**: Phase 9 does not generate any LLM
  prompt yet, but retrieved content will eventually feed a future RAG/
  Auto-Reply module (PRD Module 10). `tests/test_retrieval_security.py::
  test_prompt_injection_style_content_is_treated_as_ordinary_text`
  confirms indexing/search today have no instruction-following mechanism
  to exploit (classical embedding + vector similarity), and that `top_k`
  is always respected regardless of body content — but this is a
  forward-looking note, not a solved problem for the eventual RAG
  consumer, which will need its own defenses when it exists.
- **Malformed input**: huge bodies, empty subject/body, Unicode, HTML,
  control characters, malformed `email_id` path parameters — all tested,
  none crash the service (`tests/test_retrieval_security.py`,
  `tests/test_retrieval_endpoint.py`).
- **Regex-DoS**: not applicable — this module uses no custom regex
  matching (unlike Module 8's keyword engine); text processing is
  `EmailPreprocessor` (already used by 5 prior modules) plus Presidio's
  own recognizers.

## Performance

Component-level measurements (`scripts/benchmark_embedding_models.py`),
not a load test:

| Component | Latency |
|---|---|
| PII anonymization (Presidio) | ~36ms/call |
| TF-IDF embedding (warm) | 0.20ms |
| MiniLM embedding (warm) | 6.27ms |
| Chroma query (small corpus) | sub-millisecond |

All comfortably within FR-45's 500ms budget in isolation. **Not
measured**: end-to-end P50/P95/P99 under realistic corpus size (10K+
emails) or concurrent load — no load-testing infrastructure exists for
any module in this codebase, disclosed as a gap, not silently assumed
fine at scale.

## Known Gaps

| Gap | Reason |
|---|---|
| Not auto-triggered after upstream classification | Deliberately deferred — see "Not Auto-Wired" above |
| No real relevance ground truth | No labelled retrieval dataset exists; qualitative gold set only — `docs/error_analysis_retrieval.md` |
| No load testing | No infrastructure exists for this in any module |
| No near-duplicate / thread-aware deduplication | Content-hash identity only — `docs/email_identity_and_deduplication.md` |
| No real tenant authentication | Structural isolation only, blocked on auth (same gap since Phase 1) — `docs/vector_tenant_isolation.md` |
| No automated embedding-model migration pipeline | Architectural readiness only (versioned collections) — `docs/embedding_versioning.md` |
| TF-IDF default has a demonstrated paraphrase-blindness weakness | Disclosed, not hidden — `docs/embedding_model_decision.md` |
