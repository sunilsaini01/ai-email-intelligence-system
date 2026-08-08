"""create sentiment_prediction_logs table

Hand-written, same reason as the four prior migrations: no live Postgres
instance reachable to autogenerate against in this environment. Columns
match app/models/sentiment_prediction_log.py exactly. Uses native Postgres
UUID (not the app's GUID TypeDecorator) -- migrations only ever target real
Postgres, same convention as every prior migration in this repo.

This migration also closes a pre-existing gap surfaced during Phase 7A's
Gate D audit: app/models/__init__.py was missing CategoryPredictionLog and
SummaryLog (added in Phases 5/6 but never registered for Alembic metadata
discovery). That import-registration fix lives in __init__.py itself, not
here -- this migration only needs to exist for the new table those two
already have their own (83169e56d48c, f4a71c9d2e83).

Revision ID: a3c7f19b2d4e
Revises: f4a71c9d2e83
Create Date: 2026-08-09 01:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a3c7f19b2d4e'
down_revision: Union[str, Sequence[str], None] = 'f4a71c9d2e83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "sentiment_prediction_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("predicted_sentiment", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
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
    op.create_index("ix_sentiment_prediction_logs_created_at", "sentiment_prediction_logs", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_sentiment_prediction_logs_created_at", table_name="sentiment_prediction_logs")
    op.drop_table("sentiment_prediction_logs")
