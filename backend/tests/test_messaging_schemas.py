"""Message contract round-trip tests (FR-65's versioned schemas, Module 13
/ Phase 12) -- guards against producer/consumer schema drift, the exact
failure mode app/messaging/schemas.py's module docstring warns about."""

import uuid

from app.messaging.schemas import SCHEMA_VERSION, AgentEvent, DeadLetterEnvelope


def _make_event(**overrides) -> AgentEvent:
    defaults = dict(
        job_id=uuid.uuid4(),
        email_id=uuid.uuid4(),
        event_type="email.spam.requested",
        correlation_id=uuid.uuid4(),
        payload={"subject": "hi", "body": "there"},
    )
    defaults.update(overrides)
    return AgentEvent(**defaults)


def test_agent_event_round_trips_through_kafka_bytes():
    event = _make_event()
    raw = event.to_kafka_value()
    restored = AgentEvent.from_kafka_value(raw)

    assert restored.job_id == event.job_id
    assert restored.email_id == event.email_id
    assert restored.event_type == event.event_type
    assert restored.correlation_id == event.correlation_id
    assert restored.payload == event.payload
    assert restored.schema_version == SCHEMA_VERSION


def test_agent_event_defaults_event_id_and_retry_count():
    event = _make_event()
    assert isinstance(event.event_id, uuid.UUID)
    assert event.retry_count == 0


def test_agent_event_older_consumer_ignores_unknown_future_fields():
    """Additive schema evolution (module docstring): a message with an
    extra, not-yet-known field must not crash a consumer running this
    version of the schema."""
    event = _make_event()
    raw_dict = event.model_dump(mode="json")
    raw_dict["a_future_field_this_version_does_not_know_about"] = "value"
    import json

    restored = AgentEvent.model_validate_json(json.dumps(raw_dict))
    assert restored.job_id == event.job_id


def test_dead_letter_envelope_round_trips_and_carries_original_event():
    original = _make_event(retry_count=3)
    envelope = DeadLetterEnvelope(
        original_event=original,
        source_topic="email.spam.requested",
        agent="spam",
        failure_reason="model artifact missing",
        error_type="transient",
        retry_count=3,
        correlation_id=original.correlation_id,
    )
    raw = envelope.to_kafka_value()
    restored = DeadLetterEnvelope.from_kafka_value(raw)

    assert restored.original_event.job_id == original.job_id
    assert restored.agent == "spam"
    assert restored.retry_count == 3
    assert restored.failure_reason == "model artifact missing"
