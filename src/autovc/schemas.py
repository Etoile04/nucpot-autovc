from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class VerificationRequest(BaseModel):
    potential_name: str = Field(..., description="Name or KIM model ID")
    properties: list[str] = Field(default=["lattice_constant", "cohesive_energy", "elastic_constants"])
    species: list[str] = Field(default=[])
    structure: str = Field(default="BCC")


class ParameterizedVerificationRequest(BaseModel):
    """Phase 2: Template-based verification with parameter overrides."""
    potential_name: str = Field(..., description="Name or KIM model ID")
    template: str = Field(default="basic", description="Template name: basic, mechanical, defect, comprehensive")
    property_overrides: list[str] | None = Field(
        default=None,
        description="Override template properties. If set, replaces template property list.",
    )
    parameter_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description="Override computation parameters, e.g. {'lattice_guess': 3.5, 'species': 'U'}",
    )
    species: list[str] = Field(default=[])
    structure: str = Field(default="BCC")


class PotentialCreate(BaseModel):
    name: str
    potential_type: str
    species: list[str]
    kim_model_id: str | None = None
    source_url: str | None = None
    file_path: str | None = None


class VerificationResultResponse(BaseModel):
    property_name: str
    computed_value: float
    reference_value: float | None
    unit: str
    absolute_error: float | None
    relative_error: float | None
    grade: str | None
    details: dict | None = None


class VerificationJobResponse(BaseModel):
    id: int
    potential_id: int
    status: str
    properties_requested: list[str]
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    results: list[VerificationResultResponse] = []
    model_config = {"from_attributes": True}


class PotentialResponse(BaseModel):
    id: int
    name: str
    potential_type: str
    species: list[str]
    kim_model_id: str | None
    created_at: datetime
    jobs: list[VerificationJobResponse] = []
    model_config = {"from_attributes": True}


class TemplateResponse(BaseModel):
    id: str
    name: str
    description: str
    properties: list[str]
    estimated_time_minutes: int
    tags: list[str]


class ScoreReport(BaseModel):
    """Structured scoring report for a verification job."""
    job_id: int
    potential_name: str
    overall_grade: str | None
    property_scores: list[dict[str, Any]]
    summary: str
    created_at: datetime | None = None
