"""
Regression test for the DB metadata registration gap found during Phase 7A's
Gate D audit (see app/models/__init__.py's docstring): CategoryPredictionLog
and SummaryLog were added in Phases 5/6 but never imported into
app/models/__init__.py, making them invisible to Alembic's autogenerate (and
any ad-hoc Base.metadata.create_all) despite having hand-written migrations
that worked anyway. Fixed alongside adding SentimentPredictionLog. This test
locks in that every prediction-log model stays registered, so the same class
of gap can't silently reopen for a future module.
"""

from app.database.session import Base
import app.models  # noqa: F401 -- importing the package is what populates Base.metadata


EXPECTED_TABLES = {
    "spam_prediction_logs",
    "priority_prediction_logs",
    "category_prediction_logs",
    "summary_logs",
    "sentiment_prediction_logs",
    "intent_prediction_logs",
    "routing_decision_logs",
    "emails",
    "reply_drafts",
}


def test_every_prediction_log_table_is_registered_in_base_metadata():
    registered = set(Base.metadata.tables.keys())
    missing = EXPECTED_TABLES - registered
    assert not missing, f"Tables missing from Base.metadata (invisible to Alembic autogenerate): {missing}"


def test_models_dunder_all_matches_the_actual_registered_models():
    expected_names = {
        "CategoryPredictionLog",
        "EmailRecord",
        "IntentPredictionLog",
        "PriorityPredictionLog",
        "ReplyDraft",
        "RoutingDecisionLog",
        "SentimentPredictionLog",
        "SpamPredictionLog",
        "SummaryLog",
    }
    assert set(app.models.__all__) == expected_names
