"""Pydantic schemas for user relationships endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field
from app.schemas.auth import UserResponse
from app.schemas.user import UserSearchResult


class ConnectUserRequest(BaseModel):
    related_email: str | None = Field(None, description="Email of the user to connect with")
    related_user_id: str | None = Field(None, description="User ID of the user to connect with")
    relationship_type: str = Field(..., pattern="^(FAMILY|CAREGIVER|SPOUSE|PARTNER|OTHER)$")
    label: str | None = Field(None, description="Custom role/label e.g. Spouse Caregiver, Partner")
    is_primary: bool = Field(False)


class UpdateRelationshipRequest(BaseModel):
    label: str | None = None
    is_primary: bool | None = None


class RelationshipResponse(BaseModel):
    id: UUID
    senior_id: UUID
    related_user_id: UUID
    relationship_type: str
    label: str | None = None
    is_primary: bool
    related_user: UserResponse

    class Config:
        from_attributes = True


class RelationshipRequestCreate(BaseModel):
    """
    A request to be connected to someone.

    Note the fields are `target_*`, not `senior_*`. The caller does not get to
    decide who the senior is — **the person being asked becomes the senior when
    they accept.** Naming it after the target rather than the role keeps that
    straight at every call site.
    """

    target_email: str | None = Field(None, description="Email of the person you are asking")
    target_user_id: str | None = Field(None, description="User ID of the person you are asking")
    relationship_type: str = Field(..., pattern="^(FAMILY|CAREGIVER|SPOUSE|PARTNER|OTHER)$")
    label: str | None = Field(None, max_length=100, description="e.g. Daughter, Night nurse")
    message: str | None = Field(None, description="Optional note shown alongside the request")


class RelationshipRequestResponse(BaseModel):
    id: UUID
    requester_id: UUID
    target_id: UUID
    relationship_type: str
    label: str | None = None
    message: str | None = None
    status: str
    created_at: datetime
    responded_at: datetime | None = None
    requester: UserSearchResult
    target: UserSearchResult

    class Config:
        from_attributes = True
