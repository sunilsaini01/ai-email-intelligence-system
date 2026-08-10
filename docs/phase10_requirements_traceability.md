# Phase 10 — Auto-Reply Generation: Requirements Traceability

Extracted directly from `project document/PRD_AI_Email_Intelligence_System.md`
§5, Module 10. No requirement below was invented — every row cites its PRD
source line. See `docs/architecture_auto_reply.md` for the full design
record and `docs/rag_evaluation_auto_reply.md` for evaluation evidence.

## Functional Requirements (PRD §5, Module 10)

| PRD Requirement | Design Decision | Implementation | Test | Evidence | Status |
|---|---|---|---|---|---|
| **FR-48**: "System shall generate a draft reply using the email content + top-3 similar resolved emails as RAG context" | Reuses Phase 9's `RetrievalService.search()` (now MiniLM-backed, see "Embedder Decision" below), filters candidates against fresh Postgres for `resolution_status == RESOLVED` and a minimum similarity score, truncates to 3 | `app/api/v1/endpoints/reply.py:_fetch_resolved_context()`, `app/services/auto_reply_service.py:select_context()` | `tests/test_reply_endpoint.py::test_generate_finds_resolved_similar_email_as_context`, `::test_generate_ignores_unresolved_similar_email`, `tests/test_auto_reply_service.py::test_context_is_truncated_to_max_three_items` | **PARTIAL** — mechanism is real and verified end-to-end against real Postgres + real Groq; but Section C of the Phase 10 audit found the system is very likely to have zero or near-zero `RESOLVED` emails in practice today (Phase 9's resolution_status never auto-transitions — see `docs/resolution_status_design.md`), so the "with real historical context" path is currently the *uncommon* case, not the common one — disclosed, not hidden, and designed for explicitly (`NO_SIMILAR_EMAILS` policy) |
| **FR-49**: "Generated replies shall be draft-only by default — not auto-sent without human approval" | No send capability exists anywhere in the reply pipeline — architecturally impossible, not just policy-gated. `DRAFT_STATUSES` has no `SENT` state; only `GENERATED`/`EDITED`/`APPROVED`/`REJECTED`/`FAILED` | `app/models/reply_draft.py` | `tests/test_auto_reply_security.py::test_no_send_status_exists_in_the_draft_lifecycle`, `::test_no_email_sending_capability_exists_in_the_reply_pipeline` (static AST check — no `smtplib`/mail-library import anywhere in the pipeline) | **FULL** |
| **FR-50**: "System shall complete reply generation within 10 seconds" | Two-layer enforcement: GroqProvider passes an 8s budget directly to the SDK's own httpx timeout (real enforcement); the endpoint wraps the full retrieval+PII+LLM sequence in an outer `asyncio.wait_for(10s)` as a best-effort backstop (disclosed as imperfect — Python cooperative cancellation cannot forcibly kill a stuck thread, same caveat `docs/technical_debt/database_write_hang.md` already discloses for `DB_WRITE_TIMEOUT_SECONDS`) | `app/api/v1/endpoints/reply.py` (`LLM_TIMEOUT_SECONDS=8.0`, `TOTAL_LATENCY_BUDGET_SECONDS=10.0`) | `tests/test_reply_endpoint.py::test_generate_records_llm_timeout_as_failed_draft`; real measured latency below | **PARTIAL** — verified within budget in real, warm-process testing (see "Measured Latency" below); PRD's own §13 latency table separately lists 15s/30s for this module, a genuine PRD internal inconsistency, disclosed rather than silently resolved one way |
| **FR-51**: "Agents shall be able to approve, edit, or reject generated drafts" | Three dedicated endpoints, each a real state transition on `reply_drafts`, `reviewer_id` captured (no real auth yet — same disclosed gap as every other module since Phase 1) | `POST /reply/{id}/approve`, `/edit`, `/reject` | `tests/test_reply_endpoint.py::test_full_lifecycle_generate_then_approve`, `::test_full_lifecycle_generate_then_edit`, `::test_full_lifecycle_generate_then_reject`, `tests/test_reply_draft_repository.py` | **FULL** |
| **FR-52**: "Approval/rejection decisions shall feed back into reply quality improvement" | The decision itself is already durably recorded on `reply_drafts` (status/reviewer_id/reviewed_at); a SEPARATE, optional relevance-judgment feedback endpoint reuses the existing `FeedbackLogger` JSONL pattern, same "captured, never auto-applied" stance every other module's feedback path already takes (FR-41's precedent) | `POST /reply/feedback`, `FeedbackLogger.log_auto_reply_feedback()` | `tests/test_reply_endpoint.py::test_feedback_endpoint_logs_and_returns_id` | **PARTIAL** — feedback is captured; nothing in this codebase (any module) auto-retrains/auto-tunes a prompt or model from a feedback file — promoting these judgments into an actual prompt/model change would be a separate, explicit, human-reviewed step, same as FR-41's already-established precedent |

