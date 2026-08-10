"""
RoutingService (Module 8 / Phase 8).

The first composition point in this codebase that calls more than one
upstream ML service together (Spam + Category + Intent + Sentiment +
Priority) -- every prior module's service depends on exactly one predictor.
Composition happens via direct in-process method calls, not HTTP, per
docs/architecture.md's modular-monolith rationale and RULE 11 (no HTTP calls
between components inside the same process).

Per-signal failure isolation (Phase 8 brief SS27): each upstream service
call is wrapped independently via `_safe_call`. A missing/failing service
degrades to "signal unavailable" (recorded in `unavailable`, surfaced in the
response's `upstream_failures`) rather than raising -- this service has no
`RoutingServiceUnavailable`/503 concept of its own, because it has no
trained artifact of its own to be missing (same stance
SentimentService/SummarizationService already take). `route()` always
returns a decision (RULE 10 -- never silently drop an email); worst case is
`R-NO-EVIDENCE-FALLBACK` routing to General with `requires_human_review=True`.

All rule/threshold logic lives in app/routing/rules.py, kept deliberately
pure and independently testable -- this class's only job is: call the five
services, shape their output into RoutingSignals, call resolve_routing(),
and shape the result back into the response dict the API layer returns.
"""

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from app.routing.keyword_matcher import KEYWORD_MATCHER_VERSION, top_department_by_keywords
from app.routing.rules import ROUTING_RULES_VERSION, RoutingSignals, resolve_routing
from app.routing.sender_domain import classify_sender_domain
from app.routing.signal_reliability import SIGNAL_RELIABILITY
from app.services.category_service import CategoryService, get_category_service
from app.services.intent_service import IntentService, get_intent_service
from app.services.priority_service import PriorityService, get_priority_service
from app.services.sentiment_service import SentimentService, get_sentiment_service
from app.services.spam_service import SpamService, get_spam_service

logger = logging.getLogger("app.routing")

# Sentinel distinguishing "caller didn't supply this signal, compute it
# normally" from "caller explicitly supplied None, i.e. this signal is
# known-unavailable" -- see route()'s precomputed_* kwargs, added Phase 12
# so the Orchestrator (app/agents/orchestrator.py) can reuse this class's
# already-tested rule/composition logic WITHOUT re-running the five ML
# calls a second time (they already ran once, as Kafka agents). Existing
# callers (app/api/v1/endpoints/routing.py) pass nothing and get the exact
# prior behavior -- this is purely additive, not a breaking change to the
# existing seam docs/architecture.md describes.
_NOT_PROVIDED = object()


