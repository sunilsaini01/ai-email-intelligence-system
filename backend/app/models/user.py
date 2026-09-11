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

Why `role` is a plain string, not a separate roles/permissions table: two
values (`admin`, `member`) are all this phase needs -- FR-level RBAC
(per-endpoint permission grants) is not something any current endpoint
distinguishes on, and building that scaffolding before a second
permission actually exists would be exactly the kind of speculative
generality this codebase's own conventions warn against.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
USER_ROLES = (ROLE_ADMIN, ROLE_MEMBER)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))

    organization_id: Mapped[str] = mapped_column(String(100), default=DEFAULT_ORGANIZATION_ID)
    role: Mapped[str] = mapped_column(String(20), default=ROLE_MEMBER)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
