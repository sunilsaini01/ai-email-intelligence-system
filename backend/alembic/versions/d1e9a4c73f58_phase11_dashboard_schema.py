"""phase 11 dashboard schema

Hand-written, same reason as every prior migration in this repo: no live
Postgres instance reachable to autogenerate against in this environment.

Bundles everything docs/architecture_dashboard.md's data-model section
specifies as one migration (Module 11 / Phase 11):
  - organization_id added to the 7 prediction/log tables that lacked it
    (spam/priority/category/summary/sentiment/intent/routing), each with
    a (organization_id, created_at) composite index -- these tables had
    NO indexes beyond their primary key before this migration (audit
    finding, PHASE_11_AUDIT_REPORT.md).
  - emails.priority (caller-supplied snapshot, same pattern as
    category/department) and emails.resolved_at (set only on a real
    RESOLVED transition, not on any field edit).
  - feedback_events: the new queryable home for corrections/confirmations
    across every module (FR-58 to FR-62).
  - retraining_triggers: FR-61's threshold-crossing audit log.

Revision ID: d1e9a4c73f58
Revises: c8f2a7e91d36
Create Date: 2026-08-10 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd1e9a4c73f58'
down_revision: Union[str, Sequence[str], None] = 'c8f2a7e91d36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ORG_SCOPED_LOG_TABLES = (
    "spam_prediction_logs",
    "priority_prediction_logs",
    "category_prediction_logs",
    "summary_logs",
    "sentiment_prediction_logs",
    "intent_prediction_logs",
    "routing_decision_logs",
)


def upgrade() -> None:
    """Upgrade schema."""
    for table in _ORG_SCOPED_LOG_TABLES:
        op.add_column(
            table,
            sa.Column("organization_id", sa.String(length=100), nullable=False, server_default="default"),
        )
        op.create_index(f"ix_{table}_org_created", table, ["organization_id", "created_at"])

    op.add_column("emails", sa.Column("priority", sa.String(length=20), nullable=True))
    op.add_column("emails", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_emails_org_received", "emails", ["organization_id", "received_at"])

    op.create_table(
        "feedback_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("module", sa.String(length=30), nullable=False),
        sa.Column("organization_id", sa.String(length=100), nullable=False, server_default="default"),
        sa.Column("prediction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("original_value", sa.JSON(), nullable=True),
        sa.Column("corrected_value", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reviewer_id", sa.String(length=100), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("ix_feedback_events_org_created", "feedback_events", ["organization_id", "created_at"])
    op.create_index("ix_feedback_events_module_action", "feedback_events", ["module", "action"])
    op.create_index("ix_feedback_events_prediction_id", "feedback_events", ["prediction_id"])

    op.create_table(
        "retraining_triggers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("module", sa.String(length=30), nullable=False),
        sa.Column("feedback_count_at_trigger", sa.Integer(), nullable=False),
        sa.Column("threshold_used", sa.Integer(), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "triggered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("ix_retraining_triggers_module", "retraining_triggers", ["module"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_retraining_triggers_module", table_name="retraining_triggers")
    op.drop_table("retraining_triggers")

    op.drop_index("ix_feedback_events_prediction_id", table_name="feedback_events")
    op.drop_index("ix_feedback_events_module_action", table_name="feedback_events")
    op.drop_index("ix_feedback_events_org_created", table_name="feedback_events")
    op.drop_table("feedback_events")

    op.drop_index("ix_emails_org_received", table_name="emails")
    op.drop_column("emails", "resolved_at")
    op.drop_column("emails", "priority")

    for table in _ORG_SCOPED_LOG_TABLES:
        op.drop_index(f"ix_{table}_org_created", table_name=table)
        op.drop_column(table, "organization_id")
