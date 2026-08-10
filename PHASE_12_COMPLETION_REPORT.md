# Phase 12 Completion Report — Multi-Agent Architecture (Module 13, FR-63–67)

> Stage 30/Definition-of-Done deliverable. Written after implementation,
> testing, and real-infrastructure verification — every claim below is
> checked against actual test runs against a real Postgres container and
> a real Kafka broker, not asserted from the design docs alone.

## 1. Executive Summary

Phase 12 adds an event-driven multi-agent layer — an Orchestrator Agent
plus 6 independent Kafka-based Specialist Agents (Spam, Priority,
Category, Sentiment, Intent, Summarization) — running ALONGSIDE the
existing modular monolith, not replacing it. Every pre-Phase-12 endpoint
is unchanged (verified: all 461 pre-existing backend tests pass
unmodified). This is a deliberate, disclosed reversal of Phase 1's
original "no Kafka yet" decision, made because FR-63–67 explicitly
requires it — not a silent architecture drift.

## 2. PRD Requirements Implemented

FR-63 (Orchestrator Agent), FR-64 (independent per-module agents), FR-65
(Kafka async messaging), FR-66 (retry ×3 + exponential backoff), FR-67
(structured agent logs). Full detail:
`docs/requirements_traceability_phase12.md`.

## 3. Architecture Before Phase 12

```
Caller → FastAPI endpoint → Service (in-process call) → ML artifact / DB
```

No cross-module chaining happened automatically anywhere in this
codebase. See `PHASE_12_AUDIT_REPORT.md`'s headline finding: no
entrypoint existed for "a new email arrived and needs processing" at all.

## 4. Architecture After Phase 12

```
POST /api/v1/email/process → workflow_executions (PENDING) → 202 {job_id}
Orchestrator (Kafka consumer) → dispatches Spam+Summarization → gate → dispatches
  Priority/Category/Sentiment/Intent if not spam → Routing (in-process,
  reusing agent results) → Retrieval indexing (in-process) → workflow finalized
GET /api/v1/workflows/{job_id} → Postgres-backed status (durable, not Kafka-replayed)
```

Full detail: `docs/architecture_multi_agent.md`.

## 5. Agent Architecture

`app/agents/base.py`'s `BaseAgent` — idempotency check, in-process
retry+backoff loop, structured logging, DLQ on exhaustion — shared by all
6 specialist agents, each a ~15-line subclass wrapping its existing,
unmodified service. Full detail: `docs/agent_contracts.md`.

## 6. Kafka Architecture

`aiokafka` client, `apache/kafka` (KRaft, single container) broker — both
confirmed decisions from `PHASE_12_AUDIT_REPORT.md` section 14, chosen
specifically for this project's Windows dev environment (avoiding
another native-build dependency; minimizing container count given this
machine's own history of port-collision issues). Full detail:
`docs/kafka_architecture.md`.

## 7. Message Contracts

Versioned `AgentEvent`/`DeadLetterEnvelope` (Pydantic, `schema_version`
field, additive-only evolution — tested:
`tests/test_messaging_schemas.py::test_agent_event_older_consumer_ignores_unknown_future_fields`).
Full detail: `docs/agent_contracts.md`.

## 8. Workflow State

`workflow_executions` + `agent_executions` (Postgres), NOT reconstructed
from Kafka. Full detail: `docs/workflow_state.md`.

## 9. Retry Strategy

In-process, exponential backoff (`base**attempt`), transient/permanent
error classification. Full detail: `docs/retry_strategy.md`.

## 10. Failure Handling

