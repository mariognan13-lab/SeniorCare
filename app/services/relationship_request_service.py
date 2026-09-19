"""
Connection requests — asking to be linked to someone, and that person deciding.

The asymmetry is the design. :func:`create_request` is open to any signed-in
user; :func:`respond` is restricted to the ``target_id`` on the row. A link is
therefore only ever created by the person being cared for, never by the person
who wants access to them.

That restriction is not just privacy. It is what makes the direction of the
resulting ``Relationship`` correct by construction. ``trigger_sos`` selects
``Relationship.senior_id == <whoever pressed the button>``, so a link pointing
the wrong way means the senior's SOS reaches **nobody, silently, with no error**.
Letting the target be the one who accepts means the target is always the senior,
and that failure cannot happen.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import cast, or_, select, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    NotificationLog,
    Relationship,
    RelationshipRequest,
    RelationshipType,
    RequestStatus,
    User,
)
from app.services import notification_service

_LOADED = (
    selectinload(RelationshipRequest.requester),
    selectinload(RelationshipRequest.target),
)


async def _find_user(db: AsyncSession, identifier: str) -> User:
    """
    Resolve a user by email, firebase_uid, or id.

    Email matching is case-insensitive to agree with ``GET /users/search``, which
    uses ``ilike``: a person found by typing their address in any case must also
    be resolvable at the moment the request is actually sent, or the search would
    offer a name the send then rejects.

    UUID lookup uses both a cast comparison (PostgreSQL) and a raw string comparison
    so the same code works on SQLite (used as local fallback), where casting a UUID
    column may produce a different representation.
    """
    identifier = str(identifier).strip()

    res = await db.execute(
        select(User).where(
            or_(
                User.email.ilike(identifier),
                User.firebase_uid == identifier,
                cast(User.id, String) == identifier,
                cast(User.id, String) == identifier.lower(),
            )
        )
    )
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No user found for '{identifier}'",
        )
    return user


async def _reload(db: AsyncSession, request_id: UUID) -> RelationshipRequest:
    """Re-read a request with both parties attached, for the response model."""
    res = await db.execute(
        select(RelationshipRequest).options(*_LOADED).where(RelationshipRequest.id == request_id)
    )
    return res.scalar_one()


async def create_request(
    db: AsyncSession,
    requester_id: UUID,
    target_identifier: str,
    relationship_type: str,
    label: str | None = None,
    message: str | None = None,
) -> RelationshipRequest:
    """Ask to be connected to someone. They decide whether it happens."""
    target = await _find_user(db, target_identifier)

    if target.id == requester_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot send a connection request to yourself",
        )

    existing_link = await db.execute(
        select(Relationship).where(
            Relationship.senior_id == target.id,
            Relationship.related_user_id == requester_id,
        )
    )
    if existing_link.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You are already connected to {target.name}",
        )

    try:
        rel_type = RelationshipType(relationship_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown relationship type '{relationship_type}'",
        )

    res = await db.execute(
        select(RelationshipRequest).where(
            RelationshipRequest.requester_id == requester_id,
            RelationshipRequest.target_id == target.id,
        )
    )
    request = res.scalar_one_or_none()

    if request and request.status == RequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have a pending request with {target.name}",
        )

    if request:
        # Declined or cancelled previously. Re-ask rather than refuse: the answer
        # to a request is allowed to change, and the alternative would be a
        # permanent block decided by one tap.
        request.status = RequestStatus.PENDING
        request.relationship_type = rel_type
        request.label = label
        request.message = message
        request.created_at = datetime.now(timezone.utc)
        request.responded_at = None
    else:
        request = RelationshipRequest(
            requester_id=requester_id,
            target_id=target.id,
            relationship_type=rel_type,
            label=label,
            message=message,
            status=RequestStatus.PENDING,
        )
        db.add(request)

    await db.flush()

    requester = await db.execute(select(User).where(User.id == requester_id))
    requester_user = requester.scalar_one()

    # Log notification row for target user
    db.add(
        NotificationLog(
            user_id=target.id,
            title="New connection request",
            body=f"{requester_user.name} would like to connect with you.",
            notification_type="CONNECTION_REQUEST",
            data={
                "request_id": str(request.id),
                "requester_id": str(requester_id),
            },
        )
    )
    await db.flush()

    try:
        await notification_service.send_push(
            db=db,
            user_ids=[target.id],
            title="New connection request",
            body=f"{requester_user.name} would like to connect with you.",
            data={
                "notification_type": "CONNECTION_REQUEST",
                "request_id": str(request.id),
            },
        )
    except Exception:
        # Push notification failure must not roll back the connection request.
        pass

    return await _reload(db, request.id)


async def list_incoming(db: AsyncSession, user_id: UUID) -> list[RelationshipRequest]:
    """Requests still awaiting this user's decision — they are the one being asked."""
    res = await db.execute(
        select(RelationshipRequest)
        .options(*_LOADED)
        .where(
            RelationshipRequest.target_id == user_id,
            RelationshipRequest.status == RequestStatus.PENDING,
        )
        .order_by(RelationshipRequest.created_at.desc())
    )
    return list(res.scalars().all())


async def list_outgoing(db: AsyncSession, user_id: UUID) -> list[RelationshipRequest]:
    """Requests this user has sent, in every state, newest first."""
    res = await db.execute(
        select(RelationshipRequest)
        .options(*_LOADED)
        .where(RelationshipRequest.requester_id == user_id)
        .order_by(RelationshipRequest.created_at.desc())
    )
    return list(res.scalars().all())


async def respond(
    db: AsyncSession,
    request_id: UUID,
    user_id: UUID,
    accept: bool,
) -> RelationshipRequest:
    """
    Accept or decline a request.

    Only the person the request was addressed to may call this. On acceptance
    **they become the senior** — see the module docstring for why that matters.
    """
    res = await db.execute(
        select(RelationshipRequest).where(RelationshipRequest.id == request_id)
    )
    request = res.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    if request.target_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the person this request was sent to can respond to it",
        )

    if request.status != RequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This request has already been {request.status.value.lower()}",
        )

    if accept:
        db.add(
            Relationship(
                senior_id=request.target_id,
                related_user_id=request.requester_id,
                relationship_type=request.relationship_type,
                label=request.label or request.relationship_type.value.capitalize(),
                is_primary=False,
            )
        )
        request.status = RequestStatus.ACCEPTED
    else:
        request.status = RequestStatus.DECLINED

    request.responded_at = datetime.now(timezone.utc)
    await db.flush()

    if accept:
        target = await db.execute(select(User).where(User.id == request.target_id))
        target_user = target.scalar_one()

        db.add(
            NotificationLog(
                user_id=request.requester_id,
                title="Connection accepted",
                body=f"{target_user.name} accepted your connection request.",
                notification_type="CONNECTION_ACCEPTED",
                data={
                    "request_id": str(request.id),
                    "target_id": str(request.target_id),
                },
            )
        )
        await db.flush()

        try:
            await notification_service.send_push(
                db=db,
                user_ids=[request.requester_id],
                title="Connection accepted",
                body=f"{target_user.name} accepted your connection request.",
                data={
                    "notification_type": "CONNECTION_ACCEPTED",
                    "request_id": str(request.id),
                },
            )
        except Exception:
            # Push notification failure must not roll back the accepted status.
            pass

    return await _reload(db, request_id)
