# Testing Strategy (Module 13 / Phase 12)

## Unit Tests (default suite, no infrastructure required)

| File | Covers |
|---|---|
| `tests/test_messaging_retry.py` | Error classification (transient/permanent), exponential backoff calculation |
| `tests/test_messaging_schemas.py` | `AgentEvent`/`DeadLetterEnvelope` round-trip, additive schema evolution |
| `tests/test_agent_execution_repository.py` | Idempotency (`get_or_create`), status transitions, per-workflow listing — against in-memory SQLite, same convention as `tests/test_feedback_event_repository.py` |
| `tests/test_workflow_execution_repository.py` | CRUD + organization scoping — same SQLite convention |
| `tests/test_routing_service_precomputed.py` | The `precomputed_*` kwargs added to `RoutingService.route()` — proves precomputed results are used as-is (never re-fetched), the spam gate still applies, `None` is recorded as unavailable, and partial precomputation still falls back correctly |
| `tests/test_orchestrator_idempotency.py` | Added during a dedicated post-delivery code review (see "A Real Bug Found During Review" below) — proves `Orchestrator._start_workflow` correctly dispatches on a fresh workflow and correctly SKIPS re-dispatch/re-reset on a redelivered `email.processing.requested` for a workflow that already progressed past `PENDING` |

All six run in the default `pytest` invocation — fast, no Docker, no
network. 26 tests, 0 failures (verified).

### A Real Bug Found During Review, Not Testing

After the integration test above was passing, a dedicated line-by-line
review of `app/agents/orchestrator.py` (prompted by a request to check
the work over before committing) found that `_start_workflow` had no
idempotency guard — the one place in the whole pipeline missing the
pattern every specialist agent already used. The integration test never
caught this because it never redelivers `email.processing.requested`
itself (only Kafka's own real at-least-once redelivery, or a crash
between dispatch and offset commit, would trigger it — neither happens
in a single clean test run). Traced by hand: a redelivery arriving AFTER
a workflow reached `COMPLETED` would silently downgrade its status back
to `RUNNING`, create a fresh in-memory tracker that would never receive
completions (because the specialist agents' own idempotency check
suppresses re-publishing `*.completed` for an already-terminal
execution), and leave the workflow permanently stuck. Fixed by checking
`workflow.status == STATUS_PENDING` before dispatching. Two regression
tests (`tests/test_orchestrator_idempotency.py`) reproduce the exact
sequence against in-memory SQLite with a faked `publish_event` (fast,
no Kafka needed) — both the full unit suite and the real-Kafka
integration test were re-run afterward to confirm no regression.

## Integration / Failure / End-to-End Tests (opt-in, real infrastructure)

`tests/test_phase12_kafka_integration.py` — **skipped by default**
(`RUN_KAFKA_INTEGRATION_TESTS` env var gate, same convention
`tests/test_abstractive_summarizer_slow.py` already established for its
own different reason). Provisions a REAL disposable Postgres 16 container
and a REAL disposable `apache/kafka` (KRaft) container via `docker run`,
runs the actual `app/agents/runner.py` task set (all 6 specialist agents
+ Orchestrator), and tears both containers down afterward
(`docker rm -f`) — the same disposable-container convention every prior
phase's migration verification already used.

Run explicitly:
```
RUN_KAFKA_INTEGRATION_TESTS=1 python -m pytest tests/test_phase12_kafka_integration.py -v -s
```

