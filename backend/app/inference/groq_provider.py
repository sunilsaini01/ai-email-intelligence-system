"""
Groq LLMProvider implementation (Phase 10, Step 5/Step 11 -- FR-48/FR-50).

Groq was chosen over the PRD's own named OpenAI/Anthropic options (ADR-002)
per an explicit project-owner decision, not assumed -- see
docs/architecture_auto_reply.md "LLM Provider Decision" for the full
record, same disclosure standard Phase 9 used when it overrode the PRD's
`sentence-transformers` suggestion after finding it broken in this
environment.

Multi-key rotation: Groq's own rate limits apply at the ORGANIZATION
level, not per API key (verified directly against Groq's rate-limits
documentation before this was built) -- so extra keys from the SAME
account do NOT multiply throughput. What they DO provide: resilience if
one key is revoked/misconfigured, and genuine extra throughput if the
keys belong to separate accounts. `settings.GROQ_API_KEYS` (a list, one
required, up to five) is consumed here as an ordered rotation list -- on
a RateLimitError or AuthenticationError (both are plausibly key-specific,
unlike a malformed-request error, which rotating keys can't fix), the
next key is tried; the client-level object is built once per key and
reused, not rebuilt per call.

Timeout enforcement: `timeout_seconds` is passed straight to the SDK
call's own `timeout` override (httpx-backed, same mechanism openai-python
uses) -- the provider itself never spins its own thread/asyncio timer
around a blocking call, trusting the SDK's own cancellation instead,
consistent with this codebase not building bespoke timeout machinery
where the underlying client already provides one (unlike
DB_WRITE_TIMEOUT_SECONDS, which exists because asyncpg's own connect()
timeout did NOT reliably bound a real hang -- see
docs/technical_debt/database_write_hang.md; no equivalent gap has been
found here).
"""

import logging
import time

from app.inference.llm_provider import (
    LLMProvider,
    LLMProviderError,
    LLMRateLimitedError,
    LLMResult,
    LLMServiceUnavailableError,
    LLMTimeoutError,
)

logger = logging.getLogger("app.auto_reply")


class GroqProviderUnavailable(RuntimeError):
    """Raised at construction time when no Groq API key is configured."""


class GroqProvider(LLMProvider):
    provider_name = "groq"

    def __init__(self, api_keys: list[str], model: str):
        if not api_keys:
            raise GroqProviderUnavailable(
                "No Groq API key configured. Set GROQ_API_KEY in backend/.env."
            )

        from groq import Groq  # lazy import -- matches this codebase's heavy-dependency convention

        self.model_name = model
        self._clients = [Groq(api_key=key) for key in api_keys]

    def generate(self, system_prompt: str, user_prompt: str, timeout_seconds: float) -> LLMResult:
        from groq import (
            APIConnectionError,
            APITimeoutError,
            AuthenticationError,
            InternalServerError,
            RateLimitError,
        )

        start = time.perf_counter()
        last_error: Exception | None = None
        any_key_rate_limited = False

        for index, client in enumerate(self._clients):
            try:
                completion = client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    timeout=timeout_seconds,
                )
            except RateLimitError as e:
                # Plausibly key-specific (this key's own quota) -- rotate.
                last_error = e
                any_key_rate_limited = True
                logger.warning(
                    "groq_key_failed_rotating",
                    extra={"key_index": index, "error_type": type(e).__name__},
                )
                continue
            except AuthenticationError as e:
                # Plausibly key-specific (this key is bad/revoked) -- rotate.
                last_error = e
                logger.warning(
                    "groq_key_failed_rotating",
                    extra={"key_index": index, "error_type": type(e).__name__},
                )
                continue
            except APITimeoutError as e:
                raise LLMTimeoutError(f"Groq request exceeded {timeout_seconds}s budget") from e
            except InternalServerError as e:
                # Groq's own service, not a specific key -- rotating keys
                # wouldn't help; this IS the 503 case Post-Phase-10 fix #5's
                # FallbackLLMProvider is built to catch.
                raise LLMServiceUnavailableError(f"Groq service unavailable: {e}") from e
            except APIConnectionError as e:
                # Network-level, not key-specific -- rotating won't help.
                raise LLMProviderError(f"Groq connection failed: {e}") from e
            except Exception as e:
                # Malformed request, unexpected error shape, etc. -- also not fixed by rotating keys.
                raise LLMProviderError(f"Groq request failed: {e}") from e

            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            choice = completion.choices[0] if completion.choices else None
            text = (choice.message.content or "").strip() if choice else ""
            if not text:
                raise LLMProviderError("Groq returned an empty completion.")

            usage = getattr(completion, "usage", None)
            return LLMResult(
                text=text,
                provider=self.provider_name,
                model=self.model_name,
                latency_ms=latency_ms,
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
            )

        # All keys exhausted via rotation (RateLimitError/AuthenticationError
        # only -- Timeout/ConnectionError/other raise immediately above,
        # never reach here). LLMRateLimitedError specifically when at least
        # one key hit a real 429, so FallbackLLMProvider knows this was a
        # genuine rate-limit exhaustion, not just bad credentials everywhere
        # (a config problem a different provider wouldn't fix either).
        if any_key_rate_limited:
            raise LLMRateLimitedError(
                f"All {len(self._clients)} configured Groq key(s) were rate-limited. Last error: {last_error}"
            )
        raise LLMProviderError(
            f"All {len(self._clients)} configured Groq key(s) failed. Last error: {last_error}"
        )
