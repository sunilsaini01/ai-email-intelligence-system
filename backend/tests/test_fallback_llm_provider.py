"""
Unit tests for FallbackLLMProvider (Post-Phase-10 fix #5) -- uses two
FakeLLMProvider-style fakes, no real network/API calls.
"""

import pytest

from app.inference.fallback_llm_provider import FallbackLLMProvider
from app.inference.llm_provider import (
    LLMProviderError,
    LLMRateLimitedError,
    LLMResult,
    LLMServiceUnavailableError,
    LLMTimeoutError,
)


class _ScriptedProvider:
    provider_name = "scripted"
    model_name = "scripted-model"

    def __init__(self, behavior):
        self._behavior = behavior
        self.calls = 0

    def generate(self, system_prompt, user_prompt, timeout_seconds):
        self.calls += 1
        if isinstance(self._behavior, Exception):
            raise self._behavior
        return LLMResult(
            text=self._behavior, provider=self.provider_name, model=self.model_name, latency_ms=1.0, input_tokens=1, output_tokens=1
        )


def test_primary_success_never_calls_fallback():
    primary = _ScriptedProvider("primary response")
    fallback = _ScriptedProvider("fallback response")
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    result = provider.generate("sys", "user", timeout_seconds=8.0)

    assert result.text == "primary response"
    assert fallback.calls == 0


def test_rate_limited_primary_falls_back():
    primary = _ScriptedProvider(LLMRateLimitedError("429"))
    fallback = _ScriptedProvider("fallback response")
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    result = provider.generate("sys", "user", timeout_seconds=8.0)

    assert result.text == "fallback response"
    assert fallback.calls == 1


def test_service_unavailable_primary_falls_back():
    primary = _ScriptedProvider(LLMServiceUnavailableError("503"))
    fallback = _ScriptedProvider("fallback response")
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    result = provider.generate("sys", "user", timeout_seconds=8.0)

    assert result.text == "fallback response"


def test_timeout_does_not_fall_back():
    """Only 429/503 trigger fallback -- a timeout propagates straight
    through, since retrying against a different model wouldn't necessarily
    fix a budget the caller already spent."""
    primary = _ScriptedProvider(LLMTimeoutError("timed out"))
    fallback = _ScriptedProvider("should never be reached")
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    with pytest.raises(LLMTimeoutError):
        provider.generate("sys", "user", timeout_seconds=8.0)
    assert fallback.calls == 0


def test_generic_provider_error_does_not_fall_back():
    """A plain LLMProviderError (malformed request, empty completion, bad
    auth) is NOT a fallback trigger -- only the 429/503 subclasses are."""
    primary = _ScriptedProvider(LLMProviderError("malformed request"))
    fallback = _ScriptedProvider("should never be reached")
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    with pytest.raises(LLMProviderError):
        provider.generate("sys", "user", timeout_seconds=8.0)
    assert fallback.calls == 0


def test_provider_name_and_model_name_reflect_composition():
    primary = _ScriptedProvider("x")
    fallback = _ScriptedProvider("y")
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    assert provider.provider_name == "scripted_with_scripted_fallback"
    assert provider.model_name == "scripted-model"


def test_fallback_itself_can_still_fail():
    """If Ollama is also unavailable, the fallback's own failure propagates
    -- there is no third layer, this is not silently swallowed."""
    primary = _ScriptedProvider(LLMRateLimitedError("429"))
    fallback = _ScriptedProvider(LLMProviderError("ollama also unavailable"))
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    with pytest.raises(LLMProviderError):
        provider.generate("sys", "user", timeout_seconds=8.0)
