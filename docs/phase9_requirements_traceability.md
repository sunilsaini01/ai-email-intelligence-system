# Phase 9 — Similar Email Retrieval / RAG Foundation: Requirements Traceability

Extracted directly from `project document/PRD_AI_Email_Intelligence_System.md`
§5, Module 9. No requirement below was invented — every row cites its PRD
source line.

## Functional Requirements (PRD §5, Module 9)

| PRD Requirement | Design Decision | Implementation | Test | Evidence | Status |
|---|---|---|---|---|---|
| **FR-43**: "System shall compute and store semantic embeddings for every processed email" | Two embedders compared and both shipped (`EmbeddingBackend` Protocol); TF-IDF is the structural default, MiniLM available via injection — see `docs/embedding_model_decision.md`. Embeddings persisted in a versioned Chroma collection, indexing status tracked in the new `emails` table | `app/inference/tfidf_embedder.py`, `app/inference/minilm_embedder.py`, `app/services/retrieval_service.py:index_email()`, `POST /api/v1/retrieval/index` | `tests/test_retrieval_service.py`, `tests/test_retrieval_endpoint.py` | **PARTIAL** — "every processed email" implies automatic indexing as a side effect of the existing Spam/Category/Routing pipeline; this phase provides the indexing capability but does not wire it to auto-fire after those endpoints (a caller must explicitly call `/retrieval/index`) — see `docs/architecture_rag.md` "Not Auto-Wired to Upstream Endpoints" |
| **FR-44**: "System shall retrieve the top-5 semantically similar emails for every new email" | `top_k` defaults to 5 exactly (`RetrievalSearchRequest.top_k: int = Field(default=5, ...)`), never silently changed | `app/services/retrieval_service.py:search()`, `POST /api/v1/retrieval/search` | `tests/test_retrieval_endpoint.py::test_search_respects_top_k_default_of_5` | **FULL** for the retrieval mechanism itself; same "not auto-triggered for every new email" caveat as FR-43 |
| **FR-45**: "Vector similarity search shall complete within 500ms" | Not formally load-tested (no load-testing infrastructure exists for ANY module in this codebase), but measured directly: embedding (6.27ms MiniLM warm / 0.20ms TF-IDF warm) + PII anonymization (~36ms) + Chroma query (sub-millisecond at this corpus scale) are all comfortably within budget in isolation | `scripts/benchmark_embedding_models.py` | Manual benchmark run, not an automated perf-regression test | **PARTIAL** — component-level latency measured and within budget; end-to-end P50/P95/P99 under realistic corpus size/concurrent load is NOT measured — see `docs/architecture_rag.md` "Performance" |
| **FR-46**: "Similar email results shall be filterable by: category, department, resolution status" | All three implemented; category/department filtered via Chroma metadata (`where`), resolution_status filtered via a fresh Postgres lookup specifically because it's the one mutable-outside-reindexing field (see `app/services/retrieval_service.py`'s module docstring for why the split) | `app/api/v1/endpoints/retrieval.py:search_similar_emails()` | `tests/test_retrieval_endpoint.py::test_resolution_status_update_and_filtering` | **FULL** |
| **FR-47**: "Vector index shall support incremental updates (no full rebuild required)" | Vector identity == content_hash (not a sequential ID), so `ChromaVectorStore.upsert()` naturally adds/overwrites individual vectors — no rebuild step exists or is needed anywhere in this implementation | `app/retrieval/chroma_vector_store.py:upsert()` | `tests/test_retrieval_vector_store.py` (idempotent upsert contract test) | **FULL** |

## Non-Functional / Design Requirements (Phase 9 brief, not literally in FR-43–47 but structurally required by them)

| Requirement | Source | Design | Evidence |
|---|---|---|---|
| Canonical email identity | Step 2/3 — FR-46 needs a stable cross-signal join point that didn't exist before this phase | New `emails` table, content-hash identity | `docs/email_identity_and_deduplication.md` |
| Tenant isolation boundary | RULE 7 | `organization_id` required (not optional) on every `VectorStore` method | `docs/vector_tenant_isolation.md` |
| No cross-tenant retrieval | RULE 7 | Verified directly | `tests/test_retrieval_service.py::test_tenant_isolation_between_organizations`, `tests/test_retrieval_security.py::test_cross_tenant_retrieval_is_never_possible` |
| PII not embedded raw | RULE 6 | Presidio-based anonymization before embedding only | `docs/phase9_pii_embedding_strategy.md` |
| Similarity score ≠ probability | RULE 5 | Documented on every schema field that carries a score | `app/schemas/retrieval.py` |
| No silent empty result on vector-store failure | RULE 9 | 503, not an empty 200 | `app/api/v1/endpoints/retrieval.py:search_similar_emails()` |
| Idempotent indexing | RULE 10 | DB unique constraint `(organization_id, content_hash)` + content-derived vector IDs | `tests/test_email_record_persistence.py::test_upsert_same_content_hash_updates_not_duplicates` — verified additionally against real Postgres |