class RoutingService:
    def __init__(
        self,
        spam_service: SpamService | None = None,
        priority_service: PriorityService | None = None,
        category_service: CategoryService | None = None,
        sentiment_service: SentimentService | None = None,
        intent_service: IntentService | None = None,
    ):
        # Stored, not resolved eagerly -- resolution happens per-call inside
        # route() so a service unavailable at RoutingService construction
        # time (e.g. artifact not yet trained) doesn't prevent RoutingService
        # itself from existing; it's caught per-request instead, same as any
        # other transient upstream failure.
        self._spam_service = spam_service
        self._priority_service = priority_service
        self._category_service = category_service
        self._sentiment_service = sentiment_service
        self._intent_service = intent_service

    def route(
        self,
        subject: str,
        body: str,
        sender_email: str = "",
        *,
        precomputed_spam: dict | None = _NOT_PROVIDED,
        precomputed_category: dict | None = _NOT_PROVIDED,
        precomputed_intent: dict | None = _NOT_PROVIDED,
        precomputed_sentiment: dict | None = _NOT_PROVIDED,
        precomputed_priority: dict | None = _NOT_PROVIDED,
    ) -> dict:
        subject = subject or ""
        body = body or ""
        unavailable: list[str] = []

        spam_result = self._use_or_fetch(
            "spam", precomputed_spam, lambda: self._resolve_spam().classify(subject, body), unavailable
        )
        is_spam = spam_result["is_spam"] if spam_result else None

        category_result = intent_result = sentiment_result = priority_result = None

        # Skip the remaining four calls once spam is confirmed --
        # R-SPAM-GATE pre-empts department routing entirely, so composing
        # further evidence for a quarantined email is wasted work, not
        # extra caution.
        if not is_spam:
            category_result = self._use_or_fetch(
                "category",
                precomputed_category,
                lambda: self._resolve_category().classify(subject, body, sender_email=sender_email),
                unavailable,
            )
            intent_result = self._use_or_fetch(
                "intent", precomputed_intent, lambda: self._resolve_intent().analyze(subject, body), unavailable
            )
            sentiment_result = self._use_or_fetch(
                "sentiment",
                precomputed_sentiment,
                lambda: self._resolve_sentiment().analyze(subject, body),
                unavailable,
            )
            priority_result = self._use_or_fetch(
                "priority",
                precomputed_priority,
                lambda: self._resolve_priority().classify(subject, body, sender_email=sender_email),
                unavailable,
            )

        category, category_confidence, category_second, category_second_confidence = (
            self._top_two_categories(category_result)
        )

        # Failure-isolated the same way as the five upstream services (Phase 8
        # engineering review Fix #4) -- these are RoutingService's own pure-
        # logic calls, not upstream services, but a bug in either must
        # degrade the same safe way (recorded in `unavailable`, never a
        # crashed request) rather than being held to a different standard
        # just because they're "local" code.
        keyword_result = self._safe_call(
            "keywords", lambda: top_department_by_keywords(f"{subject} {body}"), unavailable
        )
        keyword_top, keyword_votes = keyword_result if keyword_result is not None else (None, {})

        sender_domain_type = self._safe_call(
            "sender_domain", lambda: classify_sender_domain(sender_email), unavailable
        )
        if sender_domain_type is None:
            sender_domain_type = "unknown"

        signals = RoutingSignals(
            is_spam=is_spam,
            # spam_score, NOT confidence -- confidence is max(probabilities),
            # i.e. confidence in the model's ARGMAX label. Since is_spam is
            # decided by spam_score >= threshold (0.06, far below 0.5), the
            # argmax label is routinely still "ham" even when is_spam=True,
            # so `confidence` would report confidence in NOT being spam.
            # spam_score is the actual spam-class probability that drove the
            # quarantine decision -- see docs/model_cards/spam_detection.md
            # "Threshold Calibration" and the Phase 8 engineering review's
            # Critical Finding #1.
            spam_confidence=spam_result["spam_score"] if spam_result else None,
            category=category,
            category_confidence=category_confidence,
            category_second=category_second,
            category_second_confidence=category_second_confidence,
            intents=tuple(i["intent"] for i in intent_result["intents"]) if intent_result else (),
            priority=priority_result["priority"] if priority_result else None,
            sentiment=sentiment_result["sentiment"] if sentiment_result else None,
            keyword_top=keyword_top,
            keyword_votes=keyword_votes,
            sender_domain_type=sender_domain_type,
            unavailable_signals=tuple(unavailable),
        )

        decision = resolve_routing(signals)

        supporting_signals: dict[str, Any] = {
            "spam": self._signal_view(
                # "confidence" (out) sourced from spam_score (in), not the
                # predictor's raw `confidence` field -- same reasoning as the
                # RoutingSignals.spam_confidence fix above; this is the
                # persisted/returned value a reader sees next to `is_spam`.
                spam_result, {"is_spam": "is_spam", "confidence": "spam_score"}, "spam"
            ),
            "category": (
                {
                    "top": category,
                    "confidence": category_confidence,
                    "reliability": SIGNAL_RELIABILITY["category"],
                }
                if category_result
                else None
            ),
            "intent": (
                {
                    "labels": [i["intent"] for i in intent_result["intents"]],
                    "reliability": SIGNAL_RELIABILITY["intent"],
                }
                if intent_result
                else None
            ),
            "sentiment": self._signal_view(sentiment_result, {"label": "sentiment"}, "sentiment"),
            "priority": self._signal_view(priority_result, {"label": "priority"}, "priority"),
            "keywords": (
                {"votes": keyword_votes, "reliability": SIGNAL_RELIABILITY["keywords"]}
                if keyword_votes
                else None
            ),
            "sender_domain": {
                "type": sender_domain_type,
                "reliability": SIGNAL_RELIABILITY["sender_domain"],
            },
        }

        model_versions = {
            "spam": spam_result["model_version"] if spam_result else None,
            "category": category_result["model_version"] if category_result else None,
            "intent": intent_result["model_version"] if intent_result else None,
            "sentiment": sentiment_result["model_version"] if sentiment_result else None,
            "priority": priority_result["model_version"] if priority_result else None,
        }

        processing_ms = sum(
            r["processing_ms"]
            for r in (spam_result, category_result, intent_result, sentiment_result, priority_result)
            if r
        )

        return {
            "department": decision.department,
            "action": decision.action,
            "confidence": decision.confidence,
            "requires_human_review": decision.requires_human_review,
            "reason": decision.reason,
            "matched_rules": list(decision.matched_rules),
            "supporting_signals": supporting_signals,
            "model_versions": model_versions,
            "routing_rules_version": ROUTING_RULES_VERSION,
            "keyword_matcher_version": KEYWORD_MATCHER_VERSION,
            "upstream_failures": unavailable,
            "processing_ms": round(processing_ms, 2),
        }

    # --- per-signal resolution -------------------------------------------

    def _resolve_spam(self) -> SpamService:
        return self._spam_service or get_spam_service()

    def _resolve_category(self) -> CategoryService:
        return self._category_service or get_category_service()

    def _resolve_intent(self) -> IntentService:
        return self._intent_service or get_intent_service()

    def _resolve_sentiment(self) -> SentimentService:
        return self._sentiment_service or get_sentiment_service()

    def _resolve_priority(self) -> PriorityService:
        return self._priority_service or get_priority_service()

    @classmethod
    def _use_or_fetch(
        cls, name: str, precomputed: Any, fetch_fn: Callable[[], Any], unavailable: list[str]
    ) -> Any | None:
        """precomputed is _NOT_PROVIDED -> caller didn't supply this signal,
        fetch it the normal way (_safe_call). precomputed is an explicit
        None -> the Orchestrator already tried and the agent failed/wasn't
        run; record it as unavailable the same way a raised exception
        would, without calling fetch_fn again. Anything else -> use it
        as-is, already computed."""
        if precomputed is _NOT_PROVIDED:
            return cls._safe_call(name, fetch_fn, unavailable)
        if precomputed is None:
            unavailable.append(name)
        return precomputed

    @staticmethod
    def _safe_call(name: str, fn: Callable[[], Any], unavailable: list[str]) -> Any | None:
        """Generic failure-isolation wrapper -- used for the five upstream
        service calls (which return dicts) and, since the Phase 8 engineering
        review's Fix #4, also for the keyword-matcher and sender-domain
        calls (which return a tuple / a str respectively). `None` is only
        ever returned on exception; a genuinely successful call that itself
        returns `None`-like data (e.g. `top_department_by_keywords`'s
        `(None, {})` "no evidence" result) is a distinct, non-`None` tuple
        and is never confused with a failure by callers."""
        try:
            return fn()
        except Exception:
            logger.warning(f"routing_{name}_signal_unavailable", exc_info=True)
            unavailable.append(name)
            return None

    @staticmethod
    def _signal_view(result: dict | None, field_map: dict[str, str], reliability_key: str) -> dict | None:
        if not result:
            return None
        view = {out_key: result[in_key] for out_key, in_key in field_map.items()}
        view["reliability"] = SIGNAL_RELIABILITY[reliability_key]
        return view

    @staticmethod
    def _top_two_categories(
        category_result: dict | None,
    ) -> tuple[str | None, float | None, str | None, float | None]:
        if not category_result:
            return None, None, None, None
        scores = sorted(category_result["all_scores"].items(), key=lambda kv: kv[1], reverse=True)
        if not scores:
            return None, None, None, None
        top_label, top_conf = scores[0]
        second_label, second_conf = scores[1] if len(scores) > 1 else (None, None)
        return top_label, top_conf, second_label, second_conf


@lru_cache
def get_routing_service() -> RoutingService:
    return RoutingService()
