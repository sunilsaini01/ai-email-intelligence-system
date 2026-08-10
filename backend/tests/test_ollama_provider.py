"""
Unit tests for OllamaProvider (Post-Phase-10 fix #5) -- NEVER makes a real
network call. `httpx.post` is monkeypatched to a fake response.
"""

import httpx
import pytest

from app.inference.llm_provider import LLMProviderError, LLMTimeoutError
from app.inference.ollama_provider import OllamaProvider


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://localhost:11434/api/chat")
            raise httpx.HTTPStatusError("error", request=request, response=httpx.Response(self.status_code, request=request))

    def json(self):
        return self._json_data


def test_successful_generation_returns_text_and_token_counts(monkeypatch):
    def fake_post(url, json, timeout):
        assert url == "http://localhost:11434/api/chat"
        assert json["model"] == "mistral:7b"
        assert json["stream"] is False
        return _FakeResponse({"message": {"role": "assistant", "content": "Hello there."}, "prompt_eval_count": 10, "eval_count": 3})

    monkeypatch.setattr("httpx.post", fake_post)
    provider = OllamaProvider()

    result = provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)

    assert result.text == "Hello there."
    assert result.provider == "ollama"
    assert result.model == "mistral:7b"
    assert result.input_tokens == 10
    assert result.output_tokens == 3


def test_custom_model_and_base_url_used_in_request(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["model"] = json["model"]
        return _FakeResponse({"message": {"content": "ok"}})

    monkeypatch.setattr("httpx.post", fake_post)
    provider = OllamaProvider(model="qwen2.5:3b", base_url="http://localhost:11434")

    provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)

    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["model"] == "qwen2.5:3b"


def test_timeout_raises_llm_timeout_error(monkeypatch):
    def fake_post(url, json, timeout):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("httpx.post", fake_post)
    provider = OllamaProvider()

    with pytest.raises(LLMTimeoutError):
        provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)


def test_connection_error_raises_llm_provider_error(monkeypatch):
    """The expected case whenever no local Ollama server is running."""

    def fake_post(url, json, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("httpx.post", fake_post)
    provider = OllamaProvider()

    with pytest.raises(LLMProviderError):
        provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)


def test_empty_completion_raises_provider_error(monkeypatch):
    monkeypatch.setattr("httpx.post", lambda url, json, timeout: _FakeResponse({"message": {"content": ""}}))
    provider = OllamaProvider()

    with pytest.raises(LLMProviderError):
        provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)


def test_http_error_status_raises_provider_error(monkeypatch):
    monkeypatch.setattr("httpx.post", lambda url, json, timeout: _FakeResponse({}, status_code=500))
    provider = OllamaProvider()

    with pytest.raises(LLMProviderError):
        provider.generate(system_prompt="sys", user_prompt="user", timeout_seconds=8.0)
