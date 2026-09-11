"""create mailbox_connections and mailbox_ingested_messages tables

Hand-written, same reason as every prior migration in this repo. Phase 18
-- live mailbox ingestion. Two tables in one migration, same bundling
precedent as e2f5b8c31a94 (phase12_multi_agent_schema) and d1e9a4c73f58
(phase11_dashboard_schema): mailbox_ingested_messages has a hard FK
dependency on mailbox_connections and only exists to support it, not
worth a second migration purely for that reason. See
app/models/mailbox_connection.py and app/models/mailbox_ingested_message.py's
own module docstrings for why each table exists.

Revision ID: d3a9c58e4f17
Revises: b7f3c8e21a95
Create Date: 2026-09-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd3a9c58e4f17'
down_revision: Union[str, Sequence[str], None] = 'b7f3c8e21a95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "mailbox_connections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", sa.String(length=100), nullable=False, server_default="default"),
        sa.Column("connected_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("email_address", sa.String(length=320), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("sync_cursor", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint(
            "organization_id", "provider", "email_address", name="uq_mailbox_org_provider_address"
        ),
    )
    op.create_index("ix_mailbox_connections_organization_id", "mailbox_connections", ["organization_id"])

    op.create_table(
        "mailbox_ingested_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mailbox_connections.id"),
            nullable=False,
        ),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_executions.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint(
            "connection_id", "provider_message_id", name="uq_mailbox_ingested_connection_message"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("mailbox_ingested_messages")
    op.drop_index("ix_mailbox_connections_organization_id", table_name="mailbox_connections")
    op.drop_table("mailbox_connections")
