from datetime import datetime
from pydantic import BaseModel, Field

class VerificationRequest(BaseModel):
    potential_name: str = Field(..., description="Name or KIM model ID")
    properties: list[str] = Field(default=["lattice_constant", "cohesive_energy", "elastic_constants"])
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
