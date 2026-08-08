"""create category_prediction_logs table

Hand-written, same reason as aaf9453abf37 (spam) and 57e9d6e5012d (priority):
no live Postgres instance reachable to autogenerate against in this
environment. Columns match app/models/category_prediction_log.py exactly.
Uses generic sa.JSON() (not postgresql.JSONB) for predicted_categories/
confidences so the same schema works against SQLite in tests, same
reasoning documented in that model's docstring.

Revision ID: 83169e56d48c
Revises: 57e9d6e5012d
Create Date: 2026-08-08 13:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '83169e56d48c'
down_revision: Union[str, Sequence[str], None] = '57e9d6e5012d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "category_prediction_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("predicted_categories", sa.JSON(), nullable=False),
        sa.Column("confidences", sa.JSON(), nullable=False),
        sa.Column(
            "synthetic_model",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("processing_ms", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_category_prediction_logs_created_at",
        "category_prediction_logs",
        ["created_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_category_prediction_logs_created_at", table_name="category_prediction_logs")
    op.drop_table("category_prediction_logs")
