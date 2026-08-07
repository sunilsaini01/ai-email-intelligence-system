"""create priority_prediction_logs table

Hand-written, same reason as aaf9453abf37 (spam): no live Postgres instance
reachable to autogenerate against in this environment. Columns match
app/models/priority_prediction_log.py exactly.

Revision ID: 57e9d6e5012d
Revises: aaf9453abf37
Create Date: 2026-08-08 01:25:09.521522

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '57e9d6e5012d'
down_revision: Union[str, Sequence[str], None] = 'aaf9453abf37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "priority_prediction_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("predicted_priority", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
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
        "ix_priority_prediction_logs_created_at",
        "priority_prediction_logs",
        ["created_at"],
    )
    op.create_index(
        "ix_priority_prediction_logs_predicted_priority",
        "priority_prediction_logs",
        ["predicted_priority"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_priority_prediction_logs_predicted_priority", table_name="priority_prediction_logs")
    op.drop_index("ix_priority_prediction_logs_created_at", table_name="priority_prediction_logs")
    op.drop_table("priority_prediction_logs")
