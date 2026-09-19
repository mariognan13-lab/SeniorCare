"""Pydantic schemas for medication endpoints."""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class CreateMedicationRequest(BaseModel):
    senior_id: UUID | None = Field(None, description="Senior user ID (defaults to current user)")
    name: str = Field(..., min_length=1, max_length=255)
    dosage: str = Field(..., min_length=1, max_length=100)
    frequency: str = Field(..., min_length=1, max_length=100)
    schedule_times: list[str] = Field(..., description="e.g. ['08:00', '20:00'] or ISO datetimes")
    start_date: datetime | None = None
    end_date: datetime | None = None
    notes: str | None = None


class RespondMedicationLogRequest(BaseModel):
    status: str = Field(..., pattern="^(TAKEN|SKIPPED|MISSED)$")
    notes: str | None = None


class MedicationResponse(BaseModel):
    id: UUID
    senior_id: UUID
    name: str
    dosage: str
    frequency: str
    schedule_times: list[str]
    is_active: bool
    notes: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class MedicationLogResponse(BaseModel):
    id: UUID
    medication_id: UUID
    medication_name: str
    scheduled_time: datetime
    taken_at: datetime | None = None
    status: str
    notes: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True
