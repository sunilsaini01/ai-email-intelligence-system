# Agent Contracts (Module 13 / Phase 12, FR-64/FR-65/FR-66)

## Message Contract

`app/messaging/schemas.py`'s `AgentEvent` is the envelope every message on
every `email.{module}.*` topic uses:

```python
event_id: uuid.UUID        # unique per message
job_id: uuid.UUID          # == workflow_executions.id
email_id: uuid.UUID        # canonical email, or job_id before one exists (see below)
event_type: str            # matches the topic name, e.g. "email.spam.requested"
agent: str | None          # populated on *.completed/*.failed, None on *.requested
schema_version: str        # "1.0" -- additive-only evolution, see below
timestamp: datetime
correlation_id: uuid.UUID  # == job_id today; kept distinct for a future
                            # multi-workflow correlation case without a
                            # schema break
retry_count: int
payload: dict               # module-specific: {"subject", "body", "sender_email"}
                            # on *.requested; {"result": {...}} or
                            # {"error": "..."} on *.completed/*.failed
metadata: dict               # currently just {"organization_id": ...}
```

**Why `email_id` is sometimes `job_id`**: at dispatch time (Orchestrator
publishing `*.requested`), no canonical `emails.id` exists yet — that only
gets created during retrieval indexing, AFTER classification completes
(`app/agents/orchestrator.py`'s `_finalize_workflow`). `job_id` is used as
a stable placeholder purely for Kafka partition-key purposes in the
meantime (see `docs/kafka_architecture.md` "Partitioning") — it is never
presented as a real `emails.id` anywhere; `GET /workflows/{job_id}`
returns the REAL `email_id` (nullable until indexing completes) from
`workflow_executions.email_id`.

**Schema evolution**: additive-only. A future field gets a default and
never renames/removes an existing one — an older consumer reading a
newer message ignores fields it doesn't recognize (pydantic's default
`extra="ignore"` behavior) instead of crashing. Verified:
`tests/test_messaging_schemas.py::test_agent_event_older_consumer_ignores_unknown_future_fields`.

## Agent Lifecycle

Every specialist agent (`app/agents/{module}_agent.py`) is a thin
subclass of `app/agents/base.py`'s `BaseAgent`, supplying only:

- `agent_name: str` — the module key (`"spam"`, `"priority"`, etc.)
- `async def run_ml_call(self, payload: dict) -> dict` — calls the
  **existing, unmodified** service method
  (`SpamService.classify()`, `IntentService.analyze()`, etc.) via
  `asyncio.to_thread` (these are synchronous classes, same ones the HTTP
  endpoints already wrap with `run_in_threadpool`)

Everything else is common, in `BaseAgent.handle_message()`:

1. **Idempotency check** — `AgentExecutionRepository.get_or_create()`
   against the `(workflow_id, agent_name)` unique constraint. If a row
   already exists in a terminal state (`COMPLETED`/`FAILED`), the message
   is a duplicate delivery (FR-65's at-least-once semantics) and is
   dropped with no side effects.
2. **Retry loop** (FR-66) — up to `Settings.AGENT_MAX_ATTEMPTS` (default
   3) attempts, in-process (no Kafka round-trip per retry — see
   `docs/retry_strategy.md`), with exponential backoff between attempts.
3. **Structured logging** (FR-67) — one log line per lifecycle transition
   (`agent_execution_started`, `agent_execution_failed`,
   `agent_execution_retry_scheduled`, `agent_execution_completed`), via
   `app/core/logging.py`, unchanged.
4. **Result publication** — `*.completed` on success; `*.failed` +
   `agent.failed` + a DLQ entry on final failure.

## Input/Output Contract Per Agent

| Agent | `payload` in (on `*.requested`) | `run_ml_call` wraps |
|---|---|---|
| Spam | `{subject, body}` | `SpamService.classify(subject, body)` |
| Priority | `{subject, body, sender_email}` | `PriorityService.classify(subject, body, sender_email)` |
| Category | `{subject, body, sender_email}` | `CategoryService.classify(subject, body, sender_email)` |
| Sentiment | `{subject, body}` | `SentimentService.analyze(subject, body)` |
| Intent | `{subject, body}` | `IntentService.analyze(subject, body)` |
| Summarization | `{subject, body}` | `SummarizationService.summarize(subject, body)` |

Every wrapped service returns a dict with (at minimum) `model_version` and
`processing_ms` — unchanged from their existing `*/predict` endpoint
shapes, since this is literally the same method call.

## Error Handling

See `docs/retry_strategy.md` for classification (transient vs.
permanent) and `docs/failure_handling.md` for the full failure-scenario
matrix (Kafka down, DB down, agent crash, malformed event, etc.).
