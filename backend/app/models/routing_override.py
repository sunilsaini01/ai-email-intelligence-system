"""
Admin-configurable routing overrides (Phase 21, FR-39).

Layered ON TOP of the existing heuristic routing engine
(app/routing/rules.py), never replacing it: that engine is a carefully
tuned pipeline with its own documented, error-analysis-backed rationale
for every threshold (see that module's own docstring) -- rewriting it as
a generic condition/action table per the PRD's literal §12.1
`routing_rules` schema would risk silently discarding real, validated
business logic (high-impact-department review, escalation corroboration,
etc.) that a simple CRUD table has no way to express. An override is
instead a simple, ADDITIVE final pass: "if these conditions match, force
this department/action/review flag" -- exactly FR-39's literal wording
("configurable rule-based OVERRIDES"), evaluated after the base engine
already produced a decision, never instead of it. See
app/routing/overrides.py for the pure, DB-free evaluation logic this
table feeds, and its own docstring for supported condition fields/
operators.

Why this was blocked until now: app/routing/rules.py's own module
docstring documented this exact feature as "blocked on auth landing
first" -- an unauthenticated CRUD API for live routing logic was
correctly judged too dangerous before real authentication (Phase 17) and
role-based authorization (Phase 19) existed. Both now exist; creating,
editing, or deleting an override requires an org admin (see
app/api/v1/endpoints/routing.py) -- listing stays open to any signed-in
member, same read-open/write-admin split Phase 19 already established
for mailbox connections.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID


class RoutingOverride(Base):
    __tablename__ = "routing_overrides"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[str] = mapped_column(String(100), default=DEFAULT_ORGANIZATION_ID)

    name: Mapped[str] = mapped_column(String(200))
    # Lower evaluated first -- see app/routing/overrides.py's own
    # docstring: the first override whose conditions all match wins, later
    # ones are never consulted for that decision.
    priority_order: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # [{"field": "sender_email_domain", "operator": "eq", "value": "vip-client.com"}, ...]
    # -- ANDed together within one override (see app/routing/overrides.py
    # for supported fields/operators). AND-only, no OR: a condition set
    # that needs OR is just two separate override rules at the same
    # priority_order instead -- not a limitation this table's shape
    # actually needs to express.
    conditions: Mapped[list] = mapped_column(JSON, default=list)

    # Each nullable independently -- an override only names the field(s)
    # it actually wants to force; a null field means "leave the base
    # engine's own decision for this field alone." See
    # app/routing/overrides.py for why override_requires_human_review can
    # never actually turn OFF review for a high-impact department (HR/
    # Legal/Billing) even if set to False here -- that safety net is
    # re-applied after every override, not something an override can
    # accidentally (or deliberately) disable.
    override_department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    override_action: Mapped[str | None] = mapped_column(String(30), nullable=True)
    override_requires_human_review: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
