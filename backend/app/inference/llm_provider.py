"""
Protocol boundary for Module 10's LLM backend (Phase 10, Step 11).

Mirrors every other module's `*ClassifierBackend`/`EmbeddingBackend`
Protocol: `AutoReplyService` depends on this Protocol, never on a concrete
provider (`GroqProvider`/`OllamaProvider`) or SDK (`groq`) directly --
swapping which provider is served is a constructor argument, not a
business-logic change. This is what let `OllamaProvider`
(`app/inference/ollama_provider.py`, Post-Phase-10 fix #5) slot in as a
fallback with zero changes to AutoReplyService itself -- see
`app/inference/fallback_llm_provider.py`, which composes two
`LLMProvider`s and is itself just another `LLMProvider` implementation,
not a new Protocol.

Three failure modes are distinguished, not collapsed into one generic
exception, because Step 7's generation-policy states need to tell them
apart: a timeout (`LLMTimeoutError`) should record `TIMEOUT`; any other
provider failure (`LLMProviderError`) should record `LLM_FAILURE` --
different operational signals worth keeping separate in
`reply_drafts.generation_policy`. `LLMRateLimitedError`/
`LLMServiceUnavailableError` are BOTH `LLMProviderError` subclasses (so
every existing `except LLMProviderError` catch site keeps working
unchanged) added specifically so `FallbackLLMProvider` can distinguish
"Groq returned a 429 or 503, worth falling back to Ollama for" from any
other failure (a malformed request, an empty completion) that a different
model wouldn't fix either -- falling back in that case would just spend
the timeout budget twice for the same result.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class LLMTimeoutError(RuntimeError):
    """The provider did not respond within the caller-specified timeout budget."""


class LLMProviderError(RuntimeError):
    """The provider responded with a failure (rate limit, auth, unavailable, malformed response)."""


class LLMRateLimitedError(LLMProviderError):
    """The provider rejected the request due to rate limiting (HTTP 429) --
    a `FallbackLLMProvider` trigger, see module docstring."""


class LLMServiceUnavailableError(LLMProviderError):
    """The provider's service itself is unavailable (HTTP 5xx / 503) --
    a `FallbackLLMProvider` trigger, see module docstring."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    model: str
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None


@runtime_checkable
class LLMProvider(Protocol):
    provider_name: str
    model_name: str

    def generate(self, system_prompt: str, user_prompt: str, timeout_seconds: float) -> LLMResult:
        """Raises LLMTimeoutError or LLMProviderError on failure -- never
        returns a partial/empty LLMResult to signal failure silently
        (RULE 9, same "never mask a failure as an empty success" stance
        Phase 9's vector-store/embedding failures already follow)."""
        ...
