"""add duration_ms to workflow_executions

Hand-written, same reason as every prior migration in this repo. Phase
16B / FR-72 -- stores end-to-end pipeline latency (pipeline_start =
started_at, pipeline_end = completed_at) explicitly rather than deriving
it at read time on every query, mirroring agent_executions.duration_ms
(see e2f5b8c31a94). Nullable: only ever set once a workflow reaches a
terminal status, same as completed_at itself.

Revision ID: a1b4d7e93c62
Revises: e2f5b8c31a94
Create Date: 2026-08-22 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b4d7e93c62'
down_revision: Union[str, Sequence[str], None] = 'e2f5b8c31a94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("workflow_executions", sa.Column("duration_ms", sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("workflow_executions", "duration_ms")
