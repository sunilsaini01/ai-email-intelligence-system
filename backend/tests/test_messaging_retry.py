"""FR-66 retry-policy unit tests: error classification + exponential
backoff (Module 13 / Phase 12)."""

import pytest
from pydantic import BaseModel, ValidationError

from app.messaging.retry import (
    PERMANENT,
    TRANSIENT,
    PermanentAgentError,
    TransientAgentError,
    classify_exception,
    compute_backoff_seconds,
)


class _Dummy(BaseModel):
    x: int


def test_transient_agent_error_classifies_as_transient():
    assert classify_exception(TransientAgentError("boom")) == TRANSIENT


def test_permanent_agent_error_classifies_as_permanent():
    assert classify_exception(PermanentAgentError("boom")) == PERMANENT


def test_pydantic_validation_error_classifies_as_permanent():
    try:
        _Dummy(x="not an int")
    except ValidationError as e:
        assert classify_exception(e) == PERMANENT
    else:
        pytest.fail("expected ValidationError")


def test_unclassified_exception_defaults_to_transient():
    assert classify_exception(RuntimeError("network blip")) == TRANSIENT


def test_backoff_is_exponential_in_the_attempt_number():
    assert compute_backoff_seconds(1, base_seconds=2.0) == 2.0
    assert compute_backoff_seconds(2, base_seconds=2.0) == 4.0
    assert compute_backoff_seconds(3, base_seconds=2.0) == 8.0


def test_backoff_strictly_increases_across_attempts():
    delays = [compute_backoff_seconds(n, base_seconds=2.0) for n in range(1, 4)]
    assert delays == sorted(delays)
    assert len(set(delays)) == len(delays)
