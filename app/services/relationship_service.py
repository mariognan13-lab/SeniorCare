"""
Relationship service — handles SQL connect relationship links between users.
Supports senior-senior partner care, family, and caregiver connections.
"""

from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy import cast, or_, select, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import NotificationLog, Relationship, RelationshipType, User
from app.services import notification_service


async def connect_users(
    db: AsyncSession,
    current_user_id: UUID,
    related_identifier: str,  # Email or UUID string
    relationship_type: str,
    label: str | None = None,
    is_primary: bool = False,
) -> Relationship:
    """Establish a SQL connection link between current user and target user."""
    related_identifier = str(related_identifier).strip()
    stmt = select(User).where(
        or_(
            User.email.ilike(related_identifier),
            cast(User.id, String) == related_identifier,
        )
    )
    res = await db.execute(stmt)
    target_user = res.scalar_one_or_none()

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target user '{related_identifier}' not found",
        )

    if current_user_id == target_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot establish relationship with self",
        )

    # The caller is always the senior on a link they create themselves. That is
    # precisely what makes this path safe to leave unapproved: you can only ever
    # add someone *to your own* care network, never attach yourself to another
    # person's record. Links in the other direction go through
    # relationship_request_service, where the person being cared for accepts.
    senior_id = current_user_id
    related_user_id = target_user.id

    # Validate type enum
    try:
        rel_type_enum = RelationshipType(relationship_type)
    except ValueError:
        rel_type_enum = RelationshipType.OTHER

    # Check if relationship already exists
    existing = await db.execute(
        select(Relationship).where(
            Relationship.senior_id == senior_id,
            Relationship.related_user_id == related_user_id,
        )
    )
    rel = existing.scalar_one_or_none()

    if rel:
        rel.relationship_type = rel_type_enum
        if label:
            rel.label = label
        rel.is_primary = is_primary
    else:
        rel = Relationship(
            senior_id=senior_id,
            related_user_id=related_user_id,
            relationship_type=rel_type_enum,
            label=label or relationship_type.capitalize(),
            is_primary=is_primary,
        )
        db.add(rel)

    await db.flush()

    # Load senior details for notification
    senior_user_res = await db.execute(select(User).where(User.id == current_user_id))
    senior_user = senior_user_res.scalar_one_or_none()
    senior_name = senior_user.name if senior_user else "A senior care recipient"

    # Log notification and send push to target user
    db.add(
        NotificationLog(
            user_id=target_user.id,
            title="Added to Care Network",
            body=f"{senior_name} added you to their care network.",
            notification_type="CONNECTION_ACCEPTED",
            data={
                "relationship_id": str(rel.id),
                "senior_id": str(senior_id),
            },
        )
    )
    await db.flush()

    await notification_service.send_push(
        db=db,
        user_ids=[target_user.id],
        title="Added to Care Network",
        body=f"{senior_name} added you to their care network.",
        data={
            "notification_type": "CONNECTION_ACCEPTED",
            "relationship_id": str(rel.id),
            "senior_id": str(senior_id),
        },
    )

    # Reload with related user relationship populated
    res_rel = await db.execute(
        select(Relationship)
        .options(selectinload(Relationship.related_user))
        .where(Relationship.id == rel.id)
    )
    return res_rel.scalar_one()


async def get_user_network(db: AsyncSession, user_id: UUID) -> list[Relationship]:
    """Fetch all connected relationships for a user (both care recipients & caregivers/partners)."""
    stmt = (
        select(Relationship)
        .options(
            selectinload(Relationship.related_user),
            selectinload(Relationship.senior),
        )
        .where(
            or_(
                Relationship.senior_id == user_id,
                Relationship.related_user_id == user_id,
            )
        )
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def delete_relationship(db: AsyncSession, relationship_id: UUID, user_id: UUID) -> None:
    """Remove a user connection."""
    res = await db.execute(select(Relationship).where(Relationship.id == relationship_id))
    rel = res.scalar_one_or_none()
    if not rel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found")
    
    if rel.senior_id != user_id and rel.related_user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to remove this connection")
    
    await db.delete(rel)
    await db.flush()
