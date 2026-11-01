"""phase22 PRD gap closure schema

Hand-written, same reason as every prior migration in this repo. One
migration for the whole PRD gap-closure pass:

  - users: `member` -> `agent` role rename (PRD SS6.4 RBAC: agent /
    manager / admin); department/skills/last_assigned_at (FR-42).
  - emails: assigned_agent_id (FR-42), model_priority + sentiment
    (FR-31/FR-17).
  - sentiment_prediction_logs: sender_email (FR-32), primary_emotion +
    emotions (FR-30).
  - retraining_triggers: execution lifecycle columns (FR-61).
  - new tables: organization_settings, notifications (FR-18),
    generated_reports (FR-56).

Revision ID: f9d2c4e7a815
Revises: e8b2f4a91c73
Create Date: 2026-10-28 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f9d2c4e7a815'
down_revision: Union[str, Sequence[str], None] = 'e8b2f4a91c73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- users -----------------------------------------------------------
    op.execute("UPDATE users SET role = 'agent' WHERE role = 'member'")
    op.alter_column("users", "role", server_default="agent")
    op.add_column("users", sa.Column("department", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("skills", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("users", sa.Column("last_assigned_at", sa.DateTime(timezone=True), nullable=True))

    # --- emails ----------------------------------------------------------
    op.add_column("emails", sa.Column("assigned_agent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("emails", sa.Column("model_priority", sa.String(length=20), nullable=True))
    op.add_column("emails", sa.Column("sentiment", sa.String(length=20), nullable=True))
    op.create_index("ix_emails_sender_email", "emails", ["organization_id", "sender_email"])

    # --- sentiment_prediction_logs --------------------------------------
    op.add_column("sentiment_prediction_logs", sa.Column("sender_email", sa.String(length=320), nullable=True))
    op.add_column("sentiment_prediction_logs", sa.Column("primary_emotion", sa.String(length=30), nullable=True))
    op.add_column("sentiment_prediction_logs", sa.Column("emotions", sa.JSON(), nullable=True))
    op.create_index(
        "ix_sentiment_prediction_logs_sender_email", "sentiment_prediction_logs", ["sender_email"]
    )

    # --- retraining_triggers --------------------------------------------
    op.add_column(
        "retraining_triggers", sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING")
    )
    op.add_column(
        "retraining_triggers",
        sa.Column("source", sa.String(length=30), nullable=False, server_default="feedback_threshold"),
    )
    op.add_column("retraining_triggers", sa.Column("requested_by_user_id", sa.String(length=100), nullable=True))
    op.add_column("retraining_triggers", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("retraining_triggers", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("retraining_triggers", sa.Column("result_message", sa.Text(), nullable=True))
    # Triggers written before this phase were never going to run --
    # mark them so the new runner doesn't suddenly execute a backlog.
    op.execute("UPDATE retraining_triggers SET status = 'SKIPPED' WHERE consumed = false")

    # --- new tables -----------------------------------------------------
    op.create_table(
        "organization_settings",
        sa.Column("organization_id", sa.String(length=100), primary_key=True),
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("updated_by_user_id", sa.String(length=100), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.String(length=100), nullable=False, server_default="default"),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="critical"),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("email_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dedup_key", sa.String(length=200), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("webhook_status", sa.String(length=20), nullable=False, server_default="not_configured"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_notifications_organization_id", "notifications", ["organization_id"])
    op.create_index("ix_notifications_dedup_key", "notifications", ["dedup_key"])

    op.create_table(
        "generated_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.String(length=100), nullable=False, server_default="default"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("report_format", sa.String(length=10), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_generated_reports_organization_id", "generated_reports", ["organization_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_generated_reports_organization_id", table_name="generated_reports")
    op.drop_table("generated_reports")
    op.drop_index("ix_notifications_dedup_key", table_name="notifications")
    op.drop_index("ix_notifications_organization_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("organization_settings")

    for column in ("result_message", "completed_at", "started_at", "requested_by_user_id", "source", "status"):
        op.drop_column("retraining_triggers", column)

    op.drop_index("ix_sentiment_prediction_logs_sender_email", table_name="sentiment_prediction_logs")
    for column in ("emotions", "primary_emotion", "sender_email"):
        op.drop_column("sentiment_prediction_logs", column)

    op.drop_index("ix_emails_sender_email", table_name="emails")
    for column in ("sentiment", "model_priority", "assigned_agent_id"):
        op.drop_column("emails", column)

    for column in ("last_assigned_at", "skills", "department"):
        op.drop_column("users", column)
    op.alter_column("users", "role", server_default="member")
    op.execute("UPDATE users SET role = 'member' WHERE role IN ('agent', 'manager')")
