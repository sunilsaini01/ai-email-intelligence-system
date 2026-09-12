"""create routing_overrides table

Hand-written, same reason as every prior migration in this repo. Phase 21
-- admin-configurable routing overrides. See
app/models/routing_override.py's module docstring for why this table
exists and what it deliberately does NOT replace.

Revision ID: e8b2f4a91c73
Revises: d3a9c58e4f17
Create Date: 2026-09-12 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e8b2f4a91c73'
down_revision: Union[str, Sequence[str], None] = 'd3a9c58e4f17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "routing_overrides",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", sa.String(length=100), nullable=False, server_default="default"),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("priority_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("conditions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("override_department", sa.String(length=100), nullable=True),
        sa.Column("override_action", sa.String(length=30), nullable=True),
        sa.Column("override_requires_human_review", sa.Boolean(), nullable=True),
        sa.Column(
            "created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index(
        "ix_routing_overrides_org_priority", "routing_overrides", ["organization_id", "priority_order"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_routing_overrides_org_priority", table_name="routing_overrides")
    op.drop_table("routing_overrides")
