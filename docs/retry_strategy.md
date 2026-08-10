# Retry Strategy (Module 13 / Phase 12, FR-66)

## Where Retries Happen

**In-process, inside one Kafka handler invocation** — not by re-publishing
to Kafka per attempt. See `app/models/agent_execution.py`'s module
docstring and `app/agents/base.py`'s module docstring for the full
reasoning: a retry here is "the ML call/DB write failed transiently while
we already have the message in hand," not "Kafka itself is unavailable"
(if Kafka were unavailable, the handler would never have been invoked at
all). This keeps FR-66 simple, testable without a second broker round-trip,
and avoids inflating `attempt_count` bookkeeping across multiple
Kafka messages for what is really one logical task attempt.

## Interpreting "Retry 3 Times"

Read as **up to 3 total attempts** (`Settings.AGENT_MAX_ATTEMPTS`,
default 3), not "3 retries after the first attempt" (which would be 4
total). No stronger signal exists in the PRD text to disambiguate this;
documented here as an explicit reading rather than left ambiguous.

## Backoff

Exponential, base `Settings.AGENT_RETRY_BACKOFF_BASE_SECONDS` (default
2.0): attempt 1 fails → wait `base**1` = 2s; attempt 2 fails → wait
`base**2` = 4s; (attempt 3, if it fails, is the last — no further wait,
straight to `FAILED`). See `app/messaging/retry.py::compute_backoff_seconds`,
tested in `tests/test_messaging_retry.py`.

## Error Classification

Not every failure deserves a retry (master prompt section 10: "do not
retry permanent errors blindly"):

| Error type | Examples | Retried? |
|---|---|---|
| `transient` (default for any unclassified exception) | Network blip, DB timeout, model artifact momentarily locked | Yes, up to `AGENT_MAX_ATTEMPTS` |
| `permanent` | `pydantic.ValidationError` (malformed message payload) | No — straight to `FAILED` + DLQ on the first occurrence |

**Why unclassified exceptions default to `transient`**: consistent with
this codebase's pre-existing stance in `RoutingService._safe_call`
(Phase 8) — an unexpected exception is treated as "signal unavailable,
don't assume the worst," not "definitely a permanent, unretryable bug."
`AGENT_MAX_ATTEMPTS` still bounds this to a small, finite number either
way (never infinite, per Critical Rule #9). See
`app/messaging/retry.py::classify_exception`.

An agent that KNOWS a failure is permanent (none currently do — all six
specialist agents wrap synchronous ML calls whose only realistic failure
mode is transient: missing artifact, momentary resource contention) can
raise `PermanentAgentError` to short-circuit retries; the base class is
ready for this even though no current agent needs it yet.

## After Retries Are Exhausted

1. `agent_executions.status = FAILED`, with `error_type`/`error_message`
   recorded.
2. `email.{module}.failed` published.
3. `agent.failed` published (module-agnostic terminal-failure signal).
4. A `DeadLetterEnvelope` published to `email.processing.dlq` — see
   `docs/failure_handling.md` "Dead-Letter Handling".

The Orchestrator, on receiving `*.failed`, still finalizes the workflow
(as `PARTIAL`, not stuck forever) once every OTHER dispatched agent has
also reported — a failed agent does not block the rest of the pipeline,
same failure-isolation stance `RoutingService` already established for
missing signals.

## Testing

`tests/test_messaging_retry.py` — classification + backoff calculation,
pure unit tests. `tests/test_phase12_kafka_integration.py` (gated,
`RUN_KAFKA_INTEGRATION_TESTS=1`) exercises a real transient-failure/retry/
success sequence and a real retries-exhausted/DLQ sequence against a live
broker — see `docs/testing_strategy_phase12.md`.
