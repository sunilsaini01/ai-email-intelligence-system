"""
API response contracts for health/readiness checks.

Why a separate schema even for something this simple:
    Consistency. Every endpoint in this system returns a Pydantic schema, never
    a raw dict. That means FastAPI auto-generates accurate OpenAPI docs, and
    callers get a typed, validated contract instead of "whatever shape the
    function happened to return today."
"""

from pydantic import BaseModel

from app.mlops.model_metadata import ModelProvenance


class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str


class ReadinessResponse(BaseModel):
    status: str
    database: str


class RegisteredModelVersion(BaseModel):
    module: str
    model_version: str | None
    provenance: ModelProvenance | None


class ComponentVersionResponse(BaseModel):
    component_name: str
    classification: str
    version_identifier: str
    evidence_status: str
    notes: str


class ModelVersionsResponse(BaseModel):
    registered_models: list[RegisteredModelVersion]
    other_components: list[ComponentVersionResponse]
