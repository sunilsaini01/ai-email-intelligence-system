"""
API response contracts for health/readiness checks.

Why a separate schema even for something this simple:
    Consistency. Every endpoint in this system returns a Pydantic schema, never
    a raw dict. That means FastAPI auto-generates accurate OpenAPI docs, and
    callers get a typed, validated contract instead of "whatever shape the
    function happened to return today."
"""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str


class ReadinessResponse(BaseModel):
    status: str
    database: str
