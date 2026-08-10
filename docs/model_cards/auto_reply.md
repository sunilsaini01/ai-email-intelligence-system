# Model Card — Auto-Reply Generation (Phase 10)

> **No Human Acceptance Rate data exists anywhere in this project.**
> Every metric in this document is either a component-level measurement
> (latency), a real-but-small manual sanity check (5 hand-written cases,
> read by the author, real Groq output), or explicitly marked NOT YET
> MEASURED — never presented as production ML validation. See
> "Evaluation" below and `docs/rag_evaluation_auto_reply.md`.

## Model Details

| Field | Value |
|---|---|
| Approach | RAG: retrieve up to 3 similar RESOLVED past emails (Phase 9's own retrieval, reused), construct a strictly-delimited prompt, generate a draft via a third-party LLM |
| LLM provider | Groq — project-owner decision, not the PRD's own OpenAI/Anthropic suggestion (see `docs/architecture_auto_reply.md` "LLM Provider Decision") |
| LLM model | `llama-3.3-70b-versatile` |
| Retrieval embedder | all-MiniLM-L6-v2 (Phase 9's own default, changed from TF-IDF specifically to support this module — see `docs/architecture_auto_reply.md` "Embedder Decision") |
| Served via | `POST /api/v1/reply/generate`, review via `/reply/{id}/approve\|edit\|reject` |
| Training data | None — this module trains nothing; the LLM is a fixed, third-party, pre-trained model this project does not fine-tune |

## Why Groq, Not the PRD's Own OpenAI/Anthropic Suggestion

Confirmed explicitly with the project owner before implementation, not
assumed or silently substituted. Groq's own rate-limit documentation was
verified directly (not guessed) before configuration: limits are
per-organization, not per-key — multiple keys from the same account do
not multiply throughput. See `docs/architecture_auto_reply.md` for the
full record.

## A Real Bug Found and Fixed During This Phase's Own Testing

Running the real end-to-end path (real Postgres, real Groq API) — not
just the mocked unit test suite — exposed a genuine performance bug unit
tests could not have caught: `RetrievalService`'s default embedder/vector
store were being reconstructed on every call, costing ~1.4s/request once
MiniLM became the default. Found, root-caused, and fixed before being
relied on anywhere; re-measured directly to confirm the fix. See
`docs/error_analysis_auto_reply.md` and
`docs/phase10_requirements_traceability.md` "Measured Latency."

## Composed Signal Summary

Auto-Reply does not classify or train anything — it composes Phase 9's
retrieval (inherits its own data-quality caveats, most notably: real
`RESOLVED` context is likely rare in this system's current state — see
`docs/architecture_auto_reply.md` "Resolved-Email Data Reality"), Presidio
PII anonymization (re-applied here for a new obligation Phase 9 didn't
cover — see that doc's "PII" section), and Groq's `llama-3.3-70b-versatile`
(a third-party model with its own, unmeasured-by-this-project failure
modes — hallucination, refusal, inconsistent tone).

## Intended Use

- **Draft-assistance infrastructure validation** — proves the full
  retrieve → anonymize → prompt → generate → persist → human-review
  pipeline works end-to-end, with real Postgres and a real LLM call
  verified directly, not just mocked.
- **Not validated for production draft-quality decisions.** No Human
  Acceptance Rate data exists; the qualitative script
  (`scripts/qualitative_eval_auto_reply.py`) is a diagnostic tool a human
  reads, not evidence of real-world draft usefulness.
- **Never a substitute for human judgment** — FR-49/FR-51 are structural,
  not just policy: no code path in this pipeline can send anything.

## Evaluation

**No Human Acceptance Rate/Edit Rate/Rejection Rate is reported as a
trustworthy production metric** (RULE — never fabricate evaluation
metrics), because no real agent has reviewed any draft this system has
produced yet. What was measured instead, classified honestly:

| Evaluation type | What was checked | Where |
|---|---|---|
| Component + end-to-end latency | Real Postgres + real Groq API, cold and warm, verified against FR-50's 10s budget | `docs/phase10_requirements_traceability.md` "Measured Latency" |
| Real API call verification | 5 hand-written cases (refund w/ context, refund w/o context, vague question, injection attempt, sensitive PII), real Groq output read directly | `scripts/qualitative_eval_auto_reply.py` |
| PII never reaches the LLM prompt raw | Unit-verified directly (current email AND retrieved context) | `tests/test_auto_reply_service.py` |
| Prompt injection pre-filter | Unit + end-to-end (real API call skipped entirely on match) | `tests/test_reply_prompt.py`, `tests/test_auto_reply_security.py` |
| No-send architectural guarantee | Static AST check — no mail-transport import anywhere in the pipeline | `tests/test_auto_reply_security.py::test_no_email_sending_capability_exists_in_the_reply_pipeline` |
| Failure isolation | Timeout/provider-error/retrieval-failure all produce a persisted, clearly-flagged FAILED draft, never a silent success | `tests/test_reply_endpoint.py` |
| Real Postgres migration | Upgrade/downgrade/upgrade round-trip, real insert, real constraint/default verification | Manual verification, this phase |
| Human acceptance | **NOT YET MEASURED** — requires real agents and real traffic | — |

## Limitations

1. **No production draft-quality evidence exists** — the PRD's own
   implied quality bar (Human Acceptance Rate > 60%) is untested against
   real usage.
2. **Real historical context is likely rare in practice** — inherited
   from Phase 9's `resolution_status` never auto-transitioning. Most
   drafts today will be generated under `NO_SIMILAR_EMAILS`, grounded
   only in the current email.
3. **Third-party LLM, not validated by this project** — hallucination,
   refusal, tone inconsistency, and factual errors are all possible and
   not measured here beyond the small qualitative sample.
4. **Injection defense is prompt-level and heuristic**, not a formal
   guarantee — see `docs/security_auto_reply.md`.
5. **No load testing** — real, warm-process latency is good; concurrent
   behavior at realistic traffic is unmeasured.
6. **Ollama fallback exists but has its own disclosed latency risk** — a
   Groq 429/503 now falls back to a locally-running Ollama server rather
   than failing outright, but a real, measured cold-start on that
   fallback path (~11s to load a model) can by itself exceed FR-50's 10s
   budget; no pre-warming was built for it. See
   `docs/architecture_auto_reply.md` "Ollama Fallback."
7. **Inherits every upstream caveat** Phase 9's retrieval and Phase 5/8's
   category/department already carry (synthetic labels, not PRD-compliant
   — see those modules' own data audits) for any category/department
   value referenced in a generated draft's context.

## Path to Production-Validated Auto-Reply (Not Implemented — Blocked on Real Usage)

1. Real agents using the approve/edit/reject endpoints against real
   traffic — the actual blocker to any Human Acceptance Rate claim being
   trustworthy.
2. Closing Phase 9's own `resolution_status` gap (some real workflow that
   marks emails resolved) so real historical context becomes the common
   case rather than the exception.
3. Real auth landing, so `reviewer_id`/`organization_id` become actual
   access-control boundaries, not just structural ones.
4. Load testing at realistic concurrency before any FR-50 P95/P99 claim
   beyond the single-request numbers measured here.
5. Pre-warming Ollama's fallback model at startup, the same way
   `RetrievalService`'s embedder/vector-store are warmed — not built yet;
   the ~11s cold-start finding above is the concrete evidence that would
   justify it.
