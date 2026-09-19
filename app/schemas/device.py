"""Pydantic schemas for device registration endpoints."""

from uuid import UUID

from pydantic import BaseModel, Field


class RegisterDeviceRequest(BaseModel):
    fcm_token: str = Field(..., description="Firebase Cloud Messaging Token")
    device_type: str = Field("android", description="Platform e.g. android/ios")
    device_name: str | None = Field(None, description="Optional device name")


class DeviceResponse(BaseModel):
    id: UUID
    user_id: UUID
    fcm_token: str
    device_type: str
    device_name: str | None

    class Config:
        from_attributes = True
