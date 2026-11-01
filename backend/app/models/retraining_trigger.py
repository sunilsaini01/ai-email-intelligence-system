"""
Retraining-threshold trigger audit log (Module 11 / Phase 11, FR-61).

FR-61 says "when feedback volume crosses a threshold, system shall
trigger retraining pipeline" -- this table IS the complete scope of what
Phase 11 builds for that requirement: a row is written when a module's
correction count crosses RETRAINING_FEEDBACK_THRESHOLD
(app/core/config.py), nothing more. No retraining executes, no model
artifact is touched, no CI/CD job is invoked -- see
docs/architecture_dashboard.md "Retraining trigger" and the master
prompt's own explicit non-goal ("do not automatically retrain production
models yet"). `consumed` exists so a LATER MLOps/CI/CD phase has a real
field to claim a trigger without deleting this audit history -- Phase 11
never sets it True itself.

One row per crossing event (not a running counter) so the crossing
itself stays a discrete, auditable fact: when did this happen, at what
count, against what threshold -- not just "yes/no, currently over."
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.spam_prediction_log import GUID


class RetrainingTrigger(Base):
    __tablename__ = "retraining_triggers"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    module: Mapped[str] = mapped_column(String(30))
    feedback_count_at_trigger: Mapped[int] = mapped_column(Integer)
    threshold_used: Mapped[int] = mapped_column(Integer)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)

    # FR-61 execution (app/mlops/retraining_runner.py). A trigger is
    # PENDING until the agents process claims it; `consumed` is set True at
    # claim time so the pre-existing column keeps its documented meaning.
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    # "feedback_threshold" (automatic, FR-61) or "manual" (PRD Epic 4's
    # "trigger retraining from the dashboard").
    source: Mapped[str] = mapped_column(String(30), default="feedback_threshold")
    requested_by_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
