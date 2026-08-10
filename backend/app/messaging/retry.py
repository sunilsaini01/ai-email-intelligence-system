"""
FR-66 retry policy: error classification + exponential backoff.

Why classify errors before deciding to retry at all (master prompt section
10): a malformed payload will fail identically on attempt 2 and 3 -- retrying
it three times just delays the DLQ signal an operator needs, for zero
chance of success. Only TRANSIENT failures (network blips, a momentarily
unavailable model artifact, Kafka/DB unavailable) are worth the backoff
delay.

Default classification for an exception an agent doesn't explicitly
classify: TRANSIENT. Reasoning: this codebase's existing per-signal
failure isolation (RoutingService._safe_call) already treats "unexpected
exception" as "signal unavailable, don't crash the caller" rather than
"definitely a permanent bug" -- an unclassified exception being transient-
by-default is consistent with that stance, and AGENT_MAX_ATTEMPTS still
bounds it to a small, finite number of retries either way (never infinite,
per Critical Rule #9).
"""

from pydantic import ValidationError

TRANSIENT = "transient"
PERMANENT = "permanent"


class AgentExecutionError(Exception):
    """Base class for errors an agent raises with explicit classification."""

    error_type: str = TRANSIENT


class TransientAgentError(AgentExecutionError):
    error_type = TRANSIENT


class PermanentAgentError(AgentExecutionError):
    """Validation errors, malformed payloads -- retrying cannot help."""

    error_type = PERMANENT


def classify_exception(exc: Exception) -> str:
    if isinstance(exc, AgentExecutionError):
        return exc.error_type
    if isinstance(exc, ValidationError):
        # A malformed AgentEvent payload -- structurally cannot succeed on
        # retry, same reasoning as any other permanent error.
        return PERMANENT
    return TRANSIENT


def compute_backoff_seconds(attempt_number: int, base_seconds: float) -> float:
    """attempt_number is the attempt that just FAILED (1-indexed). Returns
    the delay before the next attempt: base**1, base**2, ... A default
    base of 2.0 gives 2s / 4s / 8s; this project's configured default
    (Settings.AGENT_RETRY_BACKOFF_BASE_SECONDS = 2.0) intentionally starts
    short since local/dev Kafka blips are usually sub-second."""
    return base_seconds**attempt_number
