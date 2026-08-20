"""
Health check endpoints.

Why TWO endpoints, not one:
    /health (liveness): "Is the process alive?" No dependencies checked.
        Used by orchestrators (k8s, docker) to decide whether to restart
        the container. It must NEVER depend on the DB — if Postgres is down,
        restarting your API container won't fix that, and you'd cause a
        restart loop on top of an outage.

    /health/ready (readiness): "Can this instance actually serve traffic?"
        Checks real dependencies (DB connection here; later: Kafka, vector DB).
        Used by load balancers to decide whether to route traffic to this
        instance. If the DB is unreachable, take THIS instance out of rotation
        without killing the process.

This distinction is a real production failure mode if skipped: a single
"/health" endpoint that pings the DB will, under a DB outage, get every
instance killed and restarted simultaneously by the orchestrator — turning
a DB blip into a full application outage.
"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.database.session import get_db
from app.mlops.component_versions import get_component_versions
from app.mlops.model_metadata import REGISTRABLE_MODULES, get_deployed_model_version
from app.schemas.health import (
    ComponentVersionResponse,
    HealthResponse,
    ModelVersionsResponse,
    ReadinessResponse,
    RegisteredModelVersion,
)

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def liveness_check(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_name=settings.APP_NAME,
        environment=settings.APP_ENV,
    )


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness_check(
    response: Response, db: AsyncSession = Depends(get_db)
) -> ReadinessResponse:
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        print("DB ERROR:", e)
        db_status = "unreachable"

    # A load balancer / Kubernetes readinessProbe reads the HTTP status
    # code, not the response body -- returning 200 here even when degraded
    # (as this endpoint used to) means nothing downstream can actually act
    # on the "degraded" body field. 503 is what makes this endpoint usable
    # as a real readiness probe target, not just an informational report.
    if db_status != "connected":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ok" if db_status == "connected" else "degraded",
        database=db_status,
    )


@router.get("/health/models", response_model=ModelVersionsResponse)
def model_versions() -> ModelVersionsResponse:
    """Answers "which exact model version is THIS pod serving" (Phase 15A
    / FR-71 deployment identification). Deliberately a pure local-file
    read, same as liveness_check() above -- no MLflow network call, no
    database query, so this endpoint stays fast and available even if
    MLflow or Postgres are both down. See docs/mlflow_architecture.md
    "Why Serving Never Calls MLflow"."""
    registered = []
    for module in REGISTRABLE_MODULES:
        version, provenance = get_deployed_model_version(module)
        registered.append(RegisteredModelVersion(module=module, model_version=version, provenance=provenance))

    other = [
        ComponentVersionResponse(
            component_name=c.component_name,
            classification=c.classification,
            version_identifier=c.version_identifier,
            evidence_status=c.evidence_status.value,
            notes=c.notes,
        )
        for c in get_component_versions()
    ]

    return ModelVersionsResponse(registered_models=registered, other_components=other)
