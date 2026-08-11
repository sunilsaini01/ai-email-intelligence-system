"""
AutoReplyService (Module 10 / Phase 10, FR-48/FR-50).

Deliberately narrow, same "service does the sync/CPU-bound work, the
endpoint does the async DB calls" split Phase 9's RetrievalService already
established (see that class's own module docstring): this service has NO
database session. Retrieving similar RESOLVED emails is split across two
layers on purpose -- the vector search (CPU-bound) happens via the shared
`RetrievalService` (reused, not duplicated), and the resolution-status/
is_deleted filtering against fresh Postgres happens in the endpoint
(app/api/v1/endpoints/reply.py), exactly mirroring how
`app/api/v1/endpoints/retrieval.py::search_similar_emails` already filters
vector-store candidates against the DB. This service receives the
already-filtered `RetrievedContextItem` list, not raw vector matches.

Generation policy (Step 7) is decided here, not in the endpoint, because it
depends on CPU-bound checks (PII entity types found, an injection-heuristic
scan) that belong next to the anonymization/prompt-construction logic they
read from.
"""

import logging
import re
from functools import lru_cache

from app.inference.llm_provider import LLMProvider, LLMProviderError, LLMTimeoutError
from app.models.reply_draft import (
    POLICY_LLM_FAILURE,
    POLICY_NEEDS_HUMAN_REVIEW,
    POLICY_NO_SIMILAR_EMAILS,
    POLICY_NORMAL_REPLY,
    POLICY_TIMEOUT,
    POLICY_UNSAFE_CONTENT,
)
from app.nlp.reply_prompt import RetrievedContextItem, build_reply_prompt
from app.preprocessing.email_preprocessor import SUMMARY_CONFIG, EmailPreprocessor
from app.security.pii_anonymizer import anonymize_email_body

logger = logging.getLogger("app.auto_reply")

# Cosine-similarity floor below which a retrieved "similar" email is treated
# as noise rather than usable context (Step 4/Step 10's "low-quality match"
# gate). HEURISTIC, not derived from a measured precision/recall curve --
# no labelled retrieval-relevance dataset exists (docs/error_analysis_retrieval.md),
# same class of disclosed heuristic as retrieval.py's own _OVERFETCH_MULTIPLIER.
MIN_CONTEXT_SCORE = 0.35

MAX_CONTEXT_ITEMS = 3  # FR-48 -- "top-3 similar resolved emails"

# Hallucination-mitigation confidence gate (Post-Phase-10 fix #1). Below
# this many usable RESOLVED context items, a draft is still generated (a
# refusal-to-draft-at-all was rejected as a design choice in Phase 10 --
# see docs/architecture_auto_reply.md "Resolved-Email Data Reality," the
# common case is exactly this low-context situation) but a visible warning
# is appended so a reviewing agent knows this draft leans more on the
# model's own judgment than on a real precedent. HEURISTIC threshold, not
# derived from a measured hallucination-rate curve -- no such data exists
# (docs/error_analysis_auto_reply.md's fabricated-support-hours finding is
# a single data point, not a curve).
MIN_CONFIDENT_CONTEXT_COUNT = 2
LOW_CONTEXT_WARNING = "Note: limited historical context — verify before sending."

# Cheap, explicitly-disclosed heuristic pre-filter, NOT a security guarantee
# (the real defense is prompt-level data/instruction separation -- see
# app/nlp/reply_prompt.py's SYSTEM_PROMPT and docs/security_auto_reply.md).
# Flags the current email for UNSAFE_CONTENT (generation skipped entirely)
# when it contains a classic prompt-injection phrase.
_INJECTION_PHRASES = re.compile(
    r"ignore (all )?previous instructions|disregard (the )?above|you are now|"
    r"new instructions:|system prompt|act as if|reveal your instructions",
    re.IGNORECASE,
)

# Entity types where generation is still safe (the anonymized text sent to
# the LLM never contains them) but a human should look before this draft is
# sent, given what the underlying email is actually about.
_SENSITIVE_ENTITY_TYPES = {"CREDIT_CARD", "US_SSN", "IBAN_CODE", "US_BANK_NUMBER"}

_preprocessor = EmailPreprocessor(SUMMARY_CONFIG)


class GenerationOutcome:
    def __init__(
        self,
        generation_policy: str,
        generated_text: str | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        llm_latency_ms: float | None = None,
        failure_reason: str | None = None,
    ):
        self.generation_policy = generation_policy
        self.generated_text = generated_text
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.llm_latency_ms = llm_latency_ms
        self.failure_reason = failure_reason


