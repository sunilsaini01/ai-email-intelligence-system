# Phase 12 Audit Report — Multi-Agent Architecture (FR-63–67)

> Stage 1–4 deliverable (audit, traceability, architecture design). Written
> before any implementation code, per the Phase 12 master prompt's explicit
> gate. Checked against the real repository as it stands after Phase 11
> (461/461 backend tests passing), not assumed from the PRD alone.

## 1. Executive Summary

Phases 1–11 built a **modular monolith**: one FastAPI process, six ML
modules (spam/priority/category/sentiment/intent/summarization) plus
routing, retrieval/RAG, auto-reply, and a dashboard/feedback layer — all
composed via **direct in-process Python calls**, never HTTP, never a
queue. This was a deliberate Phase 1 decision (`docs/architecture.md`
"What Is Explicitly Deferred"), restated at the top of the README, and
held for 11 straight phases.

FR-63–67 requires reversing that decision: an Orchestrator Agent, per-module
independent agents, Kafka-based async messaging, retry/backoff, structured
agent logs. This audit's job is to determine what that reversal actually
costs this specific codebase, not a generic one.

**Headline finding not visible from the PRD text alone**: this codebase has
**no existing entrypoint that represents "a new email arrived and needs
processing."** Every module today is invoked independently, by whatever
external caller decides to hit `/spam/predict`, then separately
`/priority/predict`, then separately `/routing/route`, etc. `RoutingService`
(`app/services/routing_service.py`) is the closest thing to an orchestrator
that exists — it calls five services in-process and does per-signal failure
isolation — but nothing calls *it* automatically, and nothing chains it to
retrieval/indexing or auto-reply. Building FR-63's Orchestrator Agent
therefore also means **inventing the top-level trigger that doesn't exist
yet** (`POST /api/v1/email/process`), not just re-wiring an existing one.
This is real, necessary scope — not scope creep — but it's worth being
explicit that Phase 12 is building a new capability, not merely relocating
an old one.

## 2. What Can Be Reused (verified by reading the actual code)

| Existing asset | Reuse plan |
|---|---|
| `SpamService`, `PriorityService`, `CategoryService`, `SentimentService`, `IntentService`, `SummarizationService` (`app/services/*_service.py`) | Wrapped by agents, **unchanged**. Agents call the existing `.classify()`/`.analyze()` methods — no ML logic is duplicated or reimplemented, per Critical Rule #6. |
| `RoutingService._safe_call` per-signal failure isolation pattern | Directly informs the agent execution-lifecycle error model (transient vs. permanent, never a crashed workflow). |
| `feedback_events` / `retraining_triggers` (Phase 11) | Untouched. Agent executions are a different concern (system reliability) from feedback (model correctness) — no overlap, no merge. |
| `app/core/logging.py` structured JSON logger | Reused as-is for agent execution logs (FR-67) — **no second logging framework**, per Critical Rule #7. |
| Existing `*/predict` and `*/feedback` REST endpoints | **Unchanged contracts.** Callers who use them synchronously today keep working exactly as before (PRD §17 requirement). |
| `docker-compose.yml`'s healthcheck-gated `depends_on` pattern | Reused for the new Kafka service so the API/consumers don't race a not-yet-ready broker, same reasoning already documented for Postgres. |
| Existing Alembic migration + disposable-Postgres-container verification convention | Reused unchanged for the new `agent_executions`/`workflow_executions` tables. |
| Per-test SQLite (aiosqlite) pattern (`backend/tests/conftest.py` + per-file DB overrides) | Reused for workflow-state DB tests. **Cannot** be reused for Kafka itself — SQLite has no async-broker equivalent; see §9 Testing Strategy. |

## 3. What Must Be Extracted / Newly Built

- **Orchestrator Agent** — does not exist in any form today. New.
- **Agent execution wrappers** (one per ML module) — new thin layer;
  `RoutingService` already proves the "call the real service, shape
  input/output" pattern this will follow.
