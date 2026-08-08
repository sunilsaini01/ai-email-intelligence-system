"""create intent_prediction_logs table

Hand-written, same reason as the five prior migrations: no live Postgres
instance reachable to autogenerate against in this environment. Columns
match app/models/intent_prediction_log.py exactly. Uses native Postgres
UUID + JSONB is NOT used (generic JSON, matching the SQLite-testable model
-- see that model's docstring), same convention as category_prediction_logs.

Revision ID: c9f2e841a7b3
Revises: a3c7f19b2d4e
Create Date: 2026-08-09 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c9f2e841a7b3'
down_revision: Union[str, Sequence[str], None] = 'a3c7f19b2d4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "intent_prediction_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("predicted_intents", sa.JSON(), nullable=False),
        sa.Column("confidences", sa.JSON(), nullable=False),
        sa.Column("entities", sa.JSON(), nullable=False),
        sa.Column(
            "synthetic_model", sa.Boolean(), nullable=False, server_default=sa.text("true")
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
    op.create_index("ix_intent_prediction_logs_created_at", "intent_prediction_logs", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_intent_prediction_logs_created_at", table_name="intent_prediction_logs")
    op.drop_table("intent_prediction_logs")
