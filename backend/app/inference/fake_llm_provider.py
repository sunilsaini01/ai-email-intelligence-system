"""
Deterministic LLMProvider fake for tests (Phase 10, Step 17: "Never require
a paid API key for the standard test suite").

Mirrors every other module's test-fake precedent (Phase 9's
InMemoryVectorStore, this codebase's duck-typed fake services elsewhere) --
a real object satisfying the Protocol, not a mock library patch, so tests
exercise real AutoReplyService/prompt-construction code against a real
(if trivial) collaborator.
"""

import time

from app.inference.llm_provider import LLMProvider, LLMProviderError, LLMResult, LLMTimeoutError


class FakeLLMProvider(LLMProvider):
    provider_name = "fake"
    model_name = "fake-deterministic-v1"

    def __init__(
        self,
        response_text: str = "Thank you for reaching out. We're looking into this and will follow up shortly.",
        raise_timeout: bool = False,
        raise_error: bool = False,
    ):
        self._response_text = response_text
        self._raise_timeout = raise_timeout
        self._raise_error = raise_error
        self.calls: list[dict] = []

    def generate(self, system_prompt: str, user_prompt: str, timeout_seconds: float) -> LLMResult:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt, "timeout_seconds": timeout_seconds})

        if self._raise_timeout:
            raise LLMTimeoutError("fake provider configured to simulate a timeout")
        if self._raise_error:
            raise LLMProviderError("fake provider configured to simulate a provider failure")

        start = time.perf_counter()
        return LLMResult(
            text=self._response_text,
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
            input_tokens=len(system_prompt.split()) + len(user_prompt.split()),
            output_tokens=len(self._response_text.split()),
        )
