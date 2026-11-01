"""
User accounts (Phase 17, real authentication).

Closes the standing gap every prior phase disclosed and deferred since
Phase 1 (docs/architecture/architecture.md "Known Gaps") -- there was no
real identity anywhere in this codebase. `organization_id` and
`reviewer_id` were caller-supplied, unverified strings everywhere they
appeared (docs/design_decisions/dashboard_security.md,
app/retrieval/tenant.py's own module docstring, app/models/feedback_event.py's
`reviewer_id` comment). This table is the identity those fields were
always meant to eventually derive from -- see `app/core/security.py` for
password hashing/JWT, `app/api/v1/endpoints/auth.py` for
register/login, and `app/core/auth_dependency.py` for the
`get_current_user` dependency that now gates the API.

Why `organization_id` lives on the user, not passed separately: a user
belongs to exactly one organization in this project's current
single-tenant-per-user model (no cross-org membership) -- the same
DEFAULT_ORGANIZATION_ID single-tenant reality app/retrieval/tenant.py
already discloses, now attached to a real account instead of being a
hardcoded constant every caller trusted blindly.

Why `role` is a plain string, not a separate roles/permissions table:
the PRD's RBAC (SS6.4) names exactly three roles -- agent / manager /
admin -- ordered by privilege, and every gate in this codebase is "at
least role X" (see app/core/auth_dependency.py's require_role). Phase 19
shipped `admin`/`member`; `member` was renamed to `agent` and `manager`
added in place (see the phase22 migration), since `member` always meant
"a non-admin agent".

`department`/`skills`/`last_assigned_at` (FR-42) drive agent assignment
inside a routed department -- see app/services/assignment_service.py.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID

# How a user came to belong to their organization (membership security
# fix). Accounts that existed before invitations were enforced are
# `legacy_unverified` until an admin confirms them -- anyone could have
# self-registered into any organization then (see
# docs/security/organization_membership_remediation.md).
MEMBERSHIP_ORGANIZATION_CREATOR = "organization_creator"
MEMBERSHIP_INVITATION = "invitation"
MEMBERSHIP_ADMIN_VERIFIED = "admin_verified"
MEMBERSHIP_LEGACY_UNVERIFIED = "legacy_unverified"

ROLE_AGENT = "agent"
ROLE_MANAGER = "manager"
ROLE_ADMIN = "admin"
# Ordered least -> most privileged; require_role() compares positions.
USER_ROLES = (ROLE_AGENT, ROLE_MANAGER, ROLE_ADMIN)


class User(Base):
    __tablename__ = "users"
    # Case-insensitive email uniqueness, enforced by the database for every
    # write (migration c5b1e8f2a4d6, which refuses to run while legacy
    # case-variant duplicates exist). The original case-sensitive unique
    # index on `email` stays as well.
    __table_args__ = (Index("uq_users_email_lower", text("lower(email)"), unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))

    organization_id: Mapped[str] = mapped_column(String(100), default=DEFAULT_ORGANIZATION_ID)
    role: Mapped[str] = mapped_column(String(20), default=ROLE_AGENT)

    # FR-42 -- see module docstring.
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    last_assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    membership_source: Mapped[str] = mapped_column(String(30), default=MEMBERSHIP_LEGACY_UNVERIFIED)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
