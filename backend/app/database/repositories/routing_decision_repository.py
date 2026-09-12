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
        organization_id: str | None = None,
    ) -> RoutingDecisionLog:
        # organization_id added Phase 21: every decision was previously
        # logged under the model's own DEFAULT_ORGANIZATION_ID default
        # regardless of which organization actually called /routing/predict
        # -- the same caller-supplied-vs-token-derived gap already fixed
        # for reply.py this same phase. Optional here (not required)
        # so this repository's own unit tests don't all need updating for
        # a column they don't otherwise exercise; the endpoint always
        # passes the real one.
        kwargs = {"organization_id": organization_id} if organization_id is not None else {}
        record = RoutingDecisionLog(
            **kwargs,
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
