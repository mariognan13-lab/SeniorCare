"""Pydantic schemas for emergency SOS endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field
from app.schemas.auth import UserResponse


class SOSTriggerRequest(BaseModel):
    emergency_type: str = Field("GENERAL", description="Type of emergency e.g. MEDICAL, FALL, GENERAL")
    description: str | None = Field("Emergency assistance requested", description="Description")
    latitude: float | None = None
    longitude: float | None = None
    priority: int = Field(1, description="1=Normal, 2=High, 3=Critical")


class SOSAssignmentResponse(BaseModel):
    id: UUID
    emergency_id: UUID
    caregiver_id: UUID
    status: str
    assigned_at: datetime
    caregiver: UserResponse | None = None

    class Config:
        from_attributes = True


class SOSResponse(BaseModel):
    id: UUID
    senior_id: UUID
    emergency_type: str
    description: str | None
    status: str
    priority: int
    latitude: float | None = None
    longitude: float | None = None
    created_at: datetime
    resolved_at: datetime | None = None
    senior: UserResponse | None = None
    assignments: list[SOSAssignmentResponse] = []

    class Config:
        from_attributes = True


class SOSActionResponse(BaseModel):
    success: bool
    message: str
    emergency: SOSResponse
