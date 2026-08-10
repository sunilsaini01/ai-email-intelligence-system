"""add edit_distance to reply_drafts

Hand-written, same reason as every prior migration in this repo. Post-Phase-10
fix #2 (Human Acceptance Rate tracking, FR-52) -- adds one nullable column
to the existing reply_drafts table.

Revision ID: c8f2a7e91d36
Revises: b3e7d1f9a284
Create Date: 2026-08-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8f2a7e91d36'
down_revision: Union[str, Sequence[str], None] = 'b3e7d1f9a284'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("reply_drafts", sa.Column("edit_distance", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("reply_drafts", "edit_distance")
