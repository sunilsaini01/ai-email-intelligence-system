# Workflow State (Module 13 / Phase 12, FR-63)

## Why Postgres, Not Kafka, Is the System of Record

The master prompt is explicit: "Do not rely exclusively on Kafka messages
as durable workflow state." Kafka topics in this design have short,
transport-only retention (`docs/kafka_architecture.md`) — they answer "what
happened, in order, recently," not "what is true right now, forever."
`GET /api/v1/workflows/{job_id}` reads exclusively from Postgres,
never replays Kafka.

## Tables

### `workflow_executions`

One row per `POST /api/v1/email/process` call.

| Column | Notes |
|---|---|
| `id` | == `job_id` everywhere else in this system |
| `organization_id` | Caller-supplied, unauthenticated — same standing trust model as every other module since Phase 1 |
| `email_id` | Nullable. Set only once retrieval indexing succeeds (`app/agents/orchestrator.py`'s `_finalize_workflow`) — NULL is a legitimate, disclosed "indexing hasn't happened yet / failed" state, not an error to hide |
| `status` | `PENDING → RUNNING → COMPLETED \| FAILED \| PARTIAL` |
| `started_at` / `completed_at` | `completed_at` is NULL until a terminal status is reached |

**Status semantics**:
- `COMPLETED` — every dispatched agent succeeded AND indexing succeeded.
- `PARTIAL` — at least one dispatched agent failed (exhausted retries),
  but indexing still succeeded (Routing degrades gracefully to
  "unavailable" for a failed signal, same as it already did before Phase
  12 — see `app/services/routing_service.py`'s pre-existing
  `unavailable`-list behavior).
- `FAILED` — indexing itself failed (no canonical email record could be
  persisted). Mirrors `app/api/v1/endpoints/retrieval.py`'s own stance:
  "if it fails to write, there is no decision to return at all."

### `agent_executions`

One row per `(workflow_id, agent_name)` — NOT one row per Kafka message or
per retry attempt (see `app/models/agent_execution.py`'s module
docstring for why: FR-66's retries happen inside one handler invocation,
tracked via `attempt_count` on this single row, not a series of rows).

| Column | Notes |
|---|---|
| `event_id` | The triggering `*.requested` event's id |
| `status` | `PENDING → RUNNING ⇄ RETRYING → COMPLETED \| FAILED` |
| `attempt_count` | Incremented on every attempt, including the first |
| `duration_ms` | Of the FINAL (successful or exhausted) attempt only |
| `error_type` / `error_message` | `"transient"` \| `"permanent"`; never raw email content (see `app/core/logging.py`'s PII discipline, applied identically here) |
| `model_version` | From the wrapped service's own response — same value the pre-existing `*/predict` endpoints already return |

**Unique constraint**: `(workflow_id, agent_name)` — this IS the
idempotency primitive (`docs/agent_contracts.md`, `docs/retry_strategy.md`).

## What `GET /workflows/{job_id}` Answers

Directly maps to every question the master prompt requires answerable:

- "Which agents completed / failed / pending?" — `agents[].status` per row.
- "How many retries occurred?" — `agents[].attempt_count`.
- "What is the current workflow status?" — `status`.
- "When did execution start/finish?" — `started_at`/`completed_at`.

## Migration

`backend/alembic/versions/e2f5b8c31a94_phase12_multi_agent_schema.py`.
Verified via a real disposable Postgres 16 container: upgrade → downgrade
→ upgrade round-trip, plus a genuine ORM insert/read/update round-trip
against both tables including the idempotency `get_or_create` guarantee
(same verification convention every prior phase's migration used).
