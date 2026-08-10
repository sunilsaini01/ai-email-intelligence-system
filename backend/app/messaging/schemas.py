"""
Versioned Kafka message contracts (FR-65/PRD section "Message Contracts").

Why explicit Pydantic schemas instead of raw dicts between agents: same
reasoning app/schemas/ already applies to every HTTP request/response in
this codebase -- an uncontrolled dict lets producer/consumer drift apart
silently (a renamed key breaks a consumer with no signal until it's
already in production). `schema_version` is additive-only: a future field
gets added with a default, never renamed/removed, so an older consumer
reading a newer message still parses successfully (ignores fields it
doesn't know about) instead of crashing on an unrecognized shape.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


class AgentEvent(BaseModel):
    """The envelope every message on every email.{module}.* topic uses."""

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    job_id: uuid.UUID  # == workflow_executions.id
    email_id: uuid.UUID
    event_type: str  # e.g. "email.spam.requested" -- matches the topic name
    agent: str | None = None  # populated on *.completed/*.failed, None on *.requested
    schema_version: str = SCHEMA_VERSION
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: uuid.UUID  # == job_id today; kept distinct for a future
    # multi-workflow correlation case without a schema break (see
    # PHASE_12_AUDIT_REPORT.md section 9)
    retry_count: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_kafka_value(self) -> bytes:
        return self.model_dump_json().encode("utf-8")

    @classmethod
    def from_kafka_value(cls, raw: bytes) -> "AgentEvent":
        return cls.model_validate_json(raw)


class DeadLetterEnvelope(BaseModel):
    """Written to TOPIC_DEAD_LETTER (see topics.py) when an agent exhausts
    its retries or hits a permanent (non-retryable) error. Carries the
    ORIGINAL event untouched plus the failure context an operator needs to
    investigate -- master prompt section 11's exact field list."""

    original_event: AgentEvent
    source_topic: str
    agent: str
    failure_reason: str
    error_type: str  # "transient" | "permanent" -- see retry.py
    retry_count: int
    failed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: uuid.UUID

    def to_kafka_value(self) -> bytes:
        return self.model_dump_json().encode("utf-8")

    @classmethod
    def from_kafka_value(cls, raw: bytes) -> "DeadLetterEnvelope":
        return cls.model_validate_json(raw)
