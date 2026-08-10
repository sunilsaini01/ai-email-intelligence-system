"""create reply_drafts table

Hand-written, same reason as every prior migration in this repo: no live
Postgres instance reachable to autogenerate against in this environment.
Columns match app/models/reply_draft.py exactly.

Revision ID: b3e7d1f9a284
Revises: f7c1b9e04a52
Create Date: 2026-08-10 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b3e7d1f9a284'
down_revision: Union[str, Sequence[str], None] = 'f7c1b9e04a52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "reply_drafts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", sa.String(length=100), nullable=False, server_default="default"),
        sa.Column("source_email_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_body", sa.Text(), nullable=False),
        sa.Column("retrieved_email_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("retrieved_context_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generated_text", sa.Text(), nullable=True),
        sa.Column("edited_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="GENERATED"),
        sa.Column("generation_policy", sa.String(length=30), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("llm_provider", sa.String(length=50), nullable=True),
        sa.Column("llm_model", sa.String(length=100), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
        sa.Column("retrieval_latency_ms", sa.Float(), nullable=True),
        sa.Column("llm_latency_ms", sa.Float(), nullable=True),
        sa.Column("total_latency_ms", sa.Float(), nullable=True),
        sa.Column("reviewer_id", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_reply_drafts_organization_id", "reply_drafts", ["organization_id"])
    op.create_index("ix_reply_drafts_source_email_id", "reply_drafts", ["source_email_id"])
    op.create_index("ix_reply_drafts_status", "reply_drafts", ["status"])
    op.create_index("ix_reply_drafts_created_at", "reply_drafts", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_reply_drafts_created_at", table_name="reply_drafts")
    op.drop_index("ix_reply_drafts_status", table_name="reply_drafts")
    op.drop_index("ix_reply_drafts_source_email_id", table_name="reply_drafts")
    op.drop_index("ix_reply_drafts_organization_id", table_name="reply_drafts")
    op.drop_table("reply_drafts")
