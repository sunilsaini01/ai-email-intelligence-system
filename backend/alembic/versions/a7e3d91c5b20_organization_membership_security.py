"""organization membership security: organizations, invitations, membership_source

Hand-written, same reason as every prior migration in this repo. Closes
the unrestricted-registration hole: POST /auth/register used to accept a
caller-chosen organization_id and create an active account inside it.

  - `organizations`: authoritative tenant list. Backfilled from every
    organization_id that existing users already reference, so current
    tenants keep working unchanged (name = the old ID, editable later).
  - `organization_invitations`: admin-issued, email-bound, expiring,
    single-use invitations (only a token hash is stored).
  - `users.membership_source`: every EXISTING account is marked
    `legacy_unverified` -- it was created while anyone could self-register
    into any organization. Nothing is disabled or deleted; admins review
    them (docs/security/organization_membership_remediation.md).

Revision ID: a7e3d91c5b20
Revises: f9d2c4e7a815
Create Date: 2026-10-30 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7e3d91c5b20'
down_revision: Union[str, Sequence[str], None] = 'f9d2c4e7a815'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute(
        "INSERT INTO organizations (id, name) "
        "SELECT DISTINCT organization_id, organization_id FROM users "
        "WHERE organization_id IS NOT NULL AND organization_id <> ''"
    )

    op.create_table(
        "organization_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.String(length=100), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_organization_invitations_organization_id", "organization_invitations", ["organization_id"]
    )
    op.create_index("ix_organization_invitations_email", "organization_invitations", ["email"])

    op.add_column(
        "users",
        sa.Column("membership_source", sa.String(length=30), nullable=False, server_default="legacy_unverified"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "membership_source")
    op.drop_index("ix_organization_invitations_email", table_name="organization_invitations")
    op.drop_index("ix_organization_invitations_organization_id", table_name="organization_invitations")
    op.drop_table("organization_invitations")
    op.drop_table("organizations")