## Non-Functional / Design Requirements (Phase 10 audit, not literally in FR-48–52 but structurally required by them)

| Requirement | Source | Design | Evidence |
|---|---|---|---|
| PII never sent raw to the external LLM | FR-09 ("anonymize PII before passing email content to any external API") | Both the current email AND every retrieved historical email's raw body are re-anonymized (Presidio, reused) immediately before prompt construction — a NEW obligation Phase 9's own PII scrubbing didn't cover (that scrubbing only protected the embedding path, not a future LLM prompt) | `tests/test_auto_reply_service.py::test_pii_in_current_email_never_reaches_the_llm_prompt_raw`, `::test_pii_in_retrieved_context_never_reaches_the_llm_prompt_raw` |
| Retrieved/current email content is DATA, never INSTRUCTIONS | Step 6/RULE — prompt injection defense | Strictly delimited prompt sections + explicit system-prompt rule; a pre-filter heuristic (`_INJECTION_PHRASES`) skips generation entirely for classic injection phrasing | `tests/test_reply_prompt.py::test_injection_style_content_stays_inert_as_data_not_instructions`, `tests/test_auto_reply_security.py::test_prompt_injection_in_current_email_is_flagged_unsafe_and_not_generated` |
| No API key exposure | Master-prompt security constraint | Env var only (`backend/.env`, gitignored), never logged (rotation log records `key_index`, not the key), never in a response | `tests/test_auto_reply_security.py::test_response_never_contains_the_configured_api_key`, `::test_groq_provider_never_logs_the_raw_key_on_rotation` |
| Provider abstraction, not hard-coded to Groq | Step 11 | `LLMProvider` Protocol; `GroqProvider`/`FakeLLMProvider` both satisfy it; `AutoReplyService` depends only on the Protocol | `app/inference/llm_provider.py`, `app/inference/groq_provider.py` |
| No paid API key required for the standard test suite | Step 17/RULE | `FakeLLMProvider` used everywhere in `pytest`; `GroqProvider` exercised only via a monkeypatched fake `groq.Groq` client (real exception types, no network call); the ONLY real-API-call code path is the manual, opt-in `scripts/qualitative_eval_auto_reply.py` | `tests/test_groq_provider.py` |
| Every migration verified against real PostgreSQL | Standing project convention | `reply_drafts` table, upgrade/downgrade/upgrade round-trip, real insert, verified against a disposable Postgres 16 container | See "Real Postgres Verification" in `docs/architecture_auto_reply.md` |
| Never mix vectors from incompatible embedding models | `docs/embedding_versioning.md`'s own prescribed rule | Switching Auto-Reply's context quality required switching Phase 9's OWN structural default (TF-IDF → MiniLM) and bumping the vector collection (`v1` → `v2`), not bolting a second, disconnected embedder onto Auto-Reply alone — see "Embedder Decision" below | `app/services/retrieval_service.py` |

## A Real Bug Found and Fixed During This Phase's Own End-to-End Testing

`RetrievalService._resolve_embedder()`/`_resolve_vector_store()` used to
construct a brand-new default embedder/vector-store object on **every
call** when none was injected. Invisible with Phase 9's TF-IDF default
(cheap to construct either way) — but running the real end-to-end path
against a real Postgres container and the real Groq API for this phase
surfaced it directly: retrieval latency was ~1.4s **per request**, not
the ~6ms Phase 9 had benchmarked, because MiniLM's model was being
reloaded into memory every single call. Fixed by memoizing both on the
`RetrievalService` instance; re-measured directly after the fix: warm
per-request retrieval latency dropped to ~17-19ms. `app/main.py`'s
startup warmup was also extended to force both the embedder AND the
vector store (previously only the embedder), since Chroma's
`PersistentClient` was separately found to have its own real, multi-second
cold start independent of the embedding model. See
`docs/error_analysis_auto_reply.md` for the full incident record.