- **`POST /api/v1/email/process`** — new API surface, additive (existing
  endpoints untouched). Returns a `job_id` immediately; a separate `GET
  /api/v1/workflows/{job_id}` exposes status (PRD §17's own suggested shape).
- **Kafka infrastructure** — genuinely new to this repository (see §10).
- **`messaging/` layer** (producer, consumer, topic definitions, versioned
  message schemas, retry/backoff helper) — new.
- **Workflow/agent-execution state tables** — new (see §6).
- **Dead-letter handling** — new.

## 4. What Must Remain Synchronous

- All 12 existing `*/predict`, `*/feedback`, `*/route`, `retrieval/*`,
  `reply/*`, `dashboard/*` endpoints. A caller hitting `POST
  /spam/predict` today gets a synchronous response today and must
  continue to after Phase 12 — nothing about FR-63–67 requires breaking
  that, and PRD §17 explicitly forbids it.
- Routing's five-signal composition *inside* `RoutingService` itself stays
  in-process — Kafka topics exist between agents/orchestrator, not as a
  replacement for `RoutingService`'s own already-correct internal
  composition.

## 5. PRD Traceability Matrix (design stage — nothing implemented yet)

| Req | Design | Implementation | Test | Evidence |
|---|---|---|---|---|
| FR-63 (Orchestrator Agent) | §6 below | Not started | Not started | — |
| FR-64 (independent per-module agents) | §7 below | Not started | Not started | — |
| FR-65 (Kafka async messaging) | §8–9 below | Not started | Not started | — |
| FR-66 (retry ×3, exponential backoff) | §11 below | Not started | Not started | — |
| FR-67 (structured agent execution logs) | §12 below | Not started | Not started | — |

This table is intentionally all "Not started" — per the master prompt's own
Definition of Done, no requirement is marked complete without real
implementation, real tests, and real evidence, none of which exist yet.

## 6. Architecture Evolution

**Before (Phases 1–11, current state):**

```
Caller → FastAPI endpoint → Service (in-process call) → ML artifact / DB
```

No cross-module chaining happens automatically. `RoutingService` is the one
exception (composes 5 services), but it is itself still called synchronously
by a caller, not triggered by an event.

**After (Phase 12, proposed):**

```
Caller → POST /api/v1/email/process → EmailRecord persisted (PENDING)
                                     → Orchestrator publishes email.processing.requested
                                     → job_id returned immediately (202 Accepted)

Kafka topics (see §8)
    Orchestrator ──publishes──> {module}.requested topics
    Specialist Agents ──consume {module}.requested, call the EXISTING
                          service, publish {module}.completed/{module}.failed
    Orchestrator ──consumes {module}.completed/failed, updates workflow
                    state, decides next step (parallel/sequential per §9),
                    publishes workflow.completed when done

GET /api/v1/workflows/{job_id} → reads workflow_executions + agent_executions
                                  (Postgres, durable — NOT reconstructed from
                                  Kafka messages; see §6.1)
```

### 6.1 Where workflow state lives

Per the master prompt's explicit instruction ("Do not rely exclusively on
Kafka messages as durable workflow state"): **Postgres**, via two new
tables, using the same Alembic + disposable-container verification
convention as every prior phase:

- `workflow_executions` — one row per `POST /email/process` call. Columns:
  `id (job_id)`, `organization_id`, `email_id` (FK-equivalent to `emails.id`
  once indexed), `status` (`PENDING/RUNNING/COMPLETED/FAILED/PARTIAL`),
  `started_at`, `completed_at`, `correlation_id`.
- `agent_executions` — one row per agent's attempt at one task within one
  workflow. Columns: `id`, `workflow_id` (FK), `agent_name`, `event_id`,
  `status` (`PENDING/RUNNING/COMPLETED/FAILED/RETRYING`), `attempt_number`,
  `started_at`, `completed_at`, `duration_ms`, `error_type`, `error_message`
  (never raw email content — see §12), `model_version`.

This directly answers the master prompt's required questions ("which
agents completed / failed / pending", "how many retries", "current
status") from one join, without replaying Kafka.

## 7. FR-64 — Specialist Agents (design)

One agent per existing ML module: Spam, Priority, Category, Sentiment,
Intent, Summarization. Each is a thin consumer that:

1. Consumes its `{module}.requested` topic message.
2. Calls the **existing, unmodified** service method
   (`SpamService.classify()`, etc.) — this is the Critical Rule #6
   boundary: agents are execution wrappers, not a second copy of model
   logic.
3. Writes an `agent_executions` row (start/end/status/duration).
4. Publishes `{module}.completed` (success) or `{module}.failed`
   (exhausted retries — see §11).

Routing, RAG/retrieval, and Auto-Reply are **not** given their own
top-level agents in this design — they are downstream **consumers of the
classification agents' results**, invoked by the Orchestrator after the
relevant upstream `{module}.completed` events land, reusing
`RoutingService`'s existing internal composition rather than re-inventing
it as five separate Kafka round-trips (that would add five hops of latency
for zero behavioral benefit, since `RoutingService` already does correct
in-process composition). Open question — flagged in §14.

## 8. FR-65 — Kafka Topics (design)

| Topic | Producer | Consumer | Purpose |
|---|---|---|---|
| `email.processing.requested` | API (`/email/process`) | Orchestrator | Kick off a workflow |
| `email.spam.requested` / `.completed` / `.failed` | Orchestrator / Spam Agent | Spam Agent / Orchestrator | Spam classification round-trip |
| `email.priority.requested` / `.completed` / `.failed` | same pattern | same pattern | Priority |
| `email.category.requested` / `.completed` / `.failed` | same pattern | same pattern | Category |
| `email.sentiment.requested` / `.completed` / `.failed` | same pattern | same pattern | Sentiment |
| `email.intent.requested` / `.completed` / `.failed` | same pattern | same pattern | Intent |
| `email.summary.requested` / `.completed` / `.failed` | same pattern | same pattern | Summarization |
| `agent.failed` | any agent, after retries exhausted | Orchestrator, DLQ consumer | Terminal failure signal |
| `workflow.completed` | Orchestrator | (future consumers — dashboard, etc.) | Whole-pipeline done |
| `*.dlq` (one per requested topic, or one shared `email.processing.dlq`) | Consumer, on final failure | Manual/ops inspection | Dead-letter (see §11) |

- **Partitioning**: key by `email_id` — guarantees all events for one email
  land on the same partition, giving per-email ordering without needing
  global ordering.
- **Consumer groups**: one group per agent type (e.g. `spam-agent-group`)
  so multiple agent replicas can scale horizontally later without design
  changes now.
- **Delivery semantics**: at-least-once (Kafka's practical default without
  exactly-once transactions, which this scope doesn't need) — this is
  *why* §9 idempotency is mandatory, not optional.
- **Retention**: short (24–72h) for `*.requested`/`*.completed` — these are
  transport, not the system of record (Postgres is, per §6.1). Longer
  retention only on the DLQ topics for operator investigation.

## 9. Message Contracts (design)

Versioned Pydantic schemas (reusing this codebase's existing schema
discipline from `app/schemas/`), not raw dicts (Critical Rule violation
otherwise):

```
event_id: UUID
job_id: UUID              # == workflow_executions.id
email_id: UUID
event_type: str            # e.g. "email.spam.requested"
agent: str | None
schema_version: str        # "1.0" — additive-only evolution
timestamp: datetime
correlation_id: UUID       # == job_id at top level; kept distinct in the
                            # schema so a future multi-workflow correlation
                            # case (not needed now) doesn't require a schema
                            # break
retry_count: int
payload: dict               # module-specific, e.g. {"subject": ..., "body": ...}
metadata: dict               # organization_id, reviewer_id-equivalent, etc.
```

## 10. Idempotency (design)

Kafka's at-least-once delivery means every agent must tolerate replays.
Design: `agent_executions` gets a **unique constraint on
`(workflow_id, agent_name, attempt_number)`** — actually, the real
duplicate-detection key is `(workflow_id, agent_name, event_id)` unique.
On consume, an agent first checks whether that `event_id` was already
recorded as `COMPLETED`; if so, it re-publishes the already-stored result
(from `agent_executions`) instead of re-running the ML call — cheap,
correct, and avoids double-counting anything downstream (e.g. Phase 11's
`feedback_events`/dashboard counts, which must not see phantom duplicate
predictions). This mirrors the exact check-then-insert pattern Phase 11
already used for the Review Queue's duplicate-confirm guard
(`docs/error_analysis_dashboard.md` #3) — same codebase convention, same
disclosed narrow race window (check-then-insert, not a fully atomic
constraint), not a new invented mechanism.

## 11. FR-66 — Retry & Dead-Letter (design)

- Max 3 attempts. Backoff: 2s → 8s → 32s (exponential, base 4 — tunable
  via a new `Settings` field, same pattern as Phase 11's
  `RETRAINING_FEEDBACK_THRESHOLD`).
- **Error classification** (required before deciding whether to retry at
  all): transient (network/timeout/Kafka unavailable) → retry; permanent
  (malformed payload, validation error) → **no retry**, straight to
  `agent.failed` — retrying a validation error 3 times wastes time and
  delays the DLQ signal for no benefit.
- After 3 failed attempts (transient) or immediately (permanent): publish
  to that topic's DLQ with the original event, failure reason, agent name,
  retry count, timestamps, correlation ID (master prompt §11's exact
  field list) — and write `agent_executions.status = FAILED`.
- Orchestrator, on `agent.failed`, marks the workflow `PARTIAL` or `FAILED`
  depending on whether the failed agent was required for a downstream step
  (see §9's dependency graph) — it does not silently continue as if
  nothing happened.

## 12. FR-67 — Structured Logging (design)

Reuses `app/core/logging.py` as-is. Every agent execution emits one
structured log line per lifecycle transition (start, complete, fail,
retry) with: `timestamp`, `job_id`, `event_id`, `correlation_id`, `agent`,
`event_type`, `duration_ms`, `status`, `retry_count`, `error_type`,
`error_message`, `model_version`. **Never** the email subject/body —
same PII discipline this file's own docstring already states
("Logging PII or full email bodies at INFO level... treat log statements
with the same PII discipline as any other data sink"), consistent with
Phase 9's `docs/phase9_pii_embedding_strategy.md` and Phase 11's
`docs/dashboard_security.md` PII stances.

## 13. Dependency Graph (design)

- **Parallel**: Spam, Priority, Category, Sentiment, Intent, Summarization
  have no dependencies on each other — all six `{module}.requested` events
  can be published by the Orchestrator immediately and processed
  concurrently. This mirrors `RoutingService`'s existing behavior, which
  already calls its five signals independently (not chained) — Phase 12
  doesn't change that reasoning, just moves the calls across a queue.
- **Conditional short-circuit**: if Spam returns `is_spam=True`, the
  Orchestrator should **skip** publishing Priority/Category/Sentiment/
  Intent — this exactly mirrors `RoutingService.route()`'s existing
  `if not is_spam:` gate (`app/services/routing_service.py` lines 81–97),
  which the docstring calls `R-SPAM-GATE`. Not reproducing this in the
  orchestrator would silently regress an already-shipped, already-tested
  optimization.
- **Sequential**: Routing depends on the classification agents' results
  (all of Spam/Priority/Category/Sentiment/Intent, or the subset the
  spam-gate left running). RAG/retrieval indexing depends on Routing's
  category/department output (matches `emails.category`/`department`
  being caller-supplied snapshots, per `app/models/email_record.py`).
  Auto-Reply depends on retrieval.
- Summarization has no consumers in this graph — it's independent, PRD-wise
  a standalone module, included only because it's parallel with no
  dependency implications.

## 14. Open Questions — Resolved

Three scope-defining decisions were confirmed before implementation:

1. **Kafka client: `aiokafka`.** Async-native, matches the existing fully-
   async FastAPI/SQLAlchemy stack; pure Python, avoiding another native
   build dependency on a machine that has already hit multiple documented
   native-dependency issues (torch, the `transformers`/`pyarrow` import-
   order crash in `app/main.py`).
2. **Broker: `apache/kafka`, KRaft mode, single container.** No
   Zookeeper. Simplest local footprint, consistent with this project's
   repeated real port-collision problems on this Windows dev machine
   (Postgres, port 8000) — fewer containers is directly lower risk here,
   not just simpler in the abstract.
3. **Agent scope: only the 6 ML classification modules become Kafka
   agents** (Spam, Priority, Category, Sentiment, Intent, Summarization —
   FR-64's literal "ML Specialist Agents"). Routing, Retrieval, and
   Auto-Reply remain in-process, invoked by the Orchestrator after
   classification completes, reusing their existing, already-tested
   composition logic (`RoutingService`'s 5-signal call, retrieval's vector
   search, auto-reply's LLM call) rather than adding 3 more topics and
   several more network hops of latency for logic with no independent
   scaling need today.

Implementation proceeds on this basis.

## 15. Technical Debt Classification (master prompt §24)

| Item | Classification | Reasoning |
|---|---|---|
| DB write hang on Windows (`docs/technical_debt/database_write_hang.md`) | **Not relevant to Phase 12 directly, but the SAME risk class applies to Kafka connections** — disclosed in §17 Security/Failure semantics, not silently fixed. Not re-investigated this phase (out of scope, per Critical Rule #15 "do not silently fix unrelated technical debt"). | Root cause still unconfirmed from Phase 6; unrelated subsystem. |
| Incomplete `requirements.txt` | **Not fixed.** Pre-existing, disclosed gap since Phase 6. Only Phase 12's own new dependency (`aiokafka` or equivalent) gets added. | Out of scope to reconcile historically-missing entries. |
| Missing authentication | **Not fixed.** Same standing gap since Phase 1. Kafka topics carry no new auth boundary either — documented as a limitation in the security review, not solved. | Project-wide gap, not a Phase 12 concern. |
| Missing real multi-tenancy enforcement | **Not fixed.** `organization_id` remains caller-supplied/unauthenticated, same as Phase 11 disclosed. | Same reasoning. |
| Synthetic labels (Priority/Category/Intent) | **Not relevant.** Per Critical Rule #17 and master prompt §23, running these as agents does not change model evidence quality — no claim of improvement will be made. | Explicitly a separate dimension. |
| Spam domain-transfer issue | **Not fixed.** Pre-existing, disclosed since Phase 8. Not a reliability/architecture concern Phase 12 addresses. | Model-quality issue, not infra. |
| Retrieval limitations | **Not fixed.** Out of scope. | Same reasoning. |
| Auto-Reply Human Acceptance Rate lack of data | **Not fixed.** Standing gap since Phase 10, restated in Phase 11's final report. | Same reasoning. |
| Frontend testing gaps | **Not fixed.** Phase 12 is backend/infra-only per the master prompt's own scope (no frontend section exists in the prompt). | Out of this phase's stated scope. |

None of these are blockers for Phase 12 reliability specifically — they're
listed here because the master prompt requires an explicit pass/classify,
not because any of them gate this phase.
