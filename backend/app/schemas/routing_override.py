"""API contracts for admin-configurable routing overrides (Phase 21, FR-39)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.routing.department_taxonomy import DEPARTMENTS
from app.routing.overrides import CONDITION_FIELDS, CONDITION_OPERATORS
from app.schemas.routing import RoutingAction


class RoutingOverrideCondition(BaseModel):
    field: str = Field(description=f"One of {CONDITION_FIELDS}.")
    operator: str = Field(description=f"One of {CONDITION_OPERATORS}.")
    value: str | bool | list[str]

    @field_validator("field")
    @classmethod
    def _validate_field(cls, v: str) -> str:
        if v not in CONDITION_FIELDS:
            raise ValueError(f"field must be one of {CONDITION_FIELDS}")
        return v

    @field_validator("operator")
    @classmethod
    def _validate_operator(cls, v: str) -> str:
        if v not in CONDITION_OPERATORS:
            raise ValueError(f"operator must be one of {CONDITION_OPERATORS}")
        return v


class RoutingOverrideCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    priority_order: int = Field(default=100, description="Lower is evaluated first.")
    is_active: bool = Field(default=True)
    conditions: list[RoutingOverrideCondition] = Field(..., min_length=1, description="ANDed together.")
    override_department: str | None = Field(default=None)
    override_action: RoutingAction | None = Field(default=None)
    override_requires_human_review: bool | None = Field(default=None)

    @field_validator("override_department")
    @classmethod
    def _validate_department(cls, v: str | None) -> str | None:
        if v is not None and v not in DEPARTMENTS:
            raise ValueError(f"override_department must be one of {DEPARTMENTS}")
        return v

    @model_validator(mode="after")
    def _requires_at_least_one_action(self) -> "RoutingOverrideCreateRequest":
        if self.override_department is None and self.override_action is None and self.override_requires_human_review is None:
            raise ValueError(
                "At least one of override_department, override_action, or "
                "override_requires_human_review must be set -- an override "
                "that changes nothing isn't a valid rule."
            )
        return self


class RoutingOverrideUpdateRequest(BaseModel):
    """All fields optional (a partial update) -- the endpoint applies only
    the fields actually present in the request body (`exclude_unset`), so
    explicitly setting a field to `null` clears it, while omitting it
    entirely leaves the stored value alone."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    priority_order: int | None = None
    is_active: bool | None = None
    conditions: list[RoutingOverrideCondition] | None = Field(default=None, min_length=1)
    override_department: str | None = None
    override_action: RoutingAction | None = None
    override_requires_human_review: bool | None = None

    @field_validator("override_department")
    @classmethod
    def _validate_department(cls, v: str | None) -> str | None:
        if v is not None and v not in DEPARTMENTS:
            raise ValueError(f"override_department must be one of {DEPARTMENTS}")
        return v


class RoutingOverrideResponse(BaseModel):
    id: uuid.UUID
    name: str
    priority_order: int
    is_active: bool
    conditions: list[RoutingOverrideCondition]
    override_department: str | None
    override_action: str | None
    override_requires_human_review: bool | None
    created_at: datetime
    updated_at: datetime


class RoutingOverrideListResponse(BaseModel):
    overrides: list[RoutingOverrideResponse]
