"""
Read-only membership audit after the unrestricted-registration fix -- see
docs/security/organization_membership_remediation.md.

    cd backend && python -m scripts.audit_organization_memberships

Prints (1) accounts whose emails collide when letter case is ignored, and
(2) every organization's accounts with the signals worth a human look.
It only runs SELECTs: it never confirms, modifies, deactivates or deletes
anything.
"""

import asyncio
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

import app.models  # noqa: E402,F401
from app.database.session import AsyncSessionLocal  # noqa: E402
from app.models.user import MEMBERSHIP_LEGACY_UNVERIFIED, ROLE_ADMIN, User  # noqa: E402
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID  # noqa: E402


def _domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower()


def email_collisions(users: list[User]) -> dict[str, list[User]]:
    """Accounts whose emails are equal ignoring letter case. Login for
    these addresses fails closed, and migration c5b1e8f2a4d6 refuses to
    add the case-insensitive unique index until they are resolved."""
    groups: dict[str, list[User]] = defaultdict(list)
    for user in users:
        groups[user.email.strip().lower()].append(user)
    return {email: members for email, members in sorted(groups.items()) if len(members) > 1}


def build_report(users: list[User]) -> list[str]:
    lines: list[str] = []
    collisions = email_collisions(users)
    if collisions:
        lines.append(
            f"!! {len(collisions)} email(s) shared by several accounts when case is ignored -- "
            "login for them fails closed; resolve before `alembic upgrade head`:"
        )
        for email, members in collisions.items():
            lines.append(f"   {email}")
            for u in sorted(members, key=lambda m: m.created_at):
                lines.append(
                    f"      {u.id}  {u.email:<40} org={u.organization_id} role={u.role} "
                    f"{'active' if u.is_active else 'inactive'} created={u.created_at:%Y-%m-%d %H:%M}"
                )
    else:
        lines.append("No case-insensitive email collisions.")

    by_org: dict[str, list[User]] = defaultdict(list)
    for user in users:
        by_org[user.organization_id].append(user)

    for org_id, members in sorted(by_org.items()):
        members.sort(key=lambda u: u.created_at)
        admins = [u for u in members if u.role == ROLE_ADMIN]
        common_domain = Counter(_domain(u.email) for u in members).most_common(1)[0][0]
        unverified = sum(1 for u in members if u.membership_source == MEMBERSHIP_LEGACY_UNVERIFIED)

        flags = []
        if len(admins) > 1:
            flags.append(f"{len(admins)} admins")
        if org_id == DEFAULT_ORGANIZATION_ID:
            flags.append("default organization: signups that omitted organization_id landed here")
        lines.append(f"\n== {org_id}  ({len(members)} accounts, {unverified} unverified){'  [' + '; '.join(flags) + ']' if flags else ''}")

        for u in members:
            notes = []
            if _domain(u.email) != common_domain:
                notes.append("domain differs from organization majority")
            if u.membership_source == MEMBERSHIP_LEGACY_UNVERIFIED:
                notes.append("UNVERIFIED")
            lines.append(
                f"   {u.created_at:%Y-%m-%d %H:%M}  {u.role:<8} {'active' if u.is_active else 'inactive':<8} "
                f"{u.membership_source:<20} {u.email}{'  <- ' + ', '.join(notes) if notes else ''}"
            )
    return lines


async def main() -> None:
    async with AsyncSessionLocal() as session:
        users = list((await session.execute(select(User))).scalars())
    print("\n".join(build_report(users)) or "No users.")


if __name__ == "__main__":
    asyncio.run(main())
