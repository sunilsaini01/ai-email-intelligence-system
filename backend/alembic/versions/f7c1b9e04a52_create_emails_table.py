"""create emails table

Hand-written, same reason as every prior migration in this repo: no live
Postgres instance reachable to autogenerate against in this environment.
Columns match app/models/email_record.py exactly. First table in this
project with a UNIQUE constraint spanning two columns
(organization_id, content_hash) -- the DB-level enforcement of Module 9's
idempotent-indexing guarantee (see EmailRecord's module docstring).

Revision ID: f7c1b9e04a52
Revises: d4a8f3c216e7
Create Date: 2026-08-09 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f7c1b9e04a52'
down_revision: Union[str, Sequence[str], None] = 'd4a8f3c216e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "emails",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", sa.String(length=100), nullable=False, server_default="default"),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("message_id", sa.String(length=512), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sender_email", sa.String(length=320), nullable=False, server_default=""),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("department", sa.String(length=100), nullable=True),
        sa.Column("resolution_status", sa.String(length=20), nullable=False, server_default="OPEN"),
        sa.Column("index_status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
        sa.Column("embedding_version", sa.String(length=100), nullable=True),
        sa.Column("vector_collection", sa.String(length=100), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("organization_id", "content_hash", name="uq_emails_org_content_hash"),
    )
    op.create_index("ix_emails_category", "emails", ["category"])
    op.create_index("ix_emails_department", "emails", ["department"])
    op.create_index("ix_emails_resolution_status", "emails", ["resolution_status"])
    op.create_index("ix_emails_index_status", "emails", ["index_status"])
    op.create_index("ix_emails_is_deleted", "emails", ["is_deleted"])
    op.create_index("ix_emails_created_at", "emails", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_emails_created_at", table_name="emails")
    op.drop_index("ix_emails_is_deleted", table_name="emails")
    op.drop_index("ix_emails_index_status", table_name="emails")
    op.drop_index("ix_emails_resolution_status", table_name="emails")
    op.drop_index("ix_emails_department", table_name="emails")
    op.drop_index("ix_emails_category", table_name="emails")
    op.drop_table("emails")
