"""
Organization membership: the only two ways an account can come to belong
to an organization.

  1. create_organization_with_admin() -- public signup. Creates a NEW
     organization with a server-generated ID and its creator as admin, in
     one transaction. There is no input that selects an existing
     organization, so signup can never land inside someone else's tenant.

  2. accept_invitation() -- joins the organization an admin invited this
     email address to, with the role the admin chose. The invitation is
     consumed by a single conditional UPDATE (still unaccepted, unrevoked,
     unexpired, same email) in the same transaction that creates the user:
       - two concurrent acceptances race on that UPDATE; the database
         applies it to the row once, so exactly one sees rowcount == 1;
       - if creating the user then fails (e.g. the email is already
         registered), the transaction rolls back and the invitation stays
         usable rather than being burnt.

Transaction discipline (both write paths): every statement that can hit a
constraint -- the explicit flush(), later execute()s (which autoflush) and
commit() -- runs inside ONE try block, and ANY failure rolls the whole
transaction back before re-raising. Only a violation of the users-email
uniqueness constraints is translated to EmailAlreadyRegistered (-> 409);
every other database error propagates unchanged (-> 500), so a real outage
is never disguised as "email already registered".

Invitation tokens are 256-bit random values returned once to the issuing
admin; only their SHA-256 hash is stored.
"""

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization, OrganizationInvitation, new_organization_id
from app.models.user import (
    MEMBERSHIP_INVITATION,
    MEMBERSHIP_ORGANIZATION_CREATOR,
    ROLE_ADMIN,
    USER_ROLES,
    User,
)

logger = logging.getLogger("app.membership")

DEFAULT_INVITATION_TTL_HOURS = 72
MAX_INVITATION_TTL_HOURS = 24 * 30


class EmailAlreadyRegistered(Exception):
    pass


# The two database constraints that make an email address unique: the
# original case-sensitive unique index, and the case-insensitive unique
# index on lower(email) (migration c5b1e8f2a4d6).
EMAIL_UNIQUE_CONSTRAINTS = ("uq_users_email_lower", "ix_users_email")


def is_duplicate_email_error(exc: IntegrityError) -> bool:
    """True only when `exc` is a violation of one of EMAIL_UNIQUE_CONSTRAINTS.

    PostgreSQL (asyncpg) exposes the violated constraint's name on the
    driver exception; SQLite only puts it in the message text
    ("UNIQUE constraint failed: users.email" / "... index 'uq_users_email_lower'")."""
    orig = exc.orig
    for candidate in (orig, getattr(orig, "__cause__", None)):
        constraint = getattr(candidate, "constraint_name", None)
        if constraint:
            return constraint in EMAIL_UNIQUE_CONSTRAINTS
    message = str(orig)
    return "users.email" in message or any(name in message for name in EMAIL_UNIQUE_CONSTRAINTS)


class InvalidInvitation(Exception):
    """Unknown, expired, revoked, already used, or issued to a different
    email. Deliberately one exception with one public message: telling a
    token holder WHICH check failed would, for example, confirm the email
    address an invitation was meant for."""


@dataclass(frozen=True)
class IssuedInvitation:
    invitation: OrganizationInvitation
    token: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_invitation_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _email_taken(session: AsyncSession, email: str) -> bool:
    # Case-insensitive: legacy rows may not be lower-cased.
    result = await session.execute(select(User.id).where(func.lower(User.email) == email))
    return result.first() is not None


async def create_organization_with_admin(
    session: AsyncSession, organization_name: str, email: str, hashed_password: str
) -> tuple[Organization, User]:
    email = normalize_email(email)
    if await _email_taken(session, email):
        raise EmailAlreadyRegistered()

    organization = Organization(id=new_organization_id(), name=organization_name.strip())
    user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hashed_password,
        organization_id=organization.id,
        role=ROLE_ADMIN,
        membership_source=MEMBERSHIP_ORGANIZATION_CREATOR,
    )
    organization.created_by_user_id = user.id
    try:
        session.add_all([organization, user])
        await session.commit()
    except IntegrityError as exc:
        # Organization and user are one transaction: a failed user insert
        # (e.g. lost a race on email uniqueness) leaves no orphan
        # organization behind.
        await session.rollback()
        if is_duplicate_email_error(exc):
            raise EmailAlreadyRegistered() from exc
        raise
    except BaseException:
        await session.rollback()
        raise
    await session.refresh(user)
    logger.info("organization_created", extra={"organization_id": organization.id, "user_id": str(user.id)})
    return organization, user