## Explicitly Not Implemented This Phase (and why)

| Item | Why deferred |
|---|---|
| Auto-indexing after Spam/Category/Routing predict | Would require those endpoints to call retrieval, or a new orchestration layer — out of Phase 9's "retrieval infrastructure" scope (RULE 1: don't build Auto-Reply prematurely; this is the same category of scope discipline) |
| Real relevance ground truth / Recall@K on real traffic | No labelled retrieval dataset exists; a 15-email/5-query hand-written gold set was built instead, disclosed as qualitative — see `docs/error_analysis_retrieval.md` |
| PineconeVectorStore | PRD names it for "Prod"; this phase implements the "Dev" tier only, behind the same `VectorStore` Protocol a Pinecone implementation would also satisfy |
| DB-backed configurable resolution-status workflow (assignment, SLA, notifications) | No such workflow exists anywhere in this codebase; only a minimal, manually-set status field was built |
| Load testing / P95/P99 under concurrent load | No load-testing infrastructure exists for any module in this project |

## Engineering Gates — Outcome

| Gate | Outcome |
|---|---|
| PRD FR-43–47 audited | Done |
| Repository audited (no canonical email entity existed anywhere) | Done — see `docs/architecture_rag.md` |
| Canonical email identity defined | Done — content-hash, `docs/email_identity_and_deduplication.md` |
| Deduplication implemented | Done — DB unique constraint + content-derived vector IDs, verified against real Postgres |
| Resolution status defined | Done — invented, minimal, disclosed as such — `docs/resolution_status_design.md` |
| Tenant isolation boundary designed | Done — `docs/vector_tenant_isolation.md` |
| PII embedding strategy defined | Done — `docs/phase9_pii_embedding_strategy.md` |
| Embedding input defined | Done — `docs/embedding_input_strategy.md` |
| Embedding model selected and justified | Done, with a real measured comparison — `docs/embedding_model_decision.md` |
| Vector store selected and justified | Done — `docs/vector_store_decision.md` |
| Vector-store abstraction implemented | Done — `app/retrieval/vector_store.py` Protocol + 2 implementations |
| Top-K retrieval implemented | Done, default 5 |
| Metadata filtering implemented | Done — category/department/resolution_status, tested individually and combined |
| Similarity metric documented | Done — cosine, explicitly not a probability |
| API implemented | Done — index/search/resolution-update/delete/feedback |
| Indexing pipeline implemented | Done |
| Idempotent indexing verified | Done — unit, integration, AND real-Postgres constraint-violation test |
| Embedding versioning implemented | Done — `embedding_model`/`embedding_version` columns |
| Index versioning designed | Done — collection name encodes version (`email_embeddings_v1`) |
| Update/re-index behavior implemented | Done — same content_hash overwrites |
| Delete behavior implemented | Done — soft delete + immediate vector removal |
| Failure handling implemented | Done — 503 on vector-store/embedding failure, never a silent empty result |
| Database/vector consistency strategy implemented | Done — `docs/vector_index_consistency.md` |
| Security review completed | Done — `docs/architecture_rag.md` "Security" |
| Observability implemented | Done — structured logs, never raw subject/body/PII |
| Performance benchmark completed | Partial — component-level only, no load test |
| Retrieval evaluation strategy defined | Done — engineering validation, explicitly not production ML validation |
| Human relevance set created OR gap documented | Done — 15-email/5-query hand-written gold set, `docs/error_analysis_retrieval.md` |
| Unit/integration/API/failure tests pass | Done — 53 new Phase 9 tests |
| Previous tests remain passing | Done — 327 passed, 1 skipped, 0 failed (up from 274) |
| Real PostgreSQL migration verified | Done — upgrade/downgrade/upgrade, unique constraint verified directly with a duplicate-insert attempt |
| Docker/local development verified | Chroma runs embedded (no new Docker service needed) — see `docs/vector_store_decision.md` |
| Documentation complete | Done — this file plus 12 companion docs |
| Production-readiness level assigned | Done — LEVEL 2 (retrieval infrastructure validated) — see `docs/model_cards/embedding_retrieval.md` |