One test function, `test_multi_agent_pipeline_end_to_end`, running three
scenarios sequentially — each proving a REQUIREMENT, not just a class
(master prompt section 19's explicit standard). Not three separate
`async def test_*` functions: see "Why This Is One Test Function, Not
Three" below for the real reason.

1. **Scenario 1 (FR-63/FR-64)** — submits a real (non-spam) email through
   `POST /email/process`'s underlying function, polls
   `GET /workflows/{job_id}` until terminal, asserts all 6 agents ran to
   `COMPLETED` and the email was actually indexed (`email_id` populated).
   **Verified passing** against real Postgres + real Kafka + the real
   trained ML artifacts (spam SVM, priority logistic regression, category
   SVM, sentiment VADER, intent logistic regression, extractive
   summarizer) — not mocked.
2. **Scenario 2** — the dependency-graph short-circuit
   (`docs/architecture_multi_agent.md`'s R-SPAM-GATE): submits an
   unambiguous spam email, asserts only `spam` and `summarization` ever
   dispatch. **Verified passing.**
3. **Scenario 3 (FR-65)** — at-least-once delivery's idempotency
   guarantee: replays the exact same Kafka message bytes through
   `SpamAgent.handle_message()` twice, asserts exactly one
   `agent_executions` row and `attempt_count == 1` (the ML call did NOT
   run twice). **Verified passing.**

Final verified run: **1 passed in 34.47s**, real Postgres 16 + real
`apache/kafka` 3.9.0 containers, zero mocks.

### Why This Is One Test Function, Not Three

The first version of this file used three separate `async def test_*`
functions. All three failed, repeatedly, for a reason that had nothing to
do with Phase 12's actual code: pytest-asyncio gives each test function
its OWN event loop by default, but `app.database.session.engine` is a
module-level singleton with its own asyncpg connection pool — a
connection (or the pool's internal state) created in test A's loop is not
valid once that loop closes and test B's starts. `engine.dispose()`
between tests was tried first and did NOT fully resolve it (still
reproduced `AttributeError: 'NoneType' object has no attribute 'send'`
deep inside asyncpg's connection teardown, triggered from the next test's
loop). The actual fix: run all three scenarios inside ONE
`async def test_...` — one event loop, start to finish. A useful side
effect: the six ML services are `@lru_cache`'d singletons, so scenarios 2
and 3 also run warm instead of re-paying each model's cold-load cost.

### Real Findings From Writing These Tests

The first full end-to-end run's "normal business email" case (subject
"Order not received") unexpectedly took the spam-gated path — only 2 of
6 agents ran. Investigation (`app/services/spam_service.py` queried
directly against several sample texts) confirmed this is the ALREADY-
DOCUMENTED Spam model over-firing issue from Phase 8
(`docs/error_analysis_routing.md`: "the Spam model's recall-tuned
threshold... over-fires on ordinary business email"), surfacing through
the new pipeline for the first time — real evidence that the pipeline
correctly propagates an existing, known model behavior rather than a new
Phase 12 bug. The test's sample text was changed to one that reliably
scores well below the 0.06 threshold (confirmed directly against the real
model before committing the test), and this finding is recorded here
rather than silently worked around.

## Test Types NOT Included This Phase (Disclosed Gaps)

- **Kafka-unavailable / Postgres-unavailable failure-injection tests** —
  the failure PATHS are implemented and documented
  (`docs/failure_handling.md`), but not exercised by an automated test
  that actually kills the container mid-test. `tests/test_db_write_timeout.py`
  (Phase 6) already established that even a carefully engineered failure-
  injection test can fail to reproduce the real failure mode it's
  targeting (see `docs/technical_debt/database_write_hang.md`) — rather
  than ship a superficial version of that same trap, this is disclosed as
  not yet covered.
- **Consumer-restart-mid-workflow test** — the mechanism (offset commit
  only after success) is real and documented, but not exercised by a test
  that actually restarts a consumer process mid-message.
- **Load/throughput testing** — no concurrent-workflow volume test exists;
  see `docs/architecture_multi_agent.md`'s disclosed limitations for why
  this isn't yet load-bearing (zero production traffic).

## Full Suite Impact

The complete PRE-EXISTING test suite (`pytest tests/`, excluding the two
opt-in files) was run after every Phase 12 change: **461 tests + 24 new
Phase 12 unit tests = 485 passing, 1 skipped, 0 failed.** The one required
update to an existing test
(`tests/test_model_metadata_registration.py`, adding `AgentExecution`/
`WorkflowExecution` to the expected model registry) follows the identical
pattern every prior phase's model addition already required.
