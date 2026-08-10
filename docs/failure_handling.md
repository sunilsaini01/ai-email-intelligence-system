# Failure Handling (Module 13 / Phase 12)

For each scenario: **Detection → Recovery → Persistence → Logging →
User-visible behavior.**

## Kafka Unavailable

- **At `POST /email/process` time**: `publish_event()` raises. The
  already-created `workflow_executions` row is marked `FAILED`
  (best-effort) and the endpoint returns **503**. No silent 202 for a
  workflow that was never actually dispatched.
- **At agent-consumer time**: the agent process's `consume_forever` loop
  cannot connect; `aiokafka` retries its own connection internally (its
  documented behavior) — no explicit handling needed here beyond what
  the library already does. User-visible: no new `*.completed`/`*.failed`
  events appear; any `workflow_executions` row awaiting that agent stays
  `RUNNING` (see "No Per-Workflow Timeout" below).

## Postgres Unavailable

- **Agent handler**: `AgentExecutionRepository` calls raise; caught by
  the SAME transient-error path every other exception in
  `run_ml_call`'s try/except goes through (`app/agents/base.py`) —
  classified `transient`, retried, eventually `FAILED`+DLQ if Postgres
  stays down through all attempts.
- **Orchestrator finalize step**: if the `workflow_executions`/
  `agent_executions` writes fail during `_finalize_workflow`, the
  exception propagates out of `handle_message` uncaught — per
  `app/messaging/consumer.py`'s documented stance, the message is NOT
  committed, so it redelivers on the next successful poll (Kafka's
  at-least-once semantics doing exactly what they're for here).

## Agent Crash Mid-Handler

Message was never committed (offset commit happens only after the
handler returns — `app/messaging/consumer.py`). On restart, the same
message redelivers. The idempotency check
(`AgentExecutionRepository.get_or_create`) sees the row is still
`PENDING`/`RUNNING` (not a terminal state) and reprocesses it from
scratch — the correct behavior, since the crash means no result was ever
published.

## Model Loading Failure

Same as every prior phase's existing `SpamServiceUnavailable`/
`PriorityServiceUnavailable`-style exceptions — classified `transient`
(unclassified exception default), retried up to `AGENT_MAX_ATTEMPTS`,
then `FAILED`+DLQ. A retry will not help if the artifact is genuinely
missing (not present at all vs. momentarily locked) — a known limitation
of the default-transient classification, disclosed rather than
special-cased, since this codebase has no reliable way to distinguish
"artifact missing forever" from "artifact momentarily unreadable" from
inside a generic exception handler.

## Malformed Event

`AgentEvent.from_kafka_value()` raises `pydantic.ValidationError` before
`handle_message`'s own try/except even begins — this is NOT currently
wrapped in the same retry path (it happens before `_execute_with_retry`
is ever called). **Disclosed gap**: a malformed message today causes
`consume_forever`'s outer `except Exception` to catch it, log
`consumer_handler_failed_message_not_committed`, and leave the message
uncommitted — meaning it will be retried indefinitely on every poll
without ever reaching the DLQ, since it never gets far enough into
`BaseAgent` to classify itself as `permanent`. This is a real limitation,
not yet closed this phase — see "Remaining Work" in
`PHASE_12_COMPLETION_REPORT.md`. Mitigation for now: this can only happen
from a producer bug (this codebase's own producers are schema-validated
before publish — `AgentEvent(...)` construction itself raises before
`publish_event` is ever called with bad data), not from an external,
untrusted producer, since nothing outside this codebase publishes to
these topics.

## Duplicate Event

FR-65's expected, normal case — not a failure. See
`docs/agent_contracts.md` "Idempotency Check." This applies to every
specialist agent's `*.requested` topic (via `AgentExecutionRepository.
get_or_create`'s terminal-status check) AND to the Orchestrator's own
`email.processing.requested` topic (via a `workflow.status == PENDING`
check in `_start_workflow`, added after a post-delivery review found the
Orchestrator was the one place in the pipeline missing this guard —
without it, a redelivered `email.processing.requested` could silently
reset an already-`COMPLETED` workflow back to `RUNNING` with no way to
ever re-finalize it. See `tests/test_orchestrator_idempotency.py` for the
reproduction and fix verification.)

## Timeout

- **Per-agent**: not a separate mechanism — a hung ML call simply
  occupies one attempt's worth of the retry budget; there is no explicit
  per-call timeout wrapping `run_ml_call` today (a disclosed gap — a
  genuinely hung underlying call, e.g. the same class of issue
  `docs/technical_debt/database_write_hang.md` documents for Postgres,
  could occupy an agent indefinitely). Not fixed this phase — out of
  scope per "do not silently fix unrelated technical debt," and a new
  instance of the SAME already-disclosed risk class, not a new one.
- **Per-workflow**: see "No Per-Workflow Timeout" below.

## Consumer Restart

Handled correctly by construction: `enable_auto_commit=False` +
commit-after-success means a restarted consumer resumes from its last
committed offset, redelivering anything in flight at the moment of
restart. Combined with idempotency, this is safe — see "Agent Crash
Mid-Handler" above (the same mechanism).

## Producer Failure

`publish_event`/`publish_dead_letter` raise on failure (no silent
swallow) — every caller (`POST /email/process`, `BaseAgent.handle_message`,
the Orchestrator) either propagates this as an HTTP 503 (the endpoint) or
lets it surface via the uncommitted-message path described above (agents/
orchestrator).

## Partial Workflow Completion

This is `PARTIAL` status, a first-class outcome, not an error state — see
`docs/workflow_state.md` "Status semantics."

## Retry Exhaustion

See `docs/retry_strategy.md` "After Retries Are Exhausted."

## No Per-Workflow Timeout (Disclosed Limitation)

If an expected agent's `*.requested` message is simply never consumed at
all (as opposed to being consumed and then failing, which finalizes
normally) — e.g. that agent's consumer process is down for the entire
life of the workflow — nothing currently force-finalizes the workflow.
It stays `RUNNING` indefinitely. A real fix needs a scheduled sweep job
(e.g. "any `RUNNING` workflow older than N minutes with an agent still
`PENDING` gets force-finalized as `PARTIAL`") — this codebase has no
scheduler/cron dependency anywhere (same gap Phase 11's "no scheduled
report generation" already disclosed). Documented here rather than
silently left unmentioned; see `docs/architecture_multi_agent.md` "Known,
Disclosed Limitations" #1.

## Dead-Letter Handling

`email.processing.dlq` carries a `DeadLetterEnvelope`
(`app/messaging/schemas.py`): the original event untouched, plus
`source_topic`, `agent`, `failure_reason`, `error_type`, `retry_count`,
`failed_at`, `correlation_id`. An operator investigating failures
consumes this one topic (`docker compose logs -f agents` also shows the
same failure via structured logs, FR-67) rather than needing to poll six
separate per-module DLQ topics — see `docs/kafka_architecture.md` for why
one shared topic was chosen.
