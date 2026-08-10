"""
Composes two LLMProvider implementations, falling back from a primary to
a secondary specifically on rate-limit (429) or service-unavailable (503)
conditions (Post-Phase-10 fix #5) -- not on every failure. Retrying a
malformed-request, empty-completion, or auth failure against a different
model wouldn't fix the underlying problem, and would just spend the
fallback's own latency budget for nothing; those still raise straight
through as `LLMProviderError`/`LLMTimeoutError`, no fallback attempted.

Implements `LLMProvider` itself -- no new Protocol needed (the existing
one already covers this; see app/inference/llm_provider.py's module
docstring), so `AutoReplyService` needs zero changes to use this instead
of a bare `GroqProvider`.

Disclosed simplification: the fallback call reuses the SAME
`timeout_seconds` budget the primary was given, not a reduced remaining
budget -- in a fallback scenario, total wall-clock time can exceed the
nominal per-call budget. Not fixed here: correctly time-accounting a
budget across two sequential external calls is real complexity this
fix's scope (a minimal, working fallback) doesn't require yet; disclosed
in docs/architecture_auto_reply.md rather than silently assumed away.
"""

import logging

from app.inference.llm_provider import (
    LLMProvider,
    LLMRateLimitedError,
    LLMResult,
    LLMServiceUnavailableError,
)

logger = logging.getLogger("app.auto_reply")


class FallbackLLMProvider(LLMProvider):
    def __init__(self, primary: LLMProvider, fallback: LLMProvider):
        self._primary = primary
        self._fallback = fallback
        self.provider_name = f"{primary.provider_name}_with_{fallback.provider_name}_fallback"
        self.model_name = primary.model_name

    def generate(self, system_prompt: str, user_prompt: str, timeout_seconds: float) -> LLMResult:
        try:
            return self._primary.generate(system_prompt, user_prompt, timeout_seconds)
        except (LLMRateLimitedError, LLMServiceUnavailableError) as e:
            logger.warning(
                "llm_primary_unavailable_falling_back",
                extra={
                    "primary": self._primary.provider_name,
                    "fallback": self._fallback.provider_name,
                    "error_type": type(e).__name__,
                },
            )
            return self._fallback.generate(system_prompt, user_prompt, timeout_seconds)