class AutoReplyService:
    def __init__(self, llm_provider: LLMProvider | None = None):
        self._llm_provider = llm_provider

    def _resolve_llm_provider(self) -> LLMProvider:
        """Default: Groq, with an Ollama fallback for 429/503 specifically
        (Post-Phase-10 fix #5) -- see app/inference/fallback_llm_provider.py.
        Constructing OllamaProvider here is cheap and makes no network call
        (same lazy-construction convention as everywhere else); the
        fallback is only ever actually invoked, and only ever pays
        Ollama's own cost, when Groq genuinely returns a 429/503."""
        if self._llm_provider is not None:
            return self._llm_provider
        from app.core.config import get_settings
        from app.inference.fallback_llm_provider import FallbackLLMProvider
        from app.inference.groq_provider import GroqProvider
        from app.inference.ollama_provider import OllamaProvider

        settings = get_settings()
        groq = GroqProvider(api_keys=settings.GROQ_API_KEYS, model=settings.GROQ_MODEL)
        ollama = OllamaProvider(model=settings.OLLAMA_MODEL, base_url=settings.OLLAMA_BASE_URL)
        return FallbackLLMProvider(primary=groq, fallback=ollama)

    def anonymize(self, subject: str, body: str) -> tuple[str, str, list[str]]:
        """Re-anonymizes text for LLM-prompt use (Section C.5/C.6 finding:
        `emails.body` in Postgres is raw, NOT safe to send to an external
        API as-is -- Phase 9's anonymization only covered the embedding
        path). Returns (anon_subject, anon_body, entity_types_found)."""
        subject = subject or ""
        body = body or ""
        cleaned_body = _preprocessor.process(body)
        anon_subject, subject_entities = anonymize_email_body(subject) if subject.strip() else (subject, [])
        anon_body, body_entities = anonymize_email_body(cleaned_body)
        return anon_subject, anon_body, list(set(subject_entities) | set(body_entities))

    def generate(
        self,
        current_subject: str,
        current_body: str,
        retrieved_context: list[RetrievedContextItem],
        llm_timeout_seconds: float,
    ) -> GenerationOutcome:
        anon_subject, anon_body, entity_types = self.anonymize(current_subject, current_body)

        if _INJECTION_PHRASES.search(current_subject or "") or _INJECTION_PHRASES.search(current_body or ""):
            logger.warning("auto_reply_unsafe_content_detected", extra={"entity_types_found": entity_types})
            return GenerationOutcome(generation_policy=POLICY_UNSAFE_CONTENT, failure_reason="injection_heuristic_matched")

        anonymized_context = [
            RetrievedContextItem(
                email_id=item.email_id,
                subject=anonymize_email_body(item.subject)[0] if item.subject else item.subject,
                body=anonymize_email_body(_preprocessor.process(item.body))[0],
                resolution_status=item.resolution_status,
            )
            for item in retrieved_context[:MAX_CONTEXT_ITEMS]
        ]

        base_policy = POLICY_NORMAL_REPLY if anonymized_context else POLICY_NO_SIMILAR_EMAILS
        if _SENSITIVE_ENTITY_TYPES & set(entity_types):
            base_policy = POLICY_NEEDS_HUMAN_REVIEW

        system_prompt, user_prompt = build_reply_prompt(
            current_subject=anon_subject,
            current_body=anon_body,
            retrieved_context=anonymized_context,
            category=None,
            department=None,
        )

        try:
            result = self._resolve_llm_provider().generate(
                system_prompt=system_prompt, user_prompt=user_prompt, timeout_seconds=llm_timeout_seconds
            )
        except LLMTimeoutError as e:
            logger.error("auto_reply_llm_timeout", exc_info=True)
            return GenerationOutcome(generation_policy=POLICY_TIMEOUT, failure_reason=str(e))
        except LLMProviderError as e:
            logger.error("auto_reply_llm_failure", exc_info=True)
            return GenerationOutcome(generation_policy=POLICY_LLM_FAILURE, failure_reason=str(e))

        generated_text = result.text
        if len(anonymized_context) < MIN_CONFIDENT_CONTEXT_COUNT:
            generated_text = f"{generated_text}\n\n{LOW_CONTEXT_WARNING}"

        return GenerationOutcome(
            generation_policy=base_policy,
            generated_text=generated_text,
            llm_provider=result.provider,
            llm_model=result.model,
            llm_latency_ms=result.latency_ms,
        )


def select_context(
    candidates: list[dict], min_score: float = MIN_CONTEXT_SCORE, max_items: int = MAX_CONTEXT_ITEMS
) -> list[dict]:
    """Pure filtering/ranking helper (Step 16 -- separate retrieval quality
    from generation quality, keep this independently testable). `candidates`
    are dicts already filtered by the endpoint for resolution_status/
    is_deleted (DB state); this only applies the similarity-score gate and
    truncates to FR-48's top-3."""
    usable = [c for c in candidates if c["score"] >= min_score]
    usable.sort(key=lambda c: c["score"], reverse=True)
    return usable[:max_items]


@lru_cache
def get_auto_reply_service() -> AutoReplyService:
    return AutoReplyService()
