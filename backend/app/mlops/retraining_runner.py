"""
Executes retraining triggers (FR-61: "When feedback volume crosses a
threshold, system shall trigger retraining pipeline"; PRD Epic 4: trigger
retraining from the dashboard).

Run by the agents process (app/services/scheduled_jobs.py). For each
PENDING retraining_triggers row -- written automatically when a module's
corrections cross RETRAINING_FEEDBACK_THRESHOLD, or manually via
POST /models/retrain -- it runs that module's existing training script
with INCLUDE_FEEDBACK_CORRECTIONS=1, so the logged corrections are folded
into the train split (app/mlops/feedback_training_data.py).

What it deliberately does NOT do: promote the result. Every training
script registers an MLflow CANDIDATE and stops; turning a candidate into
the served model stays the explicit, regression-checked step in
scripts/mlops/promote_model.py (FR-71, docs/model_promotion_policy.md). A
feedback-triggered retrain that silently replaced production would let
a burst of bad corrections degrade the live model with nobody looking.

Modules with no trainable model get NOT_APPLICABLE with the reason, not a
silent no-op -- routing, for instance, already learns from its feedback
continuously (FR-41, app/routing/feedback_weights.py).
"""

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from app.database.repositories.retraining_trigger_repository import RetrainingTriggerRepository
from app.mlops.feedback_training_data import INCLUDE_FEEDBACK_ENV
from app.models.notification import KIND_RETRAINING
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID
from app.services.notification_service import notify

logger = logging.getLogger("app.mlops.retraining")

_REPO_ROOT = Path(__file__).resolve().parents[3]

TRAINING_SCRIPTS = {
    "spam": "backend/scripts/train_spam_model.py",
    "priority": "backend/scripts/train_priority_model.py",
    "category": "backend/scripts/train_category_model.py",
    "intent": "backend/scripts/train_intent_model.py",
}

NOT_RETRAINABLE = {
    "sentiment": "Sentiment is a zero-shot VADER lexicon scorer with no trained weights (docs/data_audit_sentiment.md).",
    "summarization": "Summarization uses extractive ranking and a pretrained DistilBART; nothing in-house to retrain.",
    "routing": "Routing learns from its feedback continuously via per-department thresholds (FR-41).",
    "auto_reply": "Auto-reply uses an external LLM; approved drafts feed later prompts as examples (FR-52).",
    "retrieval": "Retrieval uses a pretrained embedding model; relevance feedback is recorded for evaluation only.",
}

RETRAINING_TIMEOUT_SECONDS = 60 * 60
_OUTPUT_TAIL_CHARS = 2000

STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"


def _run_training_script(module: str) -> tuple[bool, str]:
    script = _REPO_ROOT / TRAINING_SCRIPTS[module]
    if not script.exists():
        return False, f"Training script not found at {script}."
    env = {**os.environ, INCLUDE_FEEDBACK_ENV: "1"}
    try:
        completed = subprocess.run(  # noqa: S603 -- fixed interpreter + fixed in-repo script path, no user input
            [sys.executable, str(script)],
            cwd=_REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=RETRAINING_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"Training exceeded {RETRAINING_TIMEOUT_SECONDS}s and was stopped."
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode == 0, output[-_OUTPUT_TAIL_CHARS:]


async def run_next_trigger(session) -> str | None:
    """Claims and executes at most one trigger. Returns its final status,
    or None when nothing was pending."""
    repo = RetrainingTriggerRepository(session)
    trigger = await repo.claim_next_pending()
    if trigger is None:
        return None

    module = trigger.module
    logger.info("retraining_started", extra={"trigger_id": str(trigger.id), "agent_name": module})

    if module not in TRAINING_SCRIPTS:
        reason = NOT_RETRAINABLE.get(module, "No training pipeline exists for this module.")
        await repo.finish(trigger, STATUS_NOT_APPLICABLE, reason)
        return STATUS_NOT_APPLICABLE

    succeeded, output = await asyncio.to_thread(_run_training_script, module)
    status = STATUS_COMPLETED if succeeded else STATUS_FAILED
    message = (
        "New MLflow candidate registered with feedback corrections included. "
        "Promote it with scripts/mlops/promote_model.py after review.\n"
        if succeeded
        else "Retraining failed.\n"
    ) + output
    await repo.finish(trigger, status, message)
    logger.info("retraining_finished", extra={"trigger_id": str(trigger.id), "agent_name": module, "status": status})

    try:
        await notify(
            session,
            DEFAULT_ORGANIZATION_ID,
            kind=KIND_RETRAINING,
            title=f"Retraining {status.lower()}: {module}",
            message=message.splitlines()[0],
            severity="info" if succeeded else "warning",
            dedup_key=f"{KIND_RETRAINING}:{trigger.id}",
            send_webhook=False,
        )
    except Exception:
        logger.warning("retraining_notification_failed", exc_info=True)
    return status
