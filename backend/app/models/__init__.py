"""
Every ORM model must be imported here so Base.metadata is fully populated —
Alembic's autogenerate (and any ad-hoc Base.metadata.create_all) walks
Base.metadata, not the filesystem. A model that only gets imported by
whatever endpoint happens to use it is invisible to migrations until
something else imports it first, which is a subtle, easy-to-miss bug.
"""

from app.models.priority_prediction_log import PriorityPredictionLog
from app.models.spam_prediction_log import SpamPredictionLog

__all__ = ["PriorityPredictionLog", "SpamPredictionLog"]
