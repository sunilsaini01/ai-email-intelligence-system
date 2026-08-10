"""
Unit tests for GroqProvider (Module 10 / Phase 10) -- NEVER makes a real
network call. `groq.Groq` is monkeypatched to a fake client whose behavior
per API key is scripted per test, so multi-key rotation on RateLimitError/
AuthenticationError can be verified deterministically. Real exception
INSTANCES (imported from the real `groq` package) are raised, not
hand-rolled lookalikes, so this test exercises the actual `except` clauses
in app/inference/groq_provider.py against the real exception hierarchy.
"""

import httpx
import pytest
from groq import APIConnectionError, APITimeoutError, AuthenticationError, InternalServerError, RateLimitError

from app.inference.groq_provider import GroqProvider, GroqProviderUnavailable
from app.inference.llm_provider import (
    LLMProviderError,
    LLMRateLimitedError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
)


def _request():
    return httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _rate_limit_error():
    return RateLimitError("rate limited", response=httpx.Response(429, request=_request()), body=None)


def _internal_server_error():
    return InternalServerError("service unavailable", response=httpx.Response(503, request=_request()), body=None)


def _auth_error():
    return AuthenticationError("bad key", response=httpx.Response(401, request=_request()), body=None)


class _FakeChoice:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class _FakeUsage:
    prompt_tokens = 42
    completion_tokens = 7


class _FakeCompletion:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self, behavior):
        self._behavior = behavior

    def create(self, **kwargs):
        if isinstance(self._behavior, Exception):
            raise self._behavior
        return _FakeCompletion(self._behavior)


class _FakeClient:
    def __init__(self, behavior):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(behavior)})()


@pytest.fixture
def fake_groq(monkeypatch):
    """Returns a function that patches groq.Groq so GroqProvider's
    per-key clients are scripted by this dict, keyed by api_key string."""

    def _patch(behaviors: dict[str, object]):
        def _fake_constructor(api_key):
            return _FakeClient(behaviors[api_key])

        monkeypatch.setattr("groq.Groq", _fake_constructor)

    return _patch


def test_no_keys_raises_unavailable():
    with pytest.raises(GroqProviderUnavailable):
        GroqProvider(api_keys=[], model="llama-3.3-70b-versatile")


def test_successful_generation_returns_text_and_usage(fake_groq):
    fake_groq({"key1": "Thanks for reaching out, we'll help with that."})
    provider = GroqProvider(api_keys=["key1"], model="llama-3.3-70b-versatile")

    result = provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)

    assert result.text == "Thanks for reaching out, we'll help with that."
    assert result.provider == "groq"
    assert result.input_tokens == 42
    assert result.output_tokens == 7


def test_rate_limit_on_first_key_rotates_to_second_key(fake_groq):
    fake_groq({"key1": _rate_limit_error(), "key2": "success from key2"})
    provider = GroqProvider(api_keys=["key1", "key2"], model="llama-3.3-70b-versatile")

    result = provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)

    assert result.text == "success from key2"


def test_auth_error_on_first_key_rotates_to_second_key(fake_groq):
    fake_groq({"key1": _auth_error(), "key2": "success from key2"})
    provider = GroqProvider(api_keys=["key1", "key2"], model="llama-3.3-70b-versatile")

    result = provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)

    assert result.text == "success from key2"


def test_all_keys_rate_limited_raises_provider_error(fake_groq):
    fake_groq({"key1": _rate_limit_error(), "key2": _rate_limit_error()})
    provider = GroqProvider(api_keys=["key1", "key2"], model="llama-3.3-70b-versatile")

    with pytest.raises(LLMProviderError):
        provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)


def test_all_keys_rate_limited_raises_specifically_llm_rate_limited_error(fake_groq):
    """Post-Phase-10 fix #5 -- FallbackLLMProvider needs this specific
    subclass to know a fallback is warranted (a 429, not just any failure)."""
    fake_groq({"key1": _rate_limit_error(), "key2": _rate_limit_error()})
    provider = GroqProvider(api_keys=["key1", "key2"], model="llama-3.3-70b-versatile")

    with pytest.raises(LLMRateLimitedError):
        provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)


def test_one_key_rate_limited_among_others_still_raises_rate_limited_error(fake_groq):
    """Any key hitting a real 429 is enough to classify the overall failure
    as rate-limit-triggered, even if a different key failed for a different
    reason (auth) -- 'Groq returned a 429' happened during this attempt."""
    fake_groq({"key1": _auth_error(), "key2": _rate_limit_error()})
    provider = GroqProvider(api_keys=["key1", "key2"], model="llama-3.3-70b-versatile")

    with pytest.raises(LLMRateLimitedError):
        provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)


def test_all_keys_auth_failed_raises_generic_provider_error_not_rate_limited(fake_groq):
    """All-auth-failure is a config problem, not a 429/503 -- must NOT
    trigger FallbackLLMProvider's fallback (a different provider wouldn't
    fix bad Groq credentials either)."""
    fake_groq({"key1": _auth_error(), "key2": _auth_error()})
    provider = GroqProvider(api_keys=["key1", "key2"], model="llama-3.3-70b-versatile")

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)
    assert not isinstance(exc_info.value, LLMRateLimitedError)


def test_internal_server_error_raises_service_unavailable_and_does_not_rotate(fake_groq):
    """Post-Phase-10 fix #5's 503 case -- not key-specific, so no rotation,
    and raised as the specific subclass FallbackLLMProvider watches for."""
    fake_groq({"key1": _internal_server_error(), "key2": "should never be reached"})
    provider = GroqProvider(api_keys=["key1", "key2"], model="llama-3.3-70b-versatile")

    with pytest.raises(LLMServiceUnavailableError):
        provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)


def test_timeout_raises_llm_timeout_error_not_provider_error(fake_groq):
    fake_groq({"key1": APITimeoutError(request=_request())})
    provider = GroqProvider(api_keys=["key1"], model="llama-3.3-70b-versatile")

    with pytest.raises(LLMTimeoutError):
        provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)


def test_timeout_does_not_rotate_keys(fake_groq):
    """A timeout is not key-specific -- rotating to a second key would just
    blow the latency budget for no benefit, so it must raise immediately."""
    fake_groq({"key1": APITimeoutError(request=_request()), "key2": "should never be reached"})
    provider = GroqProvider(api_keys=["key1", "key2"], model="llama-3.3-70b-versatile")

    with pytest.raises(LLMTimeoutError):
        provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)


def test_connection_error_does_not_rotate_keys(fake_groq):
    fake_groq({"key1": APIConnectionError(request=_request()), "key2": "should never be reached"})
    provider = GroqProvider(api_keys=["key1", "key2"], model="llama-3.3-70b-versatile")

    with pytest.raises(LLMProviderError):
        provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)


def test_empty_completion_raises_provider_error(fake_groq):
    fake_groq({"key1": ""})
    provider = GroqProvider(api_keys=["key1"], model="llama-3.3-70b-versatile")

    with pytest.raises(LLMProviderError):
        provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)
