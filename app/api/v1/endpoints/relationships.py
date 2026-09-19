"""Relationships endpoints — connection requests and direct care-network links."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import get_current_user_from_token
from app.core.database import get_db
from app.db.models import UserRole
from app.schemas.auth import UserResponse
from app.schemas.relationship import (
    ConnectUserRequest,
    RelationshipRequestCreate,
    RelationshipRequestResponse,
    RelationshipResponse,
)
from app.services import relationship_request_service, relationship_service

router = APIRouter()


# ── Connection requests ──
#
# These are declared before DELETE /{relationship_id} at the bottom of this file
# so the literal "requests" segment is matched ahead of the UUID path parameter.

@router.post(
    "/requests",
    response_model=RelationshipRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_connection_request(
    req: RelationshipRequestCreate,
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Ask to be connected to someone.

    The request does nothing on its own — it waits for the person it names to
    accept. See relationship_request_service for why only they can.
    """
    target_identifier = req.target_email or req.target_user_id
    if not target_identifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either target_email or target_user_id",
        )

    request = await relationship_request_service.create_request(
        db=db,
        requester_id=current_user.id,
        target_identifier=target_identifier,
        relationship_type=req.relationship_type,
        label=req.label,
        message=req.message,
    )
    return RelationshipRequestResponse.model_validate(request)


@router.get("/requests/incoming", response_model=list[RelationshipRequestResponse])
async def list_incoming_requests(
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Requests awaiting your decision."""
    requests = await relationship_request_service.list_incoming(db, current_user.id)
    return [RelationshipRequestResponse.model_validate(r) for r in requests]


@router.get("/requests/outgoing", response_model=list[RelationshipRequestResponse])
async def list_outgoing_requests(
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Requests you have sent, in every state."""
    requests = await relationship_request_service.list_outgoing(db, current_user.id)
    return [RelationshipRequestResponse.model_validate(r) for r in requests]


@router.post(
    "/requests/{request_id}/accept",
    response_model=RelationshipRequestResponse,
)
async def accept_connection_request(
    request_id: UUID,
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept a request and become connected.

    Accepting makes you the senior on the resulting link, so your SOS reaches
    everyone who accepts.
    """
    request = await relationship_request_service.respond(
        db=db,
        request_id=request_id,
        user_id=current_user.id,
        accept=True,
    )
    return RelationshipRequestResponse.model_validate(request)


@router.post(
    "/requests/{request_id}/decline",
    response_model=RelationshipRequestResponse,
)
async def decline_connection_request(
    request_id: UUID,
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Decline a request. No link is created, and the requester may ask again."""
    request = await relationship_request_service.respond(
        db=db,
        request_id=request_id,
        user_id=current_user.id,
        accept=False,
    )
    return RelationshipRequestResponse.model_validate(request)


# ── Direct links ──

@router.post("", response_model=RelationshipResponse, status_code=status.HTTP_201_CREATED)
async def connect_user(
    req: ConnectUserRequest,
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Add someone to your own care network directly.

    This is the one path that skips approval, and it is safe for exactly one
    reason: the caller can only ever add someone *to themselves*. You cannot use
    this to attach yourself to another person's care record — that has to go
    through a connection request, which they approve.
    """
    target_identifier = req.related_email or req.related_user_id
    if not target_identifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either related_email or related_user_id",
        )

    # Directly adding someone is the "the person being cared for sets themselves
    # up" path, so it belongs to a SENIOR account by definition — family and
    # caregivers reach people by request, which the other person approves.
    #
    # The check is also load-bearing for privacy. Without it this endpoint is a
    # way around the restriction on /users/search: look anyone up by name, take
    # their id from the result, connect to them, then read their email and phone
    # straight back out of /my-network.
    if current_user.role != UserRole.SENIOR.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a senior account can add someone directly. Send a connection request instead.",
        )

    rel = await relationship_service.connect_users(
        db=db,
        current_user_id=current_user.id,
        related_identifier=target_identifier,
        relationship_type=req.relationship_type,
        label=req.label,
        is_primary=req.is_primary,
    )
    return RelationshipResponse.model_validate(rel)


@router.get("/my-network", response_model=list[RelationshipResponse])
async def get_my_network(
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Fetch all connected relationships in the care network for current user."""
    relationships = await relationship_service.get_user_network(db, current_user.id)
    return [RelationshipResponse.model_validate(r) for r in relationships]


@router.delete("/{relationship_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_relationship(
    relationship_id: UUID,
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Remove a relationship connection link."""
    await relationship_service.delete_relationship(db, relationship_id, current_user.id)
