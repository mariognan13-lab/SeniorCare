"""Pydantic schemas for authentication endpoints."""

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    phone: str | None = Field(None, max_length=20)
    role: str = Field(..., pattern="^(SENIOR|FAMILY|CAREGIVER)$")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SyncUserRequest(BaseModel):
    firebase_uid: str
    email: EmailStr
    name: str = "User"
    phone: str | None = None
    role: str = "SENIOR"
    fcm_token: str | None = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"


# Avoid circular import — define inline
class UserResponse(BaseModel):
    id: UUID
    firebase_uid: str | None = None
    name: str
    email: str
    phone: str | None
    role: str

    class Config:
        from_attributes = True


# Update forward ref
AuthResponse.model_rebuild()

