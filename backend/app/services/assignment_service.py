"""
Agent assignment inside a routed department (FR-42: "Round-robin and
skills-based routing between agents shall be supported").

Routing (app/routing/rules.py) decides the DEPARTMENT; this picks the
AGENT. Eligible agents are active users of the organization whose
`department` matches, in role agent or manager (admins configure the
system; they are not in the work queue).

  - round_robin: the eligible agent assigned least recently (never-assigned
    first) gets the email.
  - skills: agents whose `skills` overlap the email's required skills
    (its intents and category, case-insensitive) are preferred, most
    overlap first; ties -- and the no-overlap case -- fall back to
    round-robin order, so a skills mismatch never leaves an email
    unassigned while an agent is available.

`last_assigned_at` is the round-robin cursor; it is bumped on every
assignment. Two concurrent assignments can occasionally pick the same
agent -- an accepted imbalance of one email, not worth a row lock.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import ROLE_AGENT, ROLE_MANAGER, User
from app.services.organization_settings_service import ASSIGNMENT_NONE, ASSIGNMENT_SKILLS

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _round_robin_key(user: User) -> tuple:
    last = user.last_assigned_at or _EPOCH
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return (last, str(user.id))


def choose_agent(candidates: list[User], strategy: str, required_skills: set[str]) -> User | None:
    """Pure selection step, separated from the query for testability."""
    if not candidates or strategy == ASSIGNMENT_NONE:
        return None

    if strategy == ASSIGNMENT_SKILLS and required_skills:
        wanted = {s.lower() for s in required_skills}

        def overlap(user: User) -> int:
            return len(wanted & {str(s).lower() for s in (user.skills or [])})

        best = max(overlap(u) for u in candidates)
        if best > 0:
            candidates = [u for u in candidates if overlap(u) == best]

    return min(candidates, key=_round_robin_key)


async def assign_agent(
    session: AsyncSession,
    organization_id: str,
    department: str | None,
    strategy: str,
    required_skills: set[str] | None = None,
) -> User | None:
    if department is None or strategy == ASSIGNMENT_NONE:
        return None

    candidates = list(
        (
            await session.execute(
                select(User).where(
                    User.organization_id == organization_id,
                    User.department == department,
                    User.is_active.is_(True),
                    User.role.in_((ROLE_AGENT, ROLE_MANAGER)),
                )
            )
        ).scalars()
    )
    agent = choose_agent(candidates, strategy, required_skills or set())
    if agent is not None:
        agent.last_assigned_at = datetime.now(UTC)
        await session.commit()
    return agent
