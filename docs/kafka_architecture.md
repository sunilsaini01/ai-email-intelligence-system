# Kafka Architecture (Module 13 / Phase 12, FR-65)

## Client Library Decision

**aiokafka**, confirmed decision (`PHASE_12_AUDIT_REPORT.md` section 14).
Async-native — matches this project's fully-async FastAPI/SQLAlchemy
stack (no thread-pool bridging needed, unlike `confluent-kafka`'s
synchronous C-extension API). Also avoids adding another native-build
dependency on a Windows dev environment that has already hit repeated
issues from exactly that class of dependency (`torch`, the
`transformers`/`pyarrow` import-order crash worked around in
`app/main.py` and, as of this phase, also `app/agents/runner.py`).
Verified installable with a prebuilt `win_amd64`/`cp313` wheel — no build
toolchain required.

## Broker Decision

**`apache/kafka:3.9.0`, KRaft mode, single container.** No Zookeeper.
Confirmed decision, chosen specifically because this project's Windows
dev machine has already hit real port-collision problems running just
Postgres (`docker-compose.yml`'s own documented `5433:5432` workaround) —
one extra container instead of two is a direct risk reduction here, not
merely a simplification in the abstract.

## Topics

See `app/messaging/topics.py` for the authoritative list (generated
programmatically via `all_agent_topics()`, so this table and the code
cannot silently drift):

| Topic | Producer | Consumer | Purpose |
|---|---|---|---|
| `email.processing.requested` | `POST /api/v1/email/process` | Orchestrator | Kick off a workflow |
| `email.{module}.requested` | Orchestrator | that module's specialist agent | Dispatch one ML call |
| `email.{module}.completed` | specialist agent | Orchestrator | Successful result |
| `email.{module}.failed` | specialist agent | Orchestrator | Retries exhausted or permanent error |
| `agent.failed` | specialist agent | (future consumers — alerting, etc.) | Terminal failure signal, module-agnostic |
| `workflow.completed` | Orchestrator | (future consumers — dashboard, etc.) | Whole-pipeline done |
| `email.processing.dlq` | specialist agent, on final failure | Manual/ops inspection | Dead-letter, see "Dead-Letter Handling" below |

`{module}` ranges over `app/messaging/topics.py`'s `AGENT_MODULES`: spam,
priority, category, sentiment, intent, summarization.

**Naming deviates from the master prompt's own illustrative example in
one place**: summarization's topics use `summarization`, not the
example's shorthand `summary` — consistency with every other reference to
this module across the codebase beats matching an illustrative example
verbatim (the master prompt itself explicitly allows this).

## Partitioning

Every message is keyed by `email_id` (or, at dispatch time before a
canonical `emails.id` exists, by `job_id` — see
`app/agents/orchestrator.py`'s `_dispatch` docstring for why). This
guarantees every event about one workflow lands on the same partition,
giving per-workflow ordering without needing a global order across
unrelated emails.

## Consumer Groups

One group per agent (`f"{KAFKA_CONSUMER_GROUP_PREFIX}-{agent_name}"`,
e.g. `email-ai-spam`), plus one for the Orchestrator
(`email-ai-orchestrator`). Each agent scaling independently later (more
replicas of the same consumer group) requires zero design changes — this
is exactly why groups are per-agent rather than one shared group.

## Delivery Semantics

**At-least-once**, by deliberate choice — not exactly-once (which would
need Kafka transactions, real complexity this scope doesn't need) and not
at-most-once (which would silently drop a message on a crash mid-handler,
a strictly worse failure mode for a correctness-sensitive pipeline like
this one). `enable_auto_commit=False`; the offset is committed only AFTER
a handler returns successfully (`app/messaging/consumer.py`). This is why
FR-65's idempotency requirement (`docs/agent_contracts.md`) is mandatory,
not optional — a crash between a successful handler run and the commit
redelivers that message on restart.

## Retention

Short (this project runs `apache/kafka` with its own defaults, not
explicitly shortened — a documented follow-up, not yet load-bearing at
zero production traffic) for `*.requested`/`*.completed`/`*.failed` —
these are transport, not the system of record
(`docs/workflow_state.md` — Postgres is). Longer retention is intended
for the DLQ topic specifically, so an operator has time to investigate; not
yet separately configured this phase (same disclosed, not-yet-tuned status
as everything else that has no real production traffic to tune against).

## Why Routing / Retrieval / Auto-Reply Are NOT Kafka Agents

Confirmed scope decision (`PHASE_12_AUDIT_REPORT.md` section 14): only
the 6 ML classification modules become Kafka agents. Reasoning:

- **Routing** is a decision layer composing the 6 classification agents'
  own results — giving it a 7th Kafka round-trip would mean either (a)
  re-running the 5 relevant ML calls a second time (wasteful, and a real
  correctness risk if results diverge between what was published and what
  Routing recomputed) or (b) building a second message contract just to
  ship already-computed results back through Kafka for no reason. Neither
  is better than the actual solution: `RoutingService.route()` gained
  `precomputed_*` kwargs (see `app/services/routing_service.py`) so the
  Orchestrator can call it in-process with the agent results it already
  has, reusing the exact same rule/composition logic
  (`app/routing/rules.py`) without re-inference.
- **Retrieval** indexing has no independent scaling need today and
  already has a correct, tested in-process sequence
  (`app/api/v1/endpoints/retrieval.py`) the Orchestrator mirrors directly.
- **Auto-Reply** is not run automatically at all — see
  `docs/architecture_multi_agent.md` "Scope Boundary" for why (a real,
  billed external API call that should stay an explicit, human-triggered
  action).

## Local Development

```
docker compose up -d postgres kafka          # infrastructure
docker compose up -d api agents              # or: run both locally with `.env`

# Submit an email:
curl -X POST http://localhost:8000/api/v1/email/process \
  -H "Content-Type: application/json" \
  -d '{"subject": "Order issue", "body": "My order has not arrived.", "sender_email": "customer@example.com"}'
# -> {"job_id": "...", "status": "PENDING"}

# Observe workflow completion:
curl http://localhost:8000/api/v1/workflows/<job_id>
```

`docker compose logs -f agents` shows the structured execution logs for
every agent + the Orchestrator (FR-67) as the workflow progresses.
