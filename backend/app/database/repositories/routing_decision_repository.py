"""
Repository for routing decision audit logs. Same rationale as
intent_prediction_repository.py.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.routing_decision_log import RoutingDecisionLog


class RoutingDecisionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_decision(
        self,
        subject: str,
        body: str,
        department: str | None,
        action: str,
        confidence: float,
        requires_human_review: bool,
        reason: str,
        matched_rules: list[str],
        supporting_signals: dict,
        model_versions: dict,
        routing_rules_version: str,
        keyword_matcher_version: str,
        upstream_failures: list[str],
        processing_ms: float,
    ) -> RoutingDecisionLog:
        record = RoutingDecisionLog(
            subject=subject,
            body=body,
            department=department,
            action=action,
            confidence=confidence,
            requires_human_review=requires_human_review,
            reason=reason,
            matched_rules=matched_rules,
            supporting_signals=supporting_signals,
            model_versions=model_versions,
            routing_rules_version=routing_rules_version,
            keyword_matcher_version=keyword_matcher_version,
            upstream_failures=upstream_failures,
            processing_ms=processing_ms,
        )

        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)

        return record
