"""
Thin MLflow wrapper -- imported ONLY by backend/scripts/train_*.py and
backend/scripts/mlops/promote_model.py. NEVER import this from app/services,
app/api, or app/agents -- that would put a live MLflow dependency on the
request-serving path, which is exactly what this phase's design explicitly
avoids (see docs/mlflow_architecture.md "Why Serving Never Calls MLflow").

Why mlflow.log_artifact() instead of mlflow.sklearn.log_model(): every
trained artifact in this project (artifacts/*_baseline.joblib) is an
instance of app.pipeline.ml_pipeline.MLPipeline, a project-specific class,
not a plain sklearn Estimator -- confirmed by loading one directly
(`type(joblib.load(...))` -> `app.pipeline.ml_pipeline.MLPipeline`).
mlflow.sklearn's flavor logic assumes sklearn's own conventions and isn't
guaranteed to round-trip a custom class correctly. Logging the exact
.joblib file as a generic artifact, then loading it back with joblib
(exactly what SpamService/PriorityService/etc. already do), sidesteps that
risk entirely -- the artifact MLflow stores is byte-identical to the one
ArtifactManager.save_model() produces, not a re-serialized copy.
"""

import os
import sys
from pathlib import Path
from typing import Any

import mlflow
from mlflow.tracking import MlflowClient

ARTIFACT_SUBPATH = "model"  # runs:/<run_id>/model/<filename> -- see download_candidate() below

# MLflow's own end_run() unconditionally prints "\U0001f3c3 View run ... at:
# ..." to stdout on every run (mlflow/tracking/_tracking_service/client.py
# _log_url()) -- not something this project's code controls or can
# silence via a flag. Windows' default console codepage (cp1252) cannot
# encode that emoji, so the print itself raises UnicodeEncodeError,
# propagating out of a successfully-completed mlflow.start_run() block and
# making log_training_run() LOOK like it failed even though the run was
# already fully logged (params, metrics, artifact, tags) before the crash
# -- confirmed by inspecting MLflow's own experiment/run list after a
# "failed" call. Reconfiguring stdout/stderr to UTF-8 here, once, before
# any mlflow call, fixes it at the source instead of papering over the
# exception in every caller.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")



# MLflow's own HTTP client defaults (MLFLOW_HTTP_REQUEST_TIMEOUT=120s,
# MLFLOW_HTTP_REQUEST_MAX_RETRIES=7, exponential backoff factor=2) mean an
# unreachable tracking server can make a single client call retry for
# minutes with zero progress output -- reproduced for real during this
# phase's own failure-injection testing (docs/evidence/mlflow_failure_modes.md):
# `promote_model.py` sat past 120s with the server stopped, no indication
# it was retrying rather than hung. This project's own use is either an
# interactive CLI (`promote_model.py` -- a human waiting on it deserves a
# fast, legible failure) or training scripts that already catch and
# gracefully degrade on any MLflow error (`train_*.py`'s own try/except --
# failing faster there only shortens an already-tolerated wait). Setting
# these here, once, before any mlflow call in this module, rather than
# requiring every caller to remember to configure it. `setdefault` so an
# operator who explicitly sets these env vars themselves is never overridden.
os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "10")
os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "2")
os.environ.setdefault("MLFLOW_HTTP_REQUEST_BACKOFF_FACTOR", "1")


def configure_tracking_uri() -> str:
    """MLFLOW_TRACKING_URI defaults to the Docker Compose service's
    host-published port (5001->5000, see docker-compose.yml) since every
    training/promotion script in this project runs on the host, not
    inside a container -- same established pattern as train_spam_model.py
    already being run via `python backend/scripts/train_spam_model.py`
    throughout this project's history, never via `docker exec`."""
    uri = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5001")
    mlflow.set_tracking_uri(uri)
    return uri


def log_training_run(
    *,
    experiment_name: str,
    model_filename: str,
    local_artifact_path: Path,
    params: dict[str, Any],
    metrics: dict[str, float],
    tags: dict[str, str],
    metrics_json_path: Path | None = None,
) -> str:
    """Logs one training run. Returns the MLflow run_id. Does NOT register
    a Model Registry version -- that's a separate, deliberate step
    (register_candidate()) so a logged run always exists even for
    experiments nobody intends to register as a candidate."""
    configure_tracking_uri()
    mlflow.set_experiment(experiment_name)

    with mlflow.start_run() as run:
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        for key, value in tags.items():
            mlflow.set_tag(key, value)
        mlflow.log_artifact(str(local_artifact_path), artifact_path=ARTIFACT_SUBPATH)
        if metrics_json_path is not None and metrics_json_path.exists():
            mlflow.log_artifact(str(metrics_json_path), artifact_path=ARTIFACT_SUBPATH)
        return run.info.run_id


