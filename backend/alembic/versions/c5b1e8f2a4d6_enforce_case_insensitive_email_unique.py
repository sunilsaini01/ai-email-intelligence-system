"""enforce case-insensitive email uniqueness on users

Hand-written. Adds a UNIQUE index on lower(email), so the database
itself rejects a new account whose email differs from an existing one
only by letter case -- including when two signups race.

PRECONDITION -- no existing case-variant duplicates. Before this
revision, `Bob@x.com` and `bob@x.com` could both exist (the original
index on `email` is case-sensitive). A unique index cannot be built over
such rows, and this migration will NOT merge, rename, delete or deactivate
anyone to make it fit. Instead it stops with a report of every colliding
group; Alembic runs the whole upgrade in one transaction (alembic/env.py),
so nothing from this run is left half-applied. The operator resolves the
collisions (docs/security/organization_membership_remediation.md
"Email case collisions") and re-runs `alembic upgrade head`.

Deploying in two steps is supported: `alembic upgrade a7e3d91c5b20`
ships the membership fix on its own (login already fails closed on
ambiguous emails at the application level), then `alembic upgrade head`
once collisions are resolved.

Revision ID: c5b1e8f2a4d6
Revises: a7e3d91c5b20
Create Date: 2026-10-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5b1e8f2a4d6'
down_revision: Union[str, Sequence[str], None] = 'a7e3d91c5b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "uq_users_email_lower"

_COLLISIONS_SQL = """
    SELECT lower(email) AS normalized,
           count(*) AS accounts,
           string_agg(id::text || ' ' || email || ' org=' || organization_id
                      || ' role=' || role || ' active=' || is_active::text, '; ' ORDER BY created_at) AS detail
    FROM users
    GROUP BY lower(email)
    HAVING count(*) > 1
    ORDER BY lower(email)
"""


class EmailCollisionsPresent(RuntimeError):
    pass


def upgrade() -> None:
    """Upgrade schema."""
    if context.is_offline_mode():
        # --sql output: the same precondition, enforced by the server when
        # the script is applied.
        op.execute(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM users GROUP BY lower(email) HAVING count(*) > 1) THEN "
            "RAISE EXCEPTION 'users contains emails that differ only by case; resolve them before creating "
            f"{INDEX_NAME} (see docs/security/organization_membership_remediation.md)'; END IF; END $$;"
        )
    else:
        collisions = op.get_bind().execute(sa.text(_COLLISIONS_SQL)).all()
        if collisions:
            report = "\n".join(f"  {row.normalized} ({row.accounts} accounts): {row.detail}" for row in collisions)
            raise EmailCollisionsPresent(
                f"Cannot create {INDEX_NAME}: {len(collisions)} email(s) belong to more than one account "
                f"when letter case is ignored:\n{report}\n"
                "Nothing was changed. Resolve these accounts as described in "
                "docs/security/organization_membership_remediation.md (\"Email case collisions\"), "
                "then run `alembic upgrade head` again. Until then, login for these addresses fails closed."
            )
    op.create_index(INDEX_NAME, "users", [sa.text("lower(email)")], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(INDEX_NAME, table_name="users")
