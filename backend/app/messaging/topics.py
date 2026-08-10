"""
Kafka topic names (Phase 12 / Module 13, FR-65).

Naming deviates from the master prompt's own illustrative example in one
place: the summarization module's topics use "summarization", not the
example's shorthand "summary" -- consistency with every other reference to
this module across the codebase (SummarizationService, docs/
architecture_email_summarization.md, the existing /summarization/predict
endpoint) beats matching an illustrative example verbatim. The master
prompt itself explicitly allows this ("do not blindly copy these names if
the audit identifies a better design").

Why one shared DLQ topic (email.processing.dlq) instead of one per module:
    An operator investigating failures wants "what failed today across the
    whole pipeline," not six separate topics to poll. The DLQ message
    itself (see schemas.py's DeadLetterEnvelope) carries which agent/topic
    it originated from, so nothing is lost by sharing the topic.
"""

# The six ML classification modules that become independent Kafka agents
# (FR-64's literal "ML Specialist Agents" list) -- confirmed scope
# decision, see PHASE_12_AUDIT_REPORT.md section 14. Routing, Retrieval,
# and Auto-Reply are NOT here -- they stay in-process, invoked by the
# Orchestrator (see app/agents/orchestrator.py).
AGENT_MODULES: tuple[str, ...] = (
    "spam",
    "priority",
    "category",
    "sentiment",
    "intent",
    "summarization",
)

TOPIC_EMAIL_PROCESSING_REQUESTED = "email.processing.requested"
TOPIC_AGENT_FAILED = "agent.failed"
TOPIC_WORKFLOW_COMPLETED = "workflow.completed"
TOPIC_DEAD_LETTER = "email.processing.dlq"


def requested_topic(module: str) -> str:
    return f"email.{module}.requested"


def completed_topic(module: str) -> str:
    return f"email.{module}.completed"


def failed_topic(module: str) -> str:
    return f"email.{module}.failed"


def all_agent_topics() -> list[str]:
    """Every topic an agent consumer or the orchestrator needs to know
    about at startup (for topic auto-creation / admin bootstrapping)."""
    topics = [TOPIC_EMAIL_PROCESSING_REQUESTED, TOPIC_AGENT_FAILED, TOPIC_WORKFLOW_COMPLETED, TOPIC_DEAD_LETTER]
    for module in AGENT_MODULES:
        topics += [requested_topic(module), completed_topic(module), failed_topic(module)]
    return topics