def register_candidate(*, run_id: str, model_name: str) -> str:
    """Registers the artifact logged by log_training_run() as a new Model
    Registry version, stage=None (a candidate -- see
    docs/model_lifecycle.md). Returns the new version number as a string.

    Uses MlflowClient.create_model_version() directly, NOT the higher-level
    mlflow.register_model() convenience wrapper -- reproduced for real
    during Phase 15A infrastructure testing: mlflow.register_model() in
    MLflow 3.x requires the run to have a formal "LoggedModel" entity
    (created by mlflow.<flavor>.log_model()/mlflow.pyfunc.log_model()) at
    the given artifact_path, and raises "Unable to find a logged_model
    with artifact_path model under run <id>" for a run that only used
    plain mlflow.log_artifact() (this project's deliberate choice --
    see this module's own docstring on why). create_model_version() is the
    lower-level API register_model() itself wraps, and accepts any valid
    runs:/ artifact URI without that requirement -- MLflow's own
    backward-compatible registration path, still fully supported."""
    configure_tracking_uri()
    client = MlflowClient()
    if not client.search_registered_models(filter_string=f"name='{model_name}'"):
        client.create_registered_model(model_name)
    model_uri = f"runs:/{run_id}/{ARTIFACT_SUBPATH}"
    mv = client.create_model_version(name=model_name, source=model_uri, run_id=run_id)
    return mv.version


def download_candidate(*, model_name: str, version: str, dst_dir: Path) -> Path:
    """Downloads a registered version's artifact directory to dst_dir.
    The returned path contains the exact filename
    (e.g. spam_baseline.joblib) each service's constructor expects at
    Path(artifact_dir) / MODEL_FILENAME -- promote_model.py points a
    throwaway SpamService(artifact_dir=...) at this directory to sanity-
    check the candidate before touching anything in artifacts/."""
    configure_tracking_uri()
    from mlflow.artifacts import download_artifacts

    uri = f"models:/{model_name}/{version}"
    downloaded = download_artifacts(artifact_uri=uri, dst_path=str(dst_dir))
    return Path(downloaded)


def get_run_metrics(run_id: str) -> dict[str, float]:
    configure_tracking_uri()
    client = MlflowClient()
    run = client.get_run(run_id)
    return dict(run.data.metrics)


def get_run_params(run_id: str) -> dict[str, str]:
    configure_tracking_uri()
    client = MlflowClient()
    run = client.get_run(run_id)
    return dict(run.data.params)


def get_run_tags(run_id: str) -> dict[str, str]:
    configure_tracking_uri()
    client = MlflowClient()
    run = client.get_run(run_id)
    return dict(run.data.tags)


def tag_run(run_id: str, key: str, value: str) -> None:
    """Sets a tag on an already-completed run. Used to attach the
    versioned-artifact filename's model_version string (e.g.
    "svm-20260813-145106") to the specific run that gets registered as a
    candidate -- needed because train_spam_model.py logs a run per
    candidate model_type INSIDE its comparison loop, before the winning
    model_version string is computed, so it can't be passed as a normal
    tag at log_training_run() time for that one script (see that script's
    own comment on this exact ordering)."""
    configure_tracking_uri()
    client = MlflowClient()
    client.set_tag(run_id, key, value)


def get_production_version(model_name: str) -> dict[str, Any] | None:
    """Returns {"version": ..., "run_id": ..., "metrics": {...}} for
    whichever version currently has the mlflow_stage tag Production
    (see transition_stage() -- this project uses a version-level tag,
    not MLflow's older stages API, which is deprecated as of MLflow 2.9+
    and removed entirely in newer client APIs)."""
    configure_tracking_uri()
    client = MlflowClient()
    try:
        versions = client.search_model_versions(f"name='{model_name}'")
    except Exception:
        return None
    for v in versions:
        if v.tags.get("stage") == "Production":
            return {"version": v.version, "run_id": v.run_id, "metrics": get_run_metrics(v.run_id)}
    return None


def list_versions(model_name: str) -> list[dict[str, Any]]:
    configure_tracking_uri()
    client = MlflowClient()
    versions = client.search_model_versions(f"name='{model_name}'")
    return [
        {
            "version": v.version,
            "run_id": v.run_id,
            "stage": v.tags.get("stage", "None"),
            "created_at": v.creation_timestamp,
        }
        for v in sorted(versions, key=lambda v: int(v.version))
    ]


def transition_stage(*, model_name: str, version: str, stage: str) -> None:
    """Sets a `stage` tag on the version (Production/Archived/None). If
    setting stage=Production, every OTHER version of this model that
    currently has stage=Production is first moved to Archived -- MLflow's
    registry allows multiple versions to carry any tag simultaneously
    (tags aren't exclusive), so single-Production-per-model is a policy
    this function enforces, not something the registry guarantees on its
    own. See docs/mlflow_failure_modes.md "Race Conditions During
    Promotion" for the known limitation this doesn't fully close."""
    configure_tracking_uri()
    client = MlflowClient()
    if stage == "Production":
        for v in client.search_model_versions(f"name='{model_name}'"):
            if v.version != version and v.tags.get("stage") == "Production":
                client.set_model_version_tag(model_name, v.version, "stage", "Archived")
    client.set_model_version_tag(model_name, version, "stage", stage)