async def issue_invitation(
    session: AsyncSession,
    inviter: User,
    email: str,
    role: str,
    ttl_hours: int = DEFAULT_INVITATION_TTL_HOURS,
) -> IssuedInvitation:
    """`inviter` must already be verified as an admin by the caller
    (require_admin). The organization is always the inviter's own -- there
    is no parameter that could point an invitation at another tenant."""
    if role not in USER_ROLES:
        raise ValueError(f"role must be one of {USER_ROLES}")
    email = normalize_email(email)
    if await _email_taken(session, email):
        raise EmailAlreadyRegistered()

    now = datetime.now(UTC)
    # Re-inviting the same address replaces any still-open invitation, so
    # only the newest link works.
    await session.execute(
        update(OrganizationInvitation)
        .where(
            OrganizationInvitation.organization_id == inviter.organization_id,
            OrganizationInvitation.email == email,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )

    token = secrets.token_urlsafe(32)
    invitation = OrganizationInvitation(
        organization_id=inviter.organization_id,
        email=email,
        role=role,
        token_hash=hash_invitation_token(token),
        created_by_user_id=inviter.id,
        expires_at=now + timedelta(hours=max(1, min(ttl_hours, MAX_INVITATION_TTL_HOURS))),
    )
    session.add(invitation)
    await session.commit()
    await session.refresh(invitation)
    logger.info(
        "organization_invitation_issued",
        extra={"organization_id": inviter.organization_id, "invitation_id": str(invitation.id), "role": role},
    )
    return IssuedInvitation(invitation=invitation, token=token)


async def accept_invitation(session: AsyncSession, token: str, email: str, hashed_password: str) -> User:
    email = normalize_email(email)
    now = datetime.now(UTC)
    token_hash = hash_invitation_token(token)

    try:
        claimed = await session.execute(
            update(OrganizationInvitation)
            .where(
                OrganizationInvitation.token_hash == token_hash,
                OrganizationInvitation.email == email,
                OrganizationInvitation.accepted_at.is_(None),
                OrganizationInvitation.revoked_at.is_(None),
                OrganizationInvitation.expires_at > now,
            )
            .values(accepted_at=now)
            .returning(OrganizationInvitation.id, OrganizationInvitation.organization_id, OrganizationInvitation.role)
        )
        row = claimed.first()
        if row is None:
            raise InvalidInvitation()
        invitation_id, organization_id, role = row

        user = User(
            id=uuid.uuid4(),
            email=email,
            hashed_password=hashed_password,
            organization_id=organization_id,
            role=role,
            membership_source=MEMBERSHIP_INVITATION,
        )
        session.add(user)
        # Explicit flush: the user INSERT -- where an email collision
        # surfaces -- happens here, inside the handler, instead of as a
        # side effect (autoflush) of the next statement.
        await session.flush()
        await session.execute(
            update(OrganizationInvitation)
            .where(OrganizationInvitation.id == invitation_id)
            .values(accepted_by_user_id=user.id)
        )
        await session.commit()
    except InvalidInvitation:
        await session.rollback()
        logger.info("organization_invitation_rejected")
        raise
    except IntegrityError as exc:
        # Rolls back the claim too: the invitation stays usable rather
        # than being consumed by a signup that didn't happen.
        await session.rollback()
        if is_duplicate_email_error(exc):
            raise EmailAlreadyRegistered() from exc
        raise
    except BaseException:
        await session.rollback()
        raise
    await session.refresh(user)
    logger.info(
        "organization_invitation_accepted",
        extra={"organization_id": organization_id, "invitation_id": str(invitation_id), "user_id": str(user.id)},
    )
    return user


async def list_invitations(session: AsyncSession, organization_id: str) -> list[OrganizationInvitation]:
    result = await session.execute(
        select(OrganizationInvitation)
        .where(OrganizationInvitation.organization_id == organization_id)
        .order_by(OrganizationInvitation.created_at.desc())
    )
    return list(result.scalars())


async def revoke_invitation(session: AsyncSession, organization_id: str, invitation_id: uuid.UUID) -> bool:
    """Scoped to the caller's organization: another tenant's invitation id
    behaves exactly like a nonexistent one."""
    result = await session.execute(
        update(OrganizationInvitation)
        .where(
            OrganizationInvitation.id == invitation_id,
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()
    return (result.rowcount or 0) == 1


def invitation_status(invitation: OrganizationInvitation, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:  # SQLite round-trips naive datetimes
        expires_at = expires_at.replace(tzinfo=UTC)
    if invitation.accepted_at is not None:
        return "accepted"
    if invitation.revoked_at is not None:
        return "revoked"
    if expires_at <= now:
        return "expired"
    return "pending"
