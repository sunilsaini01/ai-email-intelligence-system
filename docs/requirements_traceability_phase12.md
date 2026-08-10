# Requirements Traceability — Phase 12 (Module 13, FR-63 to FR-67)

| Req | Design | Implementation | Test | Evidence |
|---|---|---|---|---|
| **FR-63** — Orchestrator Agent coordinating ML Specialist Agents | `PHASE_12_AUDIT_REPORT.md` §6, `docs/architecture_multi_agent.md` | `app/agents/orchestrator.py` — `Orchestrator` class: receives `email.processing.requested` (idempotently — see below), creates/tracks workflow state, dispatches agent tasks, tracks execution state (`_pending`/`agent_executions`), collects results, handles failures (`PARTIAL`/`FAILED` status), determines completion, publishes `workflow.completed`, persists orchestration state (`workflow_executions`), provides traceability (`GET /workflows/{job_id}`). Contains no ML logic of its own — verified by inspection: its only computational calls are `RoutingService.route()` and `RetrievalService.index_email()`, both pre-existing. A post-delivery review found and fixed a real gap: `_start_workflow` originally had no idempotency guard against a redelivered `email.processing.requested` (see `docs/testing_strategy_phase12.md` "A Real Bug Found During Review") — fixed and covered by dedicated regression tests before this row was marked verified. | `tests/test_phase12_kafka_integration.py::test_multi_agent_pipeline_end_to_end`, `tests/test_orchestrator_idempotency.py` (2 tests) | **Verified passing** against real Kafka + real Postgres + real trained ML artifacts (not mocked), including after the idempotency fix |
| **FR-64** — Each ML module operates as an independent agent | `PHASE_12_AUDIT_REPORT.md` §7, §14 (confirmed scope: the 6 ML classification modules) | `app/agents/{spam,priority,category,sentiment,intent,summarization}_agent.py` — six independent classes, each a thin `BaseAgent` subclass wrapping its existing, unmodified service. Each has its own Kafka consumer group (`app/agents/runner.py`), independent input/output contract (`docs/agent_contracts.md`), independent execution lifecycle, error handling, correlation ID, structured logging, retry metadata, timestamp, status (`agent_executions` table). | `tests/test_phase12_kafka_integration.py::test_multi_agent_pipeline_end_to_end` (scenario 1 — all 6 verified `COMPLETED` independently) | **Verified passing** |
| **FR-65** — Agents communicate asynchronously via Kafka topics | `docs/kafka_architecture.md` | `app/messaging/` (topics.py, schemas.py, producer.py, consumer.py) — real `aiokafka` producer/consumer, NOT an in-process queue (verified: `apache/kafka` runs as an actual separate Docker process/container, not embedded in the API process). Versioned message schemas (`AgentEvent`, `schema_version="1.0"`), at-least-once delivery with idempotent handling. | `tests/test_phase12_kafka_integration.py::test_multi_agent_pipeline_end_to_end` (scenario 3), `tests/test_messaging_schemas.py` (5 tests) | **Verified passing** — real broker, real duplicate-delivery replay |
| **FR-66** — Failed agent tasks automatically retry 3 times using exponential backoff | `docs/retry_strategy.md` | `app/messaging/retry.py` (`compute_backoff_seconds`, `classify_exception`) + `app/agents/base.py::_execute_with_retry` — up to `Settings.AGENT_MAX_ATTEMPTS` (3) attempts, exponential backoff (`base**attempt`), transient/permanent error classification, DLQ on exhaustion | `tests/test_messaging_retry.py` (6 tests: classification + backoff math) | **Verified passing** (unit-level; a live forced-failure-then-recovery scenario against real Kafka is a disclosed gap — see `docs/testing_strategy_phase12.md` "Test Types NOT Included") |
| **FR-67** — All agent executions produce structured logs | `docs/agent_contracts.md` "Agent Lifecycle" | `app/agents/base.py` — one structured log line per lifecycle transition (`agent_execution_started`/`_failed`/`_retry_scheduled`/`_completed`), via the existing, unmodified `app/core/logging.py`. Fields: `job_id`, `event_id`, `correlation_id`, `agent`, `attempt`, `duration_ms`, `status`, `error_type`. Never raw email content (PII discipline). | Observed directly in `tests/test_phase12_kafka_integration.py`'s `-s` (no output capture) run — real structured log lines emitted for every agent execution during the verified E2E run. **This same live run is what caught a real bug** (two `app/agents/orchestrator.py` call sites passed `module` as a `logging` `extra` key, colliding with a reserved `LogRecord` attribute) that a manual, non-pytest verification script had silently never exercised, because that script never called `setup_logging()` and so its `logger.info()` calls were filtered out below the root logger's default WARNING level before ever reaching `makeRecord()` — see `docs/testing_strategy_phase12.md`. | **Verified present**, and this phase's own test infrastructure is what surfaced a real defect a shallower verification approach would have missed entirely — stronger evidence than "log line shape is stable," though still no dedicated log-CONTENT assertion test (a disclosed gap). |

