"""phase 12 multi-agent schema

Hand-written, same reason as every prior migration in this repo: no live
Postgres instance reachable to autogenerate against in this environment.

Adds the two durable workflow-state tables Module 13 / Phase 12 needs
(FR-63, FR-66, FR-67) -- see PHASE_12_AUDIT_REPORT.md section 6.1 for why
this state lives in Postgres, not reconstructed from Kafka messages:
  - workflow_executions: one row per POST /api/v1/email/process call.
  - agent_executions: one row per (workflow_id, agent_name) -- the
    idempotency/retry-tracking unit, see app/models/agent_execution.py.

Revision ID: e2f5b8c31a94
Revises: d1e9a4c73f58
Create Date: 2026-08-11 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e2f5b8c31a94'
down_revision: Union[str, Sequence[str], None] = 'd1e9a4c73f58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "workflow_executions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", sa.String(length=100), nullable=False, server_default="default"),
        sa.Column("email_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index(
        "ix_workflow_executions_org_started", "workflow_executions", ["organization_id", "started_at"]
    )
    op.create_index("ix_workflow_executions_status", "workflow_executions", ["status"])

    op.create_table(
        "agent_executions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_name", sa.String(length=30), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("error_type", sa.String(length=20), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("model_version", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("workflow_id", "agent_name", name="uq_agent_executions_workflow_agent"),
    )
    op.create_index("ix_agent_executions_workflow_id", "agent_executions", ["workflow_id"])
    op.create_index("ix_agent_executions_status", "agent_executions", ["status"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_agent_executions_status", table_name="agent_executions")
    op.drop_index("ix_agent_executions_workflow_id", table_name="agent_executions")
    op.drop_table("agent_executions")

    op.drop_index("ix_workflow_executions_status", table_name="workflow_executions")
    op.drop_index("ix_workflow_executions_org_started", table_name="workflow_executions")
    op.drop_table("workflow_executions")
