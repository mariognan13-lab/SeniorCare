"""
SOS service — handles emergency trigger, SQL relationship lookup, assignment, audit logging, and status transitions.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.alert_stream import manager as _sse
from app.core.config import settings
from app.core.rtdb import sync_emergency_to_rtdb
from app.db.models import (
    AssignmentStatus, Emergency, EmergencyAssignment, EmergencyEvent,
    EmergencyStatus, NotificationLog, Relationship, User,
)
from app.services import notification_service


async def trigger_sos(
    db: AsyncSession,
    senior_id: UUID,
    emergency_type: str = "GENERAL",
    description: str | None = None,
    priority: int = 1,
    latitude: float | None = None,
    longitude: float | None = None,
) -> Emergency:
    """Trigger an emergency SOS, assign to connected primary caregivers/partners, and record events."""
    emergency = Emergency(
        senior_id=senior_id,
        emergency_type=emergency_type,
        description=description or "Emergency assistance requested!",
        status=EmergencyStatus.CREATED,
        priority=priority,
        latitude=latitude,
        longitude=longitude,
    )
    db.add(emergency)
    await db.flush()

    # Log creation event
    event = EmergencyEvent(
        emergency_id=emergency.id,
        event_type="EMERGENCY_CREATED",
        actor_id=senior_id,
        details={"priority": priority, "emergency_type": emergency_type},
    )
    db.add(event)

    # Execute SQL connect lookup to find connected caregivers/partners/family members
    rel_stmt = select(Relationship).where(Relationship.senior_id == senior_id)
    rel_res = await db.execute(rel_stmt)
    relationships = rel_res.scalars().all()

    timeout_at = datetime.now(timezone.utc) + timedelta(seconds=settings.ASSIGNMENT_TIMEOUT_SECONDS)

    for rel in relationships:
        # Create assignment offer
        assignment = EmergencyAssignment(
            emergency_id=emergency.id,
            caregiver_id=rel.related_user_id,
            status=AssignmentStatus.PENDING,
            timeout_at=timeout_at,
        )
        db.add(assignment)

        # Log notification dispatch
        notif_log = NotificationLog(
            user_id=rel.related_user_id,
            title="EMERGENCY ALERT!",
            body=f"SOS alert from senior care recipient! ({emergency_type})",
            notification_type="EMERGENCY_ALERT",
            data={"emergency_id": str(emergency.id)},
        )
        db.add(notif_log)

    if relationships:
        emergency.status = EmergencyStatus.ASSIGNED

    await db.flush()

    # Load full emergency object with senior & assignments
    full_res = await db.execute(
        select(Emergency)
        .options(
            selectinload(Emergency.senior),
            selectinload(Emergency.assignments).selectinload(EmergencyAssignment.caregiver),
        )
        .where(Emergency.id == emergency.id)
    )
    full_emergency = full_res.scalar_one()

    # Now actually deliver the alerts.
    #
    # Everything above this line only wrote rows. Until this call existed, an SOS
    # created an assignment for exactly the right people and reached none of
    # them, because nothing in the backend had ever sent a push — so the only way
    # to discover an emergency was to open the app and look. send_push() never
    # raises, so a failure here cannot roll back the alert that summons help.
    senior_name = full_emergency.senior.name if full_emergency.senior else "Someone you care for"
    if relationships:
        await notification_service.send_push(
            db=db,
            user_ids=[rel.related_user_id for rel in relationships],
            title="Emergency alert",
            body=f"{senior_name} needs help — open the app to respond.",
            data={
                "notification_type": "EMERGENCY_ALERT",
                "emergency_id": str(full_emergency.id),
            },
        )

    # Broadcast live state to RTDB & SSE
    payload = {
        "emergency_id": str(full_emergency.id),
        "senior_id": str(senior_id),
        "senior_name": senior_name,
        "status": full_emergency.status.value,
        "emergency_type": full_emergency.emergency_type,
        "description": full_emergency.description,
        "priority": full_emergency.priority,
        "terminal": False,
        "updated_at": int(datetime.now(timezone.utc).timestamp()),
    }
    sync_emergency_to_rtdb(str(senior_id), payload)
    await _sse.broadcast(senior_id=senior_id, event=payload)

    return full_emergency


async def get_active_emergency_for_user(db: AsyncSession, user_id: UUID) -> Emergency | None:
    """Get currently active emergency for a user (either as senior or assigned caregiver)."""
    stmt = (
        select(Emergency)
        .options(
            selectinload(Emergency.senior),
            selectinload(Emergency.assignments).selectinload(EmergencyAssignment.caregiver),
        )
        .where(
            or_(
                Emergency.senior_id == user_id,
                Emergency.assignments.any(EmergencyAssignment.caregiver_id == user_id),
            ),
            Emergency.status.in_([
                EmergencyStatus.CREATED,
                EmergencyStatus.NOTIFIED,
                EmergencyStatus.ASSIGNED,
                EmergencyStatus.ACCEPTED,
                EmergencyStatus.IN_PROGRESS,
                EmergencyStatus.ESCALATED,
            ]),
        )
        .order_by(Emergency.created_at.desc())
    )
    res = await db.execute(stmt)
    return res.scalars().first()


async def accept_emergency(db: AsyncSession, emergency_id: UUID, caregiver_id: UUID) -> Emergency:
    """Caregiver or partner accepts an assigned emergency."""
    res = await db.execute(select(Emergency).where(Emergency.id == emergency_id))
    emergency = res.scalar_one_or_none()
    if not emergency:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Emergency not found")

    emergency.status = EmergencyStatus.ACCEPTED

    # Update caregiver's assignment row if present
    asgn_res = await db.execute(
        select(EmergencyAssignment).where(
            EmergencyAssignment.emergency_id == emergency_id,
            EmergencyAssignment.caregiver_id == caregiver_id,
        )
    )
    assignment = asgn_res.scalar_one_or_none()
    if assignment:
        assignment.status = AssignmentStatus.ACCEPTED
        assignment.responded_at = datetime.now(timezone.utc)

    # Log accept event
    event = EmergencyEvent(
        emergency_id=emergency.id,
        event_type="EMERGENCY_ACCEPTED",
        actor_id=caregiver_id,
    )
    db.add(event)
    await db.flush()

    full_res = await db.execute(
        select(Emergency)
        .options(
            selectinload(Emergency.senior),
            selectinload(Emergency.assignments).selectinload(EmergencyAssignment.caregiver),
        )
        .where(Emergency.id == emergency.id)
    )
    full_emergency = full_res.scalar_one()

    # Get details for notification messaging
    cg_res = await db.execute(select(User).where(User.id == caregiver_id))
    accepting_caregiver = cg_res.scalar_one_or_none()
    caregiver_name = accepting_caregiver.name if accepting_caregiver else "A caregiver"
    senior_name = full_emergency.senior.name if full_emergency.senior else "Care recipient"

    # 1. Push notification to the Senior
    notif_log_senior = NotificationLog(
        user_id=full_emergency.senior_id,
        title="Help is on the way!",
        body=f"{caregiver_name} accepted your SOS alert.",
        notification_type="EMERGENCY_ACCEPTED",
        data={"emergency_id": str(full_emergency.id), "caregiver_id": str(caregiver_id)},
    )
    db.add(notif_log_senior)

    await notification_service.send_push(
        db=db,
        user_ids=[full_emergency.senior_id],
        title="Help is on the way!",
        body=f"{caregiver_name} accepted your SOS alert.",
        data={
            "notification_type": "EMERGENCY_ACCEPTED",
            "emergency_id": str(full_emergency.id),
            "caregiver_id": str(caregiver_id),
        },
    )

    # 2. Push notification to other assigned caregivers/partners
    other_caregiver_ids = [
        asgn.caregiver_id
        for asgn in full_emergency.assignments
        if asgn.caregiver_id != caregiver_id
    ]
    if other_caregiver_ids:
        for cid in other_caregiver_ids:
            db.add(
                NotificationLog(
                    user_id=cid,
                    title="SOS Alert Responded",
                    body=f"{caregiver_name} accepted the SOS alert for {senior_name}.",
                    notification_type="EMERGENCY_ACCEPTED",
                    data={"emergency_id": str(full_emergency.id), "caregiver_id": str(caregiver_id)},
                )
            )

        await notification_service.send_push(
            db=db,
            user_ids=other_caregiver_ids,
            title="SOS Alert Responded",
            body=f"{caregiver_name} accepted the SOS alert for {senior_name}.",
            data={
                "notification_type": "EMERGENCY_ACCEPTED",
                "emergency_id": str(full_emergency.id),
                "caregiver_id": str(caregiver_id),
            },
        )

    await db.flush()

    # Broadcast live state update to RTDB and all SSE-connected clients.
    payload = {
        "emergency_id": str(full_emergency.id),
        "senior_id": str(full_emergency.senior_id),
        "senior_name": senior_name,
        "status": full_emergency.status.value,
        "emergency_type": full_emergency.emergency_type,
        "accepted_by": caregiver_name,
        "terminal": False,
        "updated_at": int(datetime.now(timezone.utc).timestamp()),
    }
    sync_emergency_to_rtdb(str(full_emergency.senior_id), payload)
    await _sse.broadcast(senior_id=full_emergency.senior_id, event=payload)
    return full_emergency


async def resolve_emergency(db: AsyncSession, emergency_id: UUID, user_id: UUID) -> Emergency:
    """Mark an emergency as RESOLVED."""
    res = await db.execute(select(Emergency).where(Emergency.id == emergency_id))
    emergency = res.scalar_one_or_none()
    if not emergency:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Emergency not found")

    emergency.status = EmergencyStatus.RESOLVED
    emergency.resolved_at = datetime.now(timezone.utc)

    event = EmergencyEvent(
        emergency_id=emergency.id,
        event_type="EMERGENCY_RESOLVED",
        actor_id=user_id,
    )
    db.add(event)
    await db.flush()

    full_res = await db.execute(
        select(Emergency)
        .options(
            selectinload(Emergency.senior),
            selectinload(Emergency.assignments).selectinload(EmergencyAssignment.caregiver),
        )
        .where(Emergency.id == emergency.id)
    )
    full_emergency = full_res.scalar_one()
    senior_name = full_emergency.senior.name if full_emergency.senior else "Care recipient"

    # Target recipients: Senior + all assigned caregivers (except person who resolved it)
    all_involved = {full_emergency.senior_id} | {
        asgn.caregiver_id for asgn in full_emergency.assignments
    }
    target_user_ids = [uid for uid in all_involved if uid != user_id]

    if target_user_ids:
        for uid in target_user_ids:
            db.add(
                NotificationLog(
                    user_id=uid,
                    title="Emergency Resolved",
                    body=f"The emergency alert for {senior_name} has been resolved.",
                    notification_type="EMERGENCY_RESOLVED",
                    data={"emergency_id": str(full_emergency.id), "resolved_by": str(user_id)},
                )
            )

        await notification_service.send_push(
            db=db,
            user_ids=target_user_ids,
            title="Emergency Resolved",
            body=f"The emergency alert for {senior_name} has been resolved.",
            data={
                "notification_type": "EMERGENCY_RESOLVED",
                "emergency_id": str(full_emergency.id),
                "resolved_by": str(user_id),
            },
        )

    await db.flush()

    payload = {
        "emergency_id": str(full_emergency.id),
        "senior_id": str(full_emergency.senior_id),
        "senior_name": senior_name,
        "status": "RESOLVED",
        "terminal": True,
        "updated_at": int(datetime.now(timezone.utc).timestamp()),
    }
    sync_emergency_to_rtdb(str(full_emergency.senior_id), payload)
    await _sse.broadcast(senior_id=full_emergency.senior_id, event=payload)
    return full_emergency


async def cancel_emergency(db: AsyncSession, emergency_id: UUID, senior_id: UUID) -> Emergency:
    """Cancel an emergency by senior."""
    res = await db.execute(select(Emergency).where(Emergency.id == emergency_id))
    emergency = res.scalar_one_or_none()
    if not emergency:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Emergency not found")

    emergency.status = EmergencyStatus.CANCELLED

    event = EmergencyEvent(
        emergency_id=emergency.id,
        event_type="EMERGENCY_CANCELLED",
        actor_id=senior_id,
    )
    db.add(event)
    await db.flush()

    full_res = await db.execute(
        select(Emergency)
        .options(
            selectinload(Emergency.senior),
            selectinload(Emergency.assignments).selectinload(EmergencyAssignment.caregiver),
        )
        .where(Emergency.id == emergency.id)
    )
    full_emergency = full_res.scalar_one()
    senior_name = full_emergency.senior.name if full_emergency.senior else "Care recipient"

    target_caregiver_ids = [asgn.caregiver_id for asgn in full_emergency.assignments]
    if target_caregiver_ids:
        for cid in target_caregiver_ids:
            db.add(
                NotificationLog(
                    user_id=cid,
                    title="Emergency Cancelled",
                    body=f"{senior_name} cancelled the emergency alert.",
                    notification_type="EMERGENCY_CANCELLED",
                    data={"emergency_id": str(full_emergency.id)},
                )
            )

        await notification_service.send_push(
            db=db,
            user_ids=target_caregiver_ids,
            title="Emergency Cancelled",
            body=f"{senior_name} cancelled the emergency alert.",
            data={
                "notification_type": "EMERGENCY_CANCELLED",
                "emergency_id": str(full_emergency.id),
            },
        )

    await db.flush()

    payload = {
        "emergency_id": str(full_emergency.id),
        "senior_id": str(full_emergency.senior_id),
        "senior_name": senior_name,
        "status": "CANCELLED",
        "terminal": True,
        "updated_at": int(datetime.now(timezone.utc).timestamp()),
    }
    sync_emergency_to_rtdb(str(full_emergency.senior_id), payload)
    await _sse.broadcast(senior_id=full_emergency.senior_id, event=payload)
    return full_emergency