## Embedder Decision (Step 4 Requirement)

Per the Phase 10 audit's own instruction — "do not blindly switch models
because MiniLM performed better on a tiny qualitative sample" — the
decision to switch was based on Phase 9's own **measured** comparison
(`docs/embedding_model_decision.md`: TF-IDF scored a literal 0.000 on 3 of
6 paraphrase pairs; MiniLM got 6/6), not this phase's own new evidence.
What Phase 10 verified independently: no real emails have meaningfully
been indexed into Phase 9's `v1` collection yet (Section C of the audit),
so switching the collection version now costs nothing in migration terms
— the exact timing `docs/embedding_model_decision.md` itself flagged as
the anticipated follow-up ("recommended explicitly as a Phase 10
follow-up"). `VECTOR_COLLECTION` bumped `email_embeddings_v1` →
`email_embeddings_v2`; `v1` is not deleted, per
`docs/embedding_versioning.md`'s own migration mechanism.

## Measured Latency (Real Groq API + Real Postgres, Not Fabricated)

Measured directly via `httpx.AsyncClient` against a real, disposable
Postgres 16 container and the real, configured Groq API
(`llama-3.3-70b-versatile`), warm process (after the same
`_resolve_embedder()`/`_resolve_vector_store()` warmup `app/main.py`
performs at startup):

| Request | Total | Retrieval | LLM |
|---|---|---|---|
| 1st (cold, before warmup fix) | 7099ms | 5848ms | 855ms |
| 1st (cold, after warmup extended to vector store) | 2988ms | 1890ms | 666ms |
| 2nd (warm) | 967ms | 19ms | 613ms |
| 3rd (warm) | 760ms | 19ms | 422ms |

All comfortably within FR-50's 10s ceiling, including the cold-start case.
**Not measured**: concurrent load, P95/P99 under realistic traffic — no
load-testing infrastructure exists for any module in this codebase, same
disclosed gap as every prior phase.

## Explicitly Not Implemented This Phase (and why)

| Item | Why deferred |
|---|---|
| ~~Ollama local fallback~~ | **Superseded** — implemented in a post-phase fix round, see "Post-Phase-10 Fixes" below and `docs/architecture_auto_reply.md` "Ollama Fallback." This row is kept for the historical record of what Phase 10's initial delivery actually shipped. |
| Human Acceptance Rate measurement | PRD's own primary metric (>60% target) — requires real agents using the approve/edit/reject endpoints against real traffic, which does not exist yet. Marked explicitly NOT YET MEASURED, not fabricated — see `docs/rag_evaluation_auto_reply.md` |
| Auto-wiring retrieval indexing into Spam/Category/Routing | A Phase 9 gap (`docs/architecture_rag.md` "Not Auto-Wired"), out of Phase 10's own scope — Auto-Reply's `/generate` does not require the source email to already be a canonical `EmailRecord` (works from raw subject/body directly), so this gap does not block FR-48 mechanically, only its real-world usefulness |
| LangChain / LLM orchestration framework | PRD's own tech-stack table names it; not used — this codebase's established pattern (Phase 6's abstractive summarizer, Phase 9's MiniLM) talks to model APIs directly, and Auto-Reply's single-provider, single-call flow has no orchestration complexity that would justify the dependency |
| BLEU-4/BERTScore automated metrics | Deferred to the qualitative eval script's manual-inspection role — no reference replies exist to score against; PRD itself lists these as secondary to Human Acceptance Rate |

## Engineering Gates — Outcome

| Gate | Outcome |
|---|---|
| PRD FR-48–52 audited | Done |
| Repository audited (retrieval, feedback, DB, config, API conventions) | Done |
| Resolved-email data reality audited | Done — found likely near-empty in practice, designed around explicitly rather than assumed away |
| Embedding model decision re-verified, not blindly switched | Done — based on Phase 9's own prior measurement, timing justified by near-empty `v1` |
| LLM provider selected with explicit confirmation | Done — Groq, `llama-3.3-70b-versatile`, project-owner decision |
| Security review completed | Done — `docs/security_auto_reply.md` |
| Database designed (minimum necessary) | Done — one table, `reply_drafts`, JSON column instead of a join table |
| API designed, consistent with existing conventions | Done — 6 endpoints, no duplication of Phase 9's retrieval endpoints |
| Provider abstraction implemented | Done — `LLMProvider` Protocol, 2 implementations (Groq, Fake) |
| Fallback strategy evaluated | Done — architected for, not built (project-owner decision) |
| Latency budget defined and measured | Done — real numbers above, not estimated |
| Testing strategy followed (no paid key required for standard suite) | Done — 62 new tests, all use `FakeLLMProvider` or a monkeypatched fake `groq.Groq` |
| Failure/edge-case testing | Done — timeout, provider error, injection, huge/empty/Unicode/HTML body, malformed draft_id, DB failure path |
| Observability implemented | Done — structured logs, never raw bodies/keys/full prompts |
| Documentation complete | Done — this file plus 5 companion docs |
| Real PostgreSQL migration verified | Done — upgrade/downgrade/upgrade round-trip, real insert, real end-to-end request through the actual FastAPI app |
| Real Groq API exercised at least once (not just mocked) | Done — `scripts/qualitative_eval_auto_reply.py`, 5 cases, real output reviewed |
| A real bug found via this phase's own testing, root-caused and fixed | Done — embedder/vector-store re-construction-per-call bug, see above and `docs/error_analysis_auto_reply.md` |
| Previous tests remain passing | Done — 389 passed, 1 skipped, 0 failed (up from 327) |
| Production-readiness level assigned | Done — LEVEL 2 (auto-reply generation infrastructure validated, human-acceptance evidence not yet collected) — see `docs/model_cards/auto_reply.md` |

## Post-Phase-10 Fixes

Five issues identified after the initial delivery above, fixed in order
before Phase 11 began:

| # | Fix | Implementation | Test | Doc |
|---|---|---|---|---|
| 1 | Hallucination-mitigation confidence gate | `AutoReplyService.generate()` appends a visible warning to `generated_text` when fewer than 2 usable RESOLVED context items were used | `tests/test_auto_reply_service.py::test_low_context_appends_confidence_warning`, `::test_sufficient_context_does_not_append_warning` | `docs/architecture_auto_reply.md` "Confidence Gate" |
| 2 | Human Acceptance Rate tracking | New `reply_drafts.edit_distance` column (Levenshtein, `app/nlp/edit_distance.py`, no new dependency) computed on edit; `auto_reply_review_action` structured log line on every approve/edit/reject | `tests/test_edit_distance.py`, `tests/test_reply_draft_repository.py::test_edit_computes_and_stores_edit_distance`, `tests/test_reply_endpoint.py` (edit_distance in response) | `docs/architecture_auto_reply.md` "Human Acceptance Rate Tracking" |
| 3 | Auto-mark-resolved on approve | `POST /reply/{id}/approve` best-effort marks `source_email_id`'s `resolution_status = RESOLVED` | `tests/test_reply_endpoint.py::test_approve_auto_marks_source_email_resolved` + 3 edge-case tests | `docs/architecture_auto_reply.md` "Auto-Mark-Resolved on Approve" |
| 4 | Groq-vs-GPT-4o/Claude deviation documented | Expanded "LLM Provider Decision" section: why, quality tradeoff (explicitly not measured head-to-head), switching triggers | N/A — documentation only | `docs/architecture_auto_reply.md` "Why Groq/Llama Over the PRD's Named GPT-4o/Claude" |
| 5 | Ollama fallback | `OllamaProvider` (real HTTP to a local server) + `FallbackLLMProvider` (composes two `LLMProvider`s, no new Protocol), triggered on Groq 429/503 only via new `LLMRateLimitedError`/`LLMServiceUnavailableError` subclasses | `tests/test_ollama_provider.py`, `tests/test_fallback_llm_provider.py`, extended `tests/test_groq_provider.py` — plus a REAL end-to-end verification against a locally-running Ollama server | `docs/architecture_auto_reply.md` "Ollama Fallback" |

New migration: `c8f2a7e91d36_add_edit_distance_to_reply_drafts.py`
(verified against a real Postgres container, upgrade/downgrade/upgrade).
Full regression after all 5 fixes: see the final report for the exact
count — zero regressions, all new tests passing.