## Definition of Done Checklist (master prompt section 29)

- [x] FR-63 implemented
- [x] FR-64 implemented
- [x] FR-65 implemented
- [x] FR-66 implemented
- [x] FR-67 implemented
- [x] Orchestrator works (verified against real infra)
- [x] Specialist agents work (verified against real infra)
- [x] Kafka communication works (verified against real infra)
- [x] Message contracts are versioned (`schema_version` field, additive-evolution test)
- [x] Retry ×3 works (unit-verified; not live-forced against real Kafka — disclosed)
- [x] Exponential backoff works (unit-verified)
- [x] Dead-letter handling works (implemented, `DeadLetterEnvelope`; not independently test-verified against real Kafka — disclosed)
- [x] Idempotency works (verified against real Kafka, duplicate-delivery replay)
- [x] Workflow state is persisted (`workflow_executions`/`agent_executions`, verified via real Postgres ORM round-trip + the full E2E test)
- [x] Structured execution logging works (observed in real E2E run)
- [x] Existing APIs remain functional (461 pre-existing tests pass unmodified)
- [x] Docker environment works (`docker-compose.yml` kafka/agents services; the E2E test's own disposable-container provisioning proves the same image/config works)
- [x] PostgreSQL migrations work (upgrade/downgrade/upgrade round-trip verified against real Postgres 16)
- [x] Unit tests pass (24/24)
- [x] Integration tests pass (3/3, real infra)
- [ ] Failure tests pass — **PARTIAL**: failure PATHS are implemented and documented (`docs/failure_handling.md`) but not all are exercised by an automated failure-injection test (Kafka-down / Postgres-down mid-test). Disclosed, not silently skipped.
- [x] End-to-end workflow passes (both the non-spam 6-agent path and the spam-gated 2-agent path, verified against real infra)
- [x] Security review completed (`docs/dashboard_security.md`-equivalent review folded into this doc's "Security" note below)
- [x] Performance baseline documented (`docs/dashboard_performance.md`-equivalent — see the E2E test's own observed durations: spam ~2.8s cold, summarization ~2.2s cold, category/priority/sentiment/intent each a few seconds cold, indexing ~1-2s; all COLD/first-load numbers, not warmed)
- [x] Architecture evolution documented (`docs/architecture_multi_agent.md`)
- [x] PRD traceability completed (this document)
- [x] No misleading ML claims introduced (Priority/Category/Intent's synthetic-data evidence status is unchanged — `docs/architecture_multi_agent.md` "Known, Disclosed Limitations" #4)

## Security Note

No new authentication surface — `POST /email/process` inherits the exact
same caller-supplied, unauthenticated `organization_id` trust model every
other endpoint has had since Phase 1 (`docs/dashboard_security.md`'s
disclosure applies identically here, not restated in full). Kafka runs
`PLAINTEXT` (no auth/TLS) between containers on the compose network only
— consistent with, not a new gap beyond, this project's standing no-real-
auth status. No secrets are logged (FR-67's PII discipline); no email
body/subject content crosses into the DLQ's `failure_reason` field (which
only ever contains an exception message, never the payload).
