# Model Card — Similar Email Retrieval (Phase 9)

> **No human-labelled retrieval-outcome ground truth exists anywhere in
> this project.** Every metric in this document is either a component-level
> measurement (latency, dimension) or a small, author-curated qualitative
> check — never presented as production ML validation. See "Evaluation"
> below and `docs/error_analysis_retrieval.md`.

## Model Details

| Field | Value |
|---|---|
| Approach | Vector similarity search (cosine) over PII-scrubbed email embeddings, metadata-filtered |
| Embedders (compared, both shipped) | TF-IDF baseline (served default) / all-MiniLM-L6-v2 via raw `transformers` (available via injection) |
| Vector store | ChromaDB, embedded/local (`artifacts/chroma/`) |
| Vector identity | Content hash (SHA-256 of normalized subject+body), not a DB-generated ID |
| Served via | `POST /api/v1/retrieval/index`, `POST /api/v1/retrieval/search` |
| Training data (TF-IDF only) | `priority_synthetic_v1` + `category_synthetic_v1` text (real Enron email, **unsupervised** — no labels used, so none of those datasets' label-fabrication caveats apply here) |

## Why Two Embedders Were Built, And Why the Weaker One Is the Default

Compared directly (`docs/embedding_model_decision.md`), not assumed:
TF-IDF is ~30x faster (0.20ms vs. 6.27ms warm) but demonstrated a real,
structural weakness — 0.000 similarity (zero vocabulary overlap) on 3 of
6 hand-written paraphrase pairs that MiniLM correctly identified as
similar. TF-IDF remains the *structural default* for `RetrievalService`
specifically for zero-network-dependency and test-suite determinism, not
because it's the better retriever — this trade-off is disclosed
explicitly, not resolved silently, and flagged as a recommended Phase 10
follow-up (switch the default to MiniLM, already fully working) in the
final Phase 9 report.

## Two Real Bugs Found and Fixed During This Phase's Own Testing

1. **TF-IDF vocabulary pollution** — the first fitted vectorizer's
   vocabulary was dominated by HTML fragments and mailing-list noise;
   "refund" wasn't in it at all, so every similarity score was exactly
   0.0. Found via this phase's own end-to-end smoke test, fixed before
   the artifact was relied on anywhere. See `docs/error_analysis_retrieval.md`
   "Incident 1."
2. **A Windows-specific import-order crash** segfaulting the *entire*
   test suite (not just Phase 9's own tests) — found via the full
   regression run, root-caused to a `transformers`/`sklearn`/`pandas`/
   `pyarrow` native-library interaction, fixed with a documented,
   verified import-order workaround in `app/main.py`. See
   `docs/error_analysis_retrieval.md` "Incident 2."

Both are disclosed here because a model card that only reports the
happy-path numbers, after two real defects were found and fixed getting
there, would be a materially incomplete picture of this module's
trustworthiness.

## Composed Signal Summary

Retrieval does not classify anything — it composes an embedding model (see
above), a vector store (Chroma, local, unvalidated at scale beyond a
qualitative smoke test), and Postgres (source of truth for
category/department/resolution_status filtering). Category/department
values indexed alongside a vector are *caller-supplied snapshots* from
Phase 5/Phase 8's own outputs — this module inherits whatever
trustworthiness those already carry (synthetic labels, not PRD-compliant
— see `docs/data_audit_categorization.md`, `docs/routing_signal_reliability.md`)
without re-validating or improving on it.

## Intended Use

- **Retrieval infrastructure validation** — proves indexing → embedding →
  vector storage → metadata-filtered similarity search → audit-consistent
  deletion works end-to-end, with real Postgres verification.
- **Not validated for production relevance-ranking decisions.** No
  labelled retrieval dataset exists; the qualitative gold set
  (`docs/error_analysis_retrieval.md`) is a diagnostic tool, not evidence
  of real-world retrieval quality.
- **Not yet consumed by any RAG/Auto-Reply system** — this phase is
  retrieval infrastructure only, per its own explicit scope boundary
  (RULE 1).

## Evaluation

**No Recall@K/Precision@K/MRR/nDCG@K is reported as a trustworthy
production metric**, because no human-labelled retrieval-outcome ground
truth exists (RULE 4/RULE 16 — never fabricate evaluation metrics). What
was measured instead, classified honestly as **ENGINEERING VALIDATION**:

| Evaluation type | What was checked | Where |
|---|---|---|
| Component latency | Embedding (both models), PII anonymization, vector query — all within FR-45's 500ms budget in isolation | `scripts/benchmark_embedding_models.py` |
| Embedding-model comparison | TF-IDF vs. MiniLM, dimension/latency/qualitative paraphrase pairs | `docs/embedding_model_decision.md` |
| Idempotent indexing | Unit, integration, AND real-Postgres unique-constraint-violation test | `tests/test_email_record_persistence.py`, direct `psql` duplicate-insert attempt |
| Tenant isolation | Verified at service, vector-store, and DB layers independently | `tests/test_retrieval_service.py`, `tests/test_retrieval_vector_store.py`, `tests/test_email_record_persistence.py` |
| Metadata filtering | category/department/resolution_status, individually and combined | `tests/test_retrieval_endpoint.py::test_resolution_status_update_and_filtering` |
| Failure isolation | Vector-store/embedding failure → 503, never a silent empty result | `app/api/v1/endpoints/retrieval.py` |
| Adversarial robustness | Huge/empty/Unicode/HTML/malformed-ID/prompt-injection-style input | `tests/test_retrieval_security.py` |
| Manual qualitative gold set | 15-email corpus, 5 queries, both embedders | `scripts/qualitative_eval_retrieval.py`, `docs/error_analysis_retrieval.md` |

## Limitations

1. **No production retrieval-quality evidence exists** — the PRD's own
   implied quality bar (a useful "similar emails" feature) is untested
   against real usage.
2. **TF-IDF's default status trades quality for determinism** — a
   disclosed, not hidden, choice (see above).
3. **Not auto-triggered** — FR-43's "every processed email" is a
   capability, not an automatic behavior, this phase (`docs/architecture_rag.md`
   "Not Auto-Wired").
4. **No near-duplicate/thread-aware deduplication** — content-hash
   identity only (`docs/email_identity_and_deduplication.md`).
5. **No load testing** — component latencies are good; end-to-end
   behavior under realistic corpus size/concurrency is unmeasured.
6. **Inherits Category/Routing's own data-quality caveats** for any
   filtered/displayed category or department value.
7. **PII anonymization is Presidio's out-of-the-box recognizers** — not
   tuned or validated against this project's specific email domain; false
   negatives (missed PII) are possible and undisclosed-by-measurement (no
   PII-detection accuracy was benchmarked, only that the mechanism runs
   and returns typed entity lists in tests).

## Path to Production-Validated Retrieval (Not Implemented — Blocked on Data + Auto-Wiring)

1. Real, human-curated relevance judgments at meaningful scale (hundreds
   of query→relevant-set pairs, not 5) — the actual blocker to any
   Recall@K claim being trustworthy.
2. Auto-wire indexing into the existing Spam/Category/Routing pipeline so
   FR-43's "every processed email" is literally true, not just possible.
3. Real auth landing, so `organization_id` scoping becomes an actual
   access-control boundary, not just a structural one.
4. Load testing at realistic corpus size before any FR-45 P95/P99 claim.
5. A decision, backed by more evidence than a 6-pair qualitative check, on
   whether TF-IDF's speed advantage is worth its demonstrated paraphrase-
   blindness for this project's actual traffic patterns — or whether
   MiniLM should become the default.
