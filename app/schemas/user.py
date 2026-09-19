"""Pydantic schemas for user-related endpoints."""

from uuid import UUID

from pydantic import BaseModel


class UserResponse(BaseModel):
    id: UUID
    firebase_uid: str | None = None
    name: str
    email: str
    phone: str | None
    role: str

    class Config:
        from_attributes = True


class UpdateFcmTokenRequest(BaseModel):
    fcm_token: str


class UserSearchResult(BaseModel):
    """
    What one user may learn about another before any link exists.

    Deliberately excludes email and phone. Search is how you *find* the person
    to ask; contact details are what you get once they have accepted, through
    the care network. Returning the full UserResponse here handed every signed-in
    account the whole directory — name, email and phone number for everyone.
    """

    id: UUID
    name: str
    role: str

    class Config:
        from_attributes = True
