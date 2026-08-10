# Multi-Agent Architecture (Module 13 / Phase 12)

> Read `PHASE_12_AUDIT_REPORT.md` first for the audit this design is
> based on. This doc is the as-built record; that one is the pre-
> implementation plan (kept, not deleted, so the "what we planned" vs.
> "what shipped" trail stays visible — same convention every prior
> phase's audit report followed).

## Architecture Before Phase 12

```
Caller → FastAPI endpoint → Service (in-process call) → ML artifact / DB
```

Every module (spam, priority, category, sentiment, intent, summarization,
routing, retrieval, auto-reply) was invoked independently by an external
caller. `RoutingService` was the one exception — it composed 5 services
in-process — but was itself still called synchronously, not triggered by
an event. **No entrypoint existed for "a new email arrived and needs
processing"** — this is the headline finding from the Phase 12 audit that
shaped everything below.

## Architecture After Phase 12

```
Caller → POST /api/v1/email/process → workflow_executions row (PENDING)
                                     → email.processing.requested published
                                     → 202 Accepted, {job_id, status}

Orchestrator (app/agents/orchestrator.py, one Kafka consumer):
  consumes email.processing.requested
    → dispatches spam.requested + summarization.requested (parallel, no deps)
  consumes {module}.completed / {module}.failed
    → once spam resolves: if not is_spam, dispatches priority/category/
      sentiment/intent.requested (R-SPAM-GATE, mirrors RoutingService's
      own existing gate)
    → once every dispatched module has reported:
        - RoutingService.route(precomputed_*) -- reuses agent results,
          no re-inference
        - Retrieval indexing (in-process, mirrors retrieval.py's own
          index_email sequence)
        - workflow_executions row finalized (COMPLETED/PARTIAL/FAILED)
        - workflow.completed published

Specialist Agents (app/agents/{module}_agent.py, one Kafka consumer each):
  consume {module}.requested
    → idempotency check (agent_executions unique on workflow_id+agent_name)
    → call the EXISTING, unmodified service (SpamService.classify(), etc.)
    → retry up to AGENT_MAX_ATTEMPTS with exponential backoff (FR-66)
    → publish {module}.completed or {module}.failed (+ DLQ on exhaustion)
    → structured log per lifecycle transition (FR-67)

GET /api/v1/workflows/{job_id} → reads workflow_executions +
                                  agent_executions (Postgres, durable)
```

## Component Responsibilities

| Component | Responsibility |
|---|---|
| `app/messaging/` | Topic names, versioned message schemas, producer/consumer wrappers, retry/backoff policy. Transport layer only — no business logic. |
| `app/agents/base.py` | Everything common to every specialist agent: idempotency, retry loop, DB state transitions, structured logging, publishing completed/failed/DLQ. |
| `app/agents/{module}_agent.py` | One per ML module. Thin — supplies `agent_name` and calls the existing service. No ML logic. |
| `app/agents/orchestrator.py` | Dependency graph, dispatch, result correlation, Routing/Retrieval invocation, workflow finalization. Contains NO ML logic of its own. |
| `app/agents/runner.py` | Process entrypoint (`python -m app.agents.runner`) — runs all 7 consumers (6 agents + orchestrator) as concurrent asyncio tasks in one process. |
| `workflow_executions` / `agent_executions` (Postgres) | Durable system of record — NOT reconstructed from Kafka. |
| Kafka | Transport only, short retention. Never the source of truth for "what happened." |
| `docs/dashboard_*` (Phase 11, unchanged) | Feedback/correction-rate concerns remain entirely separate from agent-execution reliability concerns — no overlap, no merge. |

## Scope Boundary

**In scope**: Spam, Priority, Category, Sentiment, Intent, Summarization
become independent Kafka agents (FR-64's literal "ML Specialist Agents"
list). Routing and Retrieval indexing are invoked in-process by the
Orchestrator, reusing their existing composition logic with zero
duplicated ML inference (see `docs/kafka_architecture.md` "Why Routing/
Retrieval/Auto-Reply Are Not Kafka Agents").

**Out of scope, deliberately**: Auto-Reply generation is **not**
auto-triggered by the pipeline. `AutoReplyService.generate()` makes a
real, billed Groq API call — wiring it into every processed email without
being asked would silently and significantly increase real API spend and
external-service dependency, which is not an FR-63–67 requirement. Auto-
Reply remains reachable only through its existing, explicit
`/reply/generate` endpoint.

## Reuse Ledger (what changed vs. what didn't)

| Existing code | Change |
|---|---|
| `SpamService`, `PriorityService`, `CategoryService`, `SentimentService`, `IntentService`, `SummarizationService` | **Unchanged.** Called by agents exactly as they were already called by `*/predict` endpoints. |
| `RoutingService.route()` | **Additive.** Five new keyword-only `precomputed_*` params, defaulted to a sentinel that preserves 100% of prior behavior when omitted. See `app/services/routing_service.py`. Verified: all 60 pre-existing routing tests pass unchanged. |
| `EmailRepository`, `RetrievalService.index_email()` | **Unchanged.** The Orchestrator's indexing step mirrors `app/api/v1/endpoints/retrieval.py`'s own call sequence rather than sharing a new abstraction — same "each orchestration point keeps its own short, mirrored sequence" precedent `app/api/v1/endpoints/reply.py`'s `_fetch_resolved_context` already set. |
| `app/core/logging.py` | **Unchanged.** Reused as-is for FR-67's structured agent logs — no second logging framework. |
| Every existing `*/predict`, `*/feedback`, `*/route`, `retrieval/*`, `reply/*`, `dashboard/*` endpoint | **Unchanged contracts.** Verified: the full pre-existing 461-test suite passes unmodified. |

## Known, Disclosed Limitations

1. **No per-workflow timeout for a silently-missing agent.** If an
   expected agent never publishes `*.completed` or `*.failed` at all (as
   opposed to publishing `*.failed`, which finalizes the workflow
   normally), the workflow stays `RUNNING` indefinitely. A real fix needs
   a scheduled sweep job this codebase has no scheduler for yet. See
   `docs/failure_handling.md`.
2. **Orchestrator state is process-local.** `_pending` (in-flight
   workflow tracking) is an in-memory dict, lost on restart — same
   disclosed single-process limitation Phase 11's `DashboardBroadcaster`
   already carries. `workflow_executions`/`agent_executions` in Postgres
   are unaffected by an orchestrator restart; only workflows that were
   mid-flight at the moment of restart are affected (they stay `RUNNING`
   forever, same failure mode as #1).
3. **One process runs all 7 consumers.** See `app/agents/runner.py`'s
   module docstring — a deliberate scale decision for this project's
   current (zero production traffic) status, not a ceiling: each agent
   already has its own Kafka consumer group, so splitting into separate
   processes/containers later is an infrastructure change, not a
   rewrite.
4. **Model evidence quality is unchanged.** Per Critical Rule #17 and the
   master prompt's own section 23: running Priority/Category/Intent as
   Kafka agents does not improve their underlying synthetic-data
   evidence status. See `docs/model_evidence_policy.md` (Phase 11,
   unchanged) — the same 5-badge vocabulary still applies; nothing here
   claims a production-accuracy upgrade.
