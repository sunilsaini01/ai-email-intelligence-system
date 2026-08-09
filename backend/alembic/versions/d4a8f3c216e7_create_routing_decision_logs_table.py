"""create routing_decision_logs table

Hand-written, same reason as every prior migration in this repo: no live
Postgres instance reachable to autogenerate against in this environment.
Columns match app/models/routing_decision_log.py exactly. Generic JSON (not
JSONB), same portability convention as every other prediction-log table --
exercised against SQLite in tests, verified here against a real disposable
Postgres 16 container (docs/architecture_routing.md "Database").

Revision ID: d4a8f3c216e7
Revises: c9f2e841a7b3
Create Date: 2026-08-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd4a8f3c216e7'
down_revision: Union[str, Sequence[str], None] = 'c9f2e841a7b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "routing_decision_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("department", sa.String(length=100), nullable=True),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "requires_human_review", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("matched_rules", sa.JSON(), nullable=False),
        sa.Column("supporting_signals", sa.JSON(), nullable=False),
        sa.Column("model_versions", sa.JSON(), nullable=False),
        sa.Column("routing_rules_version", sa.String(length=50), nullable=False),
        sa.Column("keyword_matcher_version", sa.String(length=50), nullable=False),
        sa.Column("upstream_failures", sa.JSON(), nullable=False),
        sa.Column(
            "synthetic_model", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("processing_ms", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_routing_decision_logs_created_at", "routing_decision_logs", ["created_at"]
    )
    op.create_index(
        "ix_routing_decision_logs_department", "routing_decision_logs", ["department"]
    )
    op.create_index(
        "ix_routing_decision_logs_requires_human_review",
        "routing_decision_logs",
        ["requires_human_review"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_routing_decision_logs_requires_human_review", table_name="routing_decision_logs")
    op.drop_index("ix_routing_decision_logs_department", table_name="routing_decision_logs")
    op.drop_index("ix_routing_decision_logs_created_at", table_name="routing_decision_logs")
    op.drop_table("routing_decision_logs")
