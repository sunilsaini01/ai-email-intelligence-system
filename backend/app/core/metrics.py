"""
Prometheus metric definitions (Phase 16B / FR-72).

One shared module, imported by both the `api` process (app/main.py mounts
/metrics onto the existing FastAPI app) and the `agents` process
(app/agents/runner.py starts its own metrics HTTP server via
start_metrics_server() below, since that process has no other HTTP server
-- see k8s/agents-deployment.yaml). Each OS process gets its own separate
prometheus_client REGISTRY; this file only avoids declaring the same
metric shape twice, it does not share state across processes.

Label cardinality discipline (see docs/architecture/architecture_monitoring.md
"Label Cardinality"): every label below is a small, bounded, non-PII set --
module name, agent name, terminal status, Kafka topic, HTTP method, and a
FastAPI *route template* (e.g. "/api/v1/workflows/{job_id}", never the
resolved path with a real UUID in it). Never email body/subject, never a
raw organization_id/email_id/reviewer_id, never a raw HTTP path.

"Queue depth" mapping (PRD FR-72's literal wording, project's own §9
instruction to document this explicitly rather than silently substitute):
Kafka has no native "queue depth" concept the way a traditional broker
does. Consumer group lag (kafka_consumergroup_lag, exported by
kafka-exporter against the real Kafka broker, not emitted by this app) is
used as the equivalent signal -- see docs/architecture/architecture_monitoring.md
"Queue Depth = Consumer Lag".
"""

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------
# API layer
# ---------------------------------------------------------------------

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests handled by the API.",
    ["method", "path_template", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "path_template"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30),
)

# ---------------------------------------------------------------------
# ML inference layer -- one histogram per module via the `module` label,
# not one histogram per module-named metric, so PromQL queries don't need
# to be duplicated six times to compare modules.
# ---------------------------------------------------------------------

INFERENCE_DURATION_SECONDS = Histogram(
    "email_inference_duration_seconds",
    "Per-module ML inference latency in seconds (mirrors the processing_ms "
    "already recorded on each module's *_prediction_logs table).",
    ["module", "model_version"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8),
)

INFERENCE_TOTAL = Counter(
    "email_inference_total",
    "Total inference calls per module, labeled by outcome.",
    ["module", "outcome"],  # outcome: success | error
)

# ---------------------------------------------------------------------
# Workflow / orchestrator layer
# ---------------------------------------------------------------------

WORKFLOW_DURATION_SECONDS = Histogram(
    "email_workflow_duration_seconds",
    "End-to-end workflow latency in seconds: pipeline_start = "
    "WorkflowExecution.started_at (set at POST /email/process), "
    "pipeline_end = WorkflowExecution.completed_at (set when the "
    "Orchestrator finalizes the workflow). See "
    "WorkflowExecutionRepository.update_status.",
    buckets=(0.5, 1, 2, 4, 8, 15, 30, 60, 120),
)

WORKFLOW_TOTAL = Counter(
    "email_workflow_total",
    "Total workflows reaching a terminal status.",
    ["status"],  # COMPLETED | FAILED | PARTIAL
)

AGENT_EXECUTIONS_TOTAL = Counter(
    "agent_execution_total",
    "Total specialist-agent executions.",
    ["agent_name", "status"],  # status: COMPLETED | FAILED
)

STUCK_WORKFLOWS = Gauge(
    "workflow_stuck_total",
    "Workflows RUNNING longer than the stuck-workflow threshold. Surfaces "
    "the Orchestrator's disclosed process-local-tracking limitation "
    "(app/agents/orchestrator.py) as an observable signal -- detection "
    "only, no auto-recovery. Set by a periodic check in app.agents.runner, "
    "read via WorkflowExecutionRepository.list_stale_running().",
)

# ---------------------------------------------------------------------
# Feedback / quality-proxy layer -- data_status makes it structurally
# impossible to graph a synthetic-label correction rate next to a real
# one without the label being visibly different, per the project's own
# disclosure discipline (docs/evidence/data_audit_*.md).
# ---------------------------------------------------------------------

FEEDBACK_CORRECTIONS_TOTAL = Counter(
    "feedback_correction_total",
    "Total feedback correction events.",
    ["module", "data_status"],  # data_status: real | synthetic | none
)

# ---------------------------------------------------------------------
# Model drift (FR-72 "model accuracy drift") -- set by the agents
# process's periodic drift check (app/services/scheduled_jobs.py). See
# app/mlops/drift.py for what these measure and what they don't.
# ---------------------------------------------------------------------

MODEL_PREDICTION_DRIFT_PSI = Gauge(
    "model_prediction_drift_psi",
    "Population Stability Index of the last 7 days' predicted-label distribution vs. the 28 days before. "
    "-1 when there is not enough data to compute it.",
    ["module"],
)

MODEL_CORRECTION_RATE = Gauge(
    "model_feedback_correction_rate",
    "Feedback correction rate (FR-62 accuracy proxy) per window; -1 when nothing was reviewed.",
    ["module", "window"],  # window: current | baseline
)

SLA_EMAILS = Gauge(
    "sla_open_emails",
    "Unresolved emails per SLA state, as of the last SLA sweep.",
    ["state"],  # within_sla | at_risk | breached
)

# ---------------------------------------------------------------------
# Kafka layer (application-side; consumer lag itself comes from
# kafka-exporter scraping the broker directly, not from this app)
# ---------------------------------------------------------------------

KAFKA_MESSAGES_TOTAL = Counter(
    "kafka_messages_total",
    "Kafka messages produced or consumed by this application.",
    ["topic", "direction", "outcome"],  # direction: produced | consumed ; outcome: success | error
)

# ---------------------------------------------------------------------
# Mailbox ingestion layer (Phase 18) -- the poller in app/agents/runner.py
# ---------------------------------------------------------------------

MAILBOX_MESSAGES_INGESTED_TOTAL = Counter(
    "mailbox_messages_ingested_total",
    "Inbound messages fetched from a connected mailbox and handed to the pipeline.",
    ["provider", "outcome"],  # provider: gmail | outlook ; outcome: success | error | duplicate
)

MAILBOX_CONNECTIONS_ERRORED = Gauge(
    "mailbox_connections_errored",
    "Mailbox connections currently in an error state (token refresh or fetch failed) -- needs reconnecting.",
)


def start_metrics_server(port: int) -> None:
    """Starts prometheus_client's own background-thread HTTP server.

    Only used by app.agents.runner. The api process instead mounts
    /metrics onto the existing FastAPI app (see app/main.py) since it
    already has an HTTP server; agents does not -- see the `ports` entry
    added to k8s/agents-deployment.yaml for this phase.
    """
    from prometheus_client import start_http_server

    start_http_server(port)