Full scenario matrix (Kafka down, DB down, agent crash, malformed event,
duplicate delivery, consumer restart, etc.) in `docs/failure_handling.md`.
One real, disclosed gap: no per-workflow timeout for a silently-missing
agent (see that doc's final section).

## 11. Idempotency

`AgentExecutionRepository.get_or_create()` against a `(workflow_id,
agent_name)` unique constraint — check-then-insert, same disclosed
narrow-race-window shape as Phase 11's Review Queue duplicate-confirm
guard. **Verified against a real Kafka broker**: replaying the identical
message bytes through `SpamAgent.handle_message()` twice produces exactly
one `agent_executions` row with `attempt_count == 1`
(`tests/test_phase12_kafka_integration.py::test_multi_agent_pipeline_end_to_end`, scenario 3).

## 12. Database Changes

One migration
(`backend/alembic/versions/e2f5b8c31a94_phase12_multi_agent_schema.py`):
2 new tables (`workflow_executions`, `agent_executions`), 4 new indexes.
Verified via a real disposable Postgres 16 container: upgrade →
downgrade → upgrade round-trip, plus a genuine ORM insert/read/update
round-trip including the idempotency guarantee.

## 13. API Changes

2 new endpoints: `POST /api/v1/email/process` (202, returns `job_id`),
`GET /api/v1/workflows/{job_id}`. Additive — every pre-existing endpoint
contract is unchanged. One additive change to existing code:
`RoutingService.route()` gained 5 keyword-only `precomputed_*` params,
defaulted to preserve 100% of prior behavior (verified: all 60
pre-existing routing tests pass unchanged, plus 4 new dedicated
regression tests in `tests/test_routing_service_precomputed.py`).

## 14. Docker Changes

`docker-compose.yml`: new `kafka` service (`apache/kafka:3.9.0`, KRaft,
healthcheck-gated) and new `agents` service (`python -m app.agents.runner`,
one process running all 6 specialist agent consumers + the Orchestrator).
`api` service gained a `KAFKA_BOOTSTRAP_SERVERS` env var and a `depends_on`
healthcheck condition on `kafka`.

## 15. Security Review

No new authentication surface — inherits the exact same caller-supplied,
unauthenticated `organization_id` trust model every endpoint has had
since Phase 1. Kafka runs `PLAINTEXT` (no auth/TLS) on the compose
network only. No PII/secrets in logs or the DLQ's `failure_reason` field
(exception messages only, never payload content). Full detail:
`docs/requirements_traceability_phase12.md` "Security Note."

## 16. Performance Results

Observed (cold, first-load) latencies from the verified end-to-end runs:
spam ~0.7–2.8s, summarization ~2.2s (extractive, short-input
passthrough), priority/category/sentiment/intent each a few seconds
cold, retrieval indexing ~1–2s (real MiniLM embedder + real Chroma vector
store). No dedicated warm-state benchmark or concurrent-workflow load
test exists yet — disclosed, not measured, consistent with this
project's zero-production-traffic status.

## 17. Test Results

**487 total backend tests** (461 pre-existing, unmodified + 26 new Phase
12 unit tests, including 2 added during a dedicated post-delivery review
pass — see §18 item 4), **0 failed, 1 skipped** (the pre-existing
`RUN_SLOW_TESTS`-gated abstractive-summarizer test — unrelated to this
phase), verified via a real full-suite run (90.54s). Plus 1 opt-in
real-infrastructure integration test
(`RUN_KAFKA_INTEGRATION_TESTS=1`, `tests/test_phase12_kafka_integration.py::test_multi_agent_pipeline_end_to_end`)
— see §19. Both the full suite and the real-infrastructure test were
re-run AFTER the §18 item 4 fix to confirm it introduced no regression.

## 18. Bugs Found and Fixed

1. **Windows import-order segfault in `app/agents/runner.py`** — this
   entrypoint (started directly via `python -m app.agents.runner`, not
   through `app/main.py`) was missing the same `import pandas; import
   sklearn`-first workaround `app/main.py` already documents for the
   `transformers`/`sklearn`/`pyarrow` lazy-import fault. Reproduced
   directly (exit 139) before the fix; fixed and re-verified.
2. **`logging` stdlib reserved-key collision in
   `app/agents/orchestrator.py`** (2 call sites: `handle_message`'s
   unknown-workflow log line, and `_dispatch`'s per-dispatch log line —
   the second one fires on EVERY single agent dispatch, so this crashed
   constantly once real logging was active) — both passed `module` as a
   `logging` `extra` key, which collides with a reserved `LogRecord`
   attribute and raises `KeyError: "Attempt to overwrite 'module' in
   LogRecord"`. Found via the live Kafka integration test, NOT a code
   review or the earlier manual verification script — the manual script
   never exercised this path at all, because it never called
   `setup_logging()`, so its `logger.info()` calls were filtered out
   below the default root-logger WARNING level before `makeRecord()` (and
   thus the collision) was ever reached. This is real, concrete evidence
   that a shallow manual smoke-test can look completely clean while
   missing a defect a properly-configured integration test catches
   immediately — recorded here rather than only in the fix's commit.
   Fixed (renamed to `agent_name`) and re-verified against a live broker.
3. **Test-harness bug in the FIRST version of
   `tests/test_phase12_kafka_integration.py`** (a test-file bug, not
   application code): three separate `async def test_*` functions each
   failed because pytest-asyncio's per-function event loop broke
   `app.database.session`'s module-level asyncpg connection pool across
   test boundaries. Fixed by combining all three scenarios into one
   `async def test_multi_agent_pipeline_end_to_end` — one event loop,
   start to finish. See `docs/testing_strategy_phase12.md` "Why This Is
   One Test Function, Not Three."
4. **`Orchestrator._start_workflow` had no idempotency guard** — found
   via a dedicated post-delivery code review (not the integration test,
   which never exercises redelivery of `email.processing.requested`
   itself). Under FR-65's at-least-once delivery, that topic's message
   CAN be redelivered (e.g. the Orchestrator crashes after dispatching
   agents but before its consumer offset commits). Without a guard,
   `_start_workflow` unconditionally re-dispatched spam/summarization and
   reset `workflow_executions.status` back to `RUNNING` — including for a
   workflow that had ALREADY reached `COMPLETED`, with no way to ever
   re-finalize it (the new in-memory tracker never receives completions
   for an execution the specialist agents' own idempotency check has
   already marked terminal and will not re-publish for — a silent,
   permanent stuck-`RUNNING` state for an email that had actually already
   finished processing correctly). Fixed by checking
   `workflow.status == STATUS_PENDING` before proceeding, mirroring the
   exact idempotency pattern every specialist agent already used
   (`app/agents/base.py`) but which `_start_workflow` had been missing.
   Two new regression tests
   (`tests/test_orchestrator_idempotency.py`) reproduce the exact failure
   sequence and verify the fix; re-verified against a live broker
   afterward (§19).
5. **`RoutingService.route()` re-inference redundancy (design-time, not a
   shipped bug)** — the audit's own initial framing risked the
   Orchestrator either re-running the 5 ML calls a second time or
   inventing a second message contract just to ferry already-computed
   results back through Kafka. Resolved before implementation by adding
   `precomputed_*` kwargs to the existing method instead — see §13.

## 19. Real-Infrastructure Integration Test Results

**PASSED** — `test_multi_agent_pipeline_end_to_end`, 1 passed in 34.47s,
against a real disposable Postgres 16 container (`docker run
postgres:16-alpine`) and a real disposable `apache/kafka:3.9.0` (KRaft)
container, both provisioned via plain `docker run` (env vars exported in
the shell before `pytest` started — see the test file's own module
docstring for why), migrated with the real Alembic migration, and torn
down (`docker rm -f`) afterward — this project's standing disposable-
container convention. All three scenarios (full 6-agent dispatch, spam-
gate 2-agent short-circuit, duplicate-delivery idempotency) passed within
that single run, using the real trained SVM/logistic-regression/VADER/
extractive-summarizer artifacts and the real MiniLM embedder + Chroma
vector store for indexing — nothing mocked.

## 20. Remaining Technical Debt

- No per-workflow timeout for a silently-missing agent (§10).
- Orchestrator in-flight state is process-local (§10 / `docs/architecture_multi_agent.md`).
- Kafka/Postgres failure-injection isn't automated (disclosed, not silently skipped).
- No per-agent-call timeout wrapping `run_ml_call` (a new instance of the
  same already-disclosed risk class as `docs/technical_debt/database_write_hang.md`).
- Malformed-event handling has a gap: a message that fails Pydantic
  validation never reaches the retry/DLQ path at all (see
  `docs/failure_handling.md` "Malformed Event") — low real risk since
  nothing outside this codebase publishes to these topics, but disclosed.
- Every pre-existing technical-debt item from Phases 1–11 (DB write hang,
  incomplete `requirements.txt`, missing auth, synthetic labels, Spam
  domain-transfer gap, no frontend tests) is untouched, per explicit
  instruction not to silently fix unrelated debt.

## 21. ML/Data Evidence Limitations

Unchanged. Running Priority/Category/Intent as Kafka agents does not
improve their underlying synthetic-data evidence status — the same
5-badge vocabulary (`docs/model_evidence_policy.md`) still applies to
every number these agents produce.

## 22. PRD Traceability

See `docs/requirements_traceability_phase12.md` for the full FR-63–67
table and Definition-of-Done checklist.

## 23. Production Readiness Level

**Not production-ready**, same standard every prior phase has held itself
to. Concretely: no real authentication (standing gap since Phase 1), no
per-workflow timeout for a stuck pipeline, no automated failure-injection
testing, no load/concurrency testing, and zero real production traffic to
validate any of this against. It IS: a real, working, end-to-end verified
async pipeline — real Kafka, real Postgres, real trained ML models, a
real duplicate-delivery idempotency guarantee, a real dependency-graph
short-circuit (the spam gate) — not a simulated or in-process-faked one,
which is what FR-65 specifically required.

## 24. Recommended Next Phase

Modules 14–15 (FR-68–72: Kubernetes, CI/CD, MLflow, alerting) — see
README.md "Next (Phase 13)" for the full reasoning.
