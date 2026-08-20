"""
Model provenance schema (Phase 15A / FR-71).

Deliberately has NO `import mlflow` anywhere in this file. This module is
imported by the request-serving path (app/api/v1/endpoints/health.py, via
get_deployed_model_versions() below) as well as by training/promotion
scripts -- keeping it mlflow-free means the deployed api/agents Docker
image never needs the mlflow client installed at all (see
requirements-mlops.txt's own comment). MLflow-specific logic (actually
talking to the tracking server) lives in app/mlops/mlflow_client.py,
imported only by scripts/train_*.py and scripts/mlops/promote_model.py.

Design: this does NOT replace how SpamService/PriorityService/etc. already
read `model_version` from their `{module}_baseline_metrics.json` file --
that stays exactly as it was before this phase. This module ADDS a
`provenance` key to that same file, written by the promotion script,
read by anything that wants richer version identity than the bare
version string (e.g. "which MLflow run produced this, which git commit,
was this a rollback").
"""

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

# Resolved relative to this file, not the process's cwd -- matches every
# *Service class's own _DEFAULT_ARTIFACT_DIR (e.g. app/services/spam_service.py).
# A plain "artifacts" default (cwd-relative) is wrong in exactly the
# environment this module's own docstring cares most about: the API
# container's cwd is /app (WORKDIR), while the artifacts/ bind mount lives
# at /artifacts -- confirmed by a real /health/models call against the
# running email_ai_api container returning model_version=null for every
# module despite artifacts/spam_baseline_metrics.json existing on disk,
# during this phase's own real-infrastructure verification.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_ARTIFACT_DIR = str(_REPO_ROOT / "artifacts")


class EvidenceStatus(StrEnum):
    """What kind of evidence backs this model's metrics -- MUST NOT be
    inferred or guessed at promotion time; see MODULE_EVIDENCE_STATUS
    below. This is the single field the whole comparison/promotion
    pipeline exists to keep from getting silently upgraded to look more
    validated than it actually is (see docs/model_promotion_policy.md)."""

    REAL_HELDOUT = "real_holdout"
    SYNTHETIC_LABEL = "synthetic_label"
    OFF_DOMAIN = "off_domain"
    UNVALIDATED = "unvalidated"
    PRETRAINED_EXTERNAL = "pretrained_external"


# The ONLY place evidence status is decided for a registrable model --
# scripts/mlops/promote_model.py reads from here, never from a CLI flag or
# a value baked into the training script's own output, specifically so a
# promotion can't accidentally mislabel a synthetic-label model as
# real-holdout evidence by omission. Matches this project's own disclosed
# status for each module (README.md "Evidence & Known Limitations",
# docs/model_cards/*.md) -- if that disclosure ever changes, this mapping
# and the docs must change together, not silently drift apart.
MODULE_EVIDENCE_STATUS: dict[str, EvidenceStatus] = {
    "spam": EvidenceStatus.REAL_HELDOUT,
    "priority": EvidenceStatus.SYNTHETIC_LABEL,
    "category": EvidenceStatus.SYNTHETIC_LABEL,
    "intent": EvidenceStatus.SYNTHETIC_LABEL,
}

# Every module registrable in MLflow (Category A from docs/mlflow_architecture.md's
# classification) uses this exact filename pattern -- verified against
# every *_service.py in this codebase during the Phase 15A audit.
REGISTRABLE_MODULES = tuple(MODULE_EVIDENCE_STATUS.keys())


class ModelProvenance(BaseModel):
    mlflow_run_id: str | None = None
    mlflow_model_name: str | None = None
    mlflow_model_version: str | None = None
    mlflow_stage: str | None = None
    git_commit: str | None = None
    dataset_version: str | None = None
    evidence_status: EvidenceStatus
    promoted_at: str | None = None
    promoted_by: str = "manual"
    rollback_of: str | None = None


def read_provenance(metrics_path: Path) -> ModelProvenance | None:
    """Returns None (not an error) for a metrics file that predates this
    phase and has no `provenance` key yet -- e.g. a model trained before
    FR-71 and never promoted through the new pipeline. Callers must treat
    None as "no MLflow-backed provenance recorded," not as a load failure."""
    if not metrics_path.exists():
        return None
    data = json.loads(metrics_path.read_text(encoding="utf-8"))
    raw = data.get("provenance")
    if raw is None:
        return None
    return ModelProvenance.model_validate(raw)


def write_provenance(metrics_path: Path, provenance: ModelProvenance) -> None:
    """Merges into the existing metrics JSON -- never overwrites the
    training-time fields (comparison, decision_threshold, etc.) that
    train_*.py already wrote. Called only by scripts/mlops/promote_model.py,
    never by the request-serving path."""
    data = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    data["provenance"] = json.loads(provenance.model_dump_json())
    metrics_path.write_text(json.dumps(data, indent=4), encoding="utf-8")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def get_deployed_model_version(module: str, artifact_dir: str = _DEFAULT_ARTIFACT_DIR) -> tuple[str | None, ModelProvenance | None]:
    """Reads model_version + provenance (if any) for one registrable
    module, straight from its {module}_baseline_metrics.json -- the exact
    same file each *_service.py already reads its own model_version from.
    Zero network calls, zero mlflow import -- safe to call from the
    request-serving path (see /api/v1/health/models)."""
    metrics_path = Path(artifact_dir) / f"{module}_baseline_metrics.json"
    if not metrics_path.exists():
        return None, None
    data = json.loads(metrics_path.read_text(encoding="utf-8"))
    return data.get("model_version"), read_provenance(metrics_path)
