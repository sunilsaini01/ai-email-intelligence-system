"""create summary_logs table

Hand-written, same reason as the three prior migrations: no live Postgres
instance reachable to autogenerate against in this environment. Columns
match app/models/summary_log.py exactly. NOTE this table has no
`subject`/`body` columns, unlike spam/priority/category_prediction_logs —
see that model's docstring for why (Step 16: don't duplicate sensitive
source content unnecessarily).

Revision ID: f4a71c9d2e83
Revises: 83169e56d48c
Create Date: 2026-08-08 22:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f4a71c9d2e83'
down_revision: Union[str, Sequence[str], None] = '83169e56d48c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "summary_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("summary_type", sa.String(length=20), nullable=False),
        sa.Column(
            "skipped_short_input", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("input_word_count", sa.Integer(), nullable=False),
        sa.Column("entity_preservation_rate", sa.Float(), nullable=True),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("processing_ms", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_summary_logs_created_at", "summary_logs", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_summary_logs_created_at", table_name="summary_logs")
    op.drop_table("summary_logs")
