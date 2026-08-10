"""
Ollama LLMProvider implementation (Post-Phase-10 fix #5).

Talks to a locally-running Ollama server's REST API directly (`/api/chat`)
via `httpx` -- no `ollama` SDK package added, matching this codebase's
general preference for a direct HTTP call over a wrapper SDK when the API
surface needed is this small (one endpoint, one call shape), the same
reasoning `app/inference/minilm_embedder.py` used to avoid the broken
`sentence-transformers` wrapper in favor of `transformers` directly.

Verified directly against a real, locally-running Ollama server during
this fix (not just unit-tested against a fake) -- see
docs/architecture_auto_reply.md "Ollama Fallback" for the exact
verification and its one disclosed caveat (the configured default model,
`mistral:7b`, was not pulled in the verification environment; the request/
response wiring was confirmed against a different, already-pulled model
instead).

No API key, no construction-time availability check (unlike GroqProvider)
-- Ollama needs no credential, only a reachable local server, which is
checked lazily at `generate()` time, same lazy-construction convention
every other heavy/external dependency in this codebase follows.
"""

import logging
import time

import httpx

from app.inference.llm_provider import LLMProvider, LLMProviderError, LLMResult, LLMTimeoutError

logger = logging.getLogger("app.auto_reply")

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "mistral:7b"


class OllamaProvider(LLMProvider):
    provider_name = "ollama"

    def __init__(self, model: str = DEFAULT_OLLAMA_MODEL, base_url: str = DEFAULT_OLLAMA_BASE_URL):
        self.model_name = model
        self._base_url = base_url.rstrip("/")

    def generate(self, system_prompt: str, user_prompt: str, timeout_seconds: float) -> LLMResult:
        start = time.perf_counter()
        try:
            response = httpx.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self.model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"Ollama request exceeded {timeout_seconds}s budget") from e
        except httpx.HTTPError as e:
            # Covers both connection failures (Ollama not running locally --
            # the expected case whenever this fallback is exercised without
            # a local Ollama install) and non-2xx responses.
            raise LLMProviderError(f"Ollama request failed: {e}") from e

        data = response.json()
        text = (data.get("message", {}).get("content") or "").strip()
        if not text:
            raise LLMProviderError("Ollama returned an empty completion.")

        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return LLMResult(
            text=text,
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=latency_ms,
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
        )
