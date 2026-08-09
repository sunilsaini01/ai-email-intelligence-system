# Phase 1 Architecture Decisions

## What This Phase Establishes

A **modular monolith**: one deployable FastAPI process, internally organized
into clearly separated layers (`api` / `services` / `models` / `schemas` /
`database`), with no inter-service network calls, no message queue, no
orchestration framework.

## Why Modular Monolith Now, Not Microservices

A service boundary should be drawn where you have evidence of an independent
scaling or deployment need. At Phase 1, there is zero production traffic and
zero load data — any service boundary drawn now is a guess, and guessed
boundaries usually don't match real bottlenecks later. The cost of guessing
wrong with microservices is high: network calls where a function call used to
be, serialization overhead, partial-failure handling, distributed tracing
just to debug a single request.

The modular monolith keeps the *internal* boundaries (so extraction later is
a refactor, not a rewrite) without paying the *operational* cost upfront.

**Concrete extraction path, when it's warranted:** the `services/` layer is
deliberately the seam. A future "Spam Detection Service" extraction means:
move `services/spam/` to its own process, replace the in-process function
call with an HTTP/Kafka call at the orchestrator boundary, keep the
`schemas/` contract unchanged. That's a clean cut specifically because the
layering exists now.

## What Is Explicitly Deferred (and why)

| Deferred | Reason |
|---|---|
| Kafka / message queue | No async multi-step pipeline exists yet — a queue with one producer and one consumer is pure overhead |
| Kubernetes | No deployment to orchestrate yet; docker-compose covers single-node local + early demo needs |
| Multi-agent orchestrator | Premature — there is exactly one "agent" (this API) right now |
| Vector DB / RAG | No embeddings being generated yet (that's Phase 9 in the PRD) |
| Real auth (OAuth2/JWT) | `SECRET_KEY` placeholder exists in config; wiring real auth before there's anything to protect is wasted motion |

## Layer Responsibilities

```
Request → api/ (HTTP shape) → services/ (business logic) → models/ (DB shape)
                ↓
           schemas/ (validation, both directions)
```

- `api/`: routing, status codes, request/response wiring only. No business logic.
- `services/`: business logic, framework-agnostic. Should be testable without
  spinning up HTTP.
- `models/`: SQLAlchemy ORM — the DB's shape.
- `schemas/`: Pydantic — the API's shape. Deliberately decoupled from `models/`
  so a DB column can exist without being exposed, and an API field can be
  computed without a matching column.
- `core/`: settings, logging — cross-cutting, imported everywhere, owns nothing else.
- `database/`: connection/session lifecycle only.
- `middleware/`: cross-request concerns (logging, error shape) that must
  apply uniformly regardless of route.

## Liveness vs. Readiness — Why Two Endpoints

`/health` never touches the database — it answers "is this process alive,"
which an orchestrator uses to decide whether to restart the container.
`/health/ready` checks the DB — it answers "can this instance serve traffic
right now," which a load balancer uses to decide whether to route to it.

Collapsing these into one endpoint is a real failure mode: if `/health` pings
the DB and the DB has a brief outage, every instance fails liveness
simultaneously and gets restarted — turning a transient DB blip into a full
application outage via self-inflicted restart storm. Verified in this repo:
with no Postgres running, `/health` still returns `200 ok` while
`/health/ready` correctly reports `degraded`.

## Known Gaps at End of Phase 1 (intentional)

- No authentication/authorization yet.
- No real database migrations (Alembic) — added when the first model exists.
- No CI pipeline yet (GitHub Actions comes with the first real feature, so
  there's something worth gating).
- `SECRET_KEY` is a placeholder — must be replaced before any non-local use.

## Module Architecture Docs (added as each module landed)

This file stays the Phase 1 foundation record; each ML module gets its own
architecture doc rather than growing this one indefinitely:

- [`architecture_spam_detection.md`](architecture_spam_detection.md) — Phase 3, spam detection (the `services/` extraction seam described above, exercised for the first time).
- [`architecture_priority_classification.md`](architecture_priority_classification.md) — Phase 4, priority classification. **Read [`data_audit_priority.md`](data_audit_priority.md) first** — this module's data status (synthetic, not PRD-compliant) gates how every metric in it should be read.
- [`architecture_email_categorization.md`](architecture_email_categorization.md) — Phase 5, email categorization (multi-label). **Read [`data_audit_categorization.md`](data_audit_categorization.md) first**, same reason as priority — synthetic, not PRD-compliant. Also documents a real cross-module incident: extending the shared `ContentFeatures` extractor broke priority's already-trained artifact, requiring a retrain (see that doc's "Incident" section).
- [`architecture_email_summarization.md`](architecture_email_summarization.md) — Phase 6, email summarization (extractive + abstractive). **Read [`data_audit_summarization.md`](data_audit_summarization.md) first** — real, human-written reference summaries, but news, not email. Introduces this codebase's first generation-task module (`app/nlp/`, not the classification pipeline shape) and its first `torch`/`transformers` dependency. See `docs/phase6_requirements_traceability.md` for the full PRD extraction and `docs/technical_debt/database_write_hang.md` for this phase's DB-write-hang root-cause investigation.
- [`architecture_sentiment.md`](architecture_sentiment.md) — Phase 7A, sentiment analysis. **Read [`data_audit_sentiment.md`](data_audit_sentiment.md) first** — no human-labelled email sentiment data exists at all; the served model (VADER) is a zero-shot lexicon scorer, not trained on anything, unvalidated on email domain. The first module with no trained artifact whatsoever. Also fixed a pre-existing DB-metadata registration gap affecting Category/Summary (see that doc's "Database" section). See `docs/phase7a_requirements_traceability.md` for the full PRD extraction and `docs/error_analysis_sentiment.md` for characterized failure modes.
- [`architecture_intent.md`](architecture_intent.md) — Phase 7B, intent detection (multi-label). **Read [`data_audit_intent.md`](data_audit_intent.md) first** — no human-labelled email intent data exists at all (confirmed independently, matching the PRD's own "custom annotation required" statement); trained on a keyword-heuristic synthetic bootstrap, same pattern as priority/category. See `docs/error_analysis_intent.md` for a concrete, root-caused reliability failure (the Escalation class fires on unrelated text and misses its own target case) — stronger, more specific evidence than the generic synthetic-data disclaimer. Deliberately maintains zero coupling to the Sentiment module. See `docs/phase7b_intent_requirements_traceability.md` for the full PRD extraction.
- [`architecture_routing.md`](architecture_routing.md) — Phase 8, the email routing engine (a decision layer over five existing signals, not a trained model — the first module to call more than one upstream ML service together). **Read `docs/routing_signal_reliability.md` first** — a routing decision can never be more trustworthy than its weakest input, and four of the five signals it composes carry their own disclosed data-quality caveats. See `docs/error_analysis_routing.md` for a real, high-priority finding discovered this phase: the Spam model's recall-tuned threshold, evaluated on spam/ham corpora, over-fires on ordinary business email and quarantines most of a qualitative test sample before department routing even runs. See `docs/phase8_requirements_traceability.md` for the full PRD extraction.
