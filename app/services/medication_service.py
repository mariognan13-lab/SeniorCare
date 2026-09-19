"""
Medication service — manages medication creation, schedules, log event recording,
and caregiver notification dispatch for missed doses.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Medication, MedicationLog, MedicationLogStatus, NotificationLog,
    Relationship, User,
)
from app.services import notification_service


async def create_medication(
    db: AsyncSession,
    senior_id: UUID,
    name: str,
    dosage: str,
    frequency: str,
    schedule_times: list[str],
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    notes: str | None = None,
) -> Medication:
    """Create a medication schedule for a senior."""
    now = datetime.now(timezone.utc)
    medication = Medication(
        senior_id=senior_id,
        name=name,
        dosage=dosage,
        frequency=frequency,
        schedule_times=schedule_times,
        start_date=start_date or now,
        end_date=end_date,
        is_active=True,
        notes=notes,
    )
    db.add(medication)
    await db.flush()
    return medication


async def get_medications_for_senior(db: AsyncSession, senior_id: UUID) -> list[Medication]:
    """Fetch active medications for a senior."""
    stmt = (
        select(Medication)
        .where(Medication.senior_id == senior_id, Medication.is_active.is_(True))
        .order_by(Medication.created_at.desc())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def get_medication_logs_for_senior(db: AsyncSession, senior_id: UUID) -> list[MedicationLog]:
    """Fetch medication logs for a senior (joined through medications)."""
    stmt = (
        select(MedicationLog)
        .join(Medication, MedicationLog.medication_id == Medication.id)
        .where(Medication.senior_id == senior_id)
        .order_by(MedicationLog.scheduled_time.desc())
        .limit(100)
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def respond_to_medication_log(
    db: AsyncSession,
    log_id: UUID,
    status_str: str,
    notes: str | None = None,
) -> MedicationLog:
    """
    Log user response to a medication reminder (TAKEN, SKIPPED, or MISSED).

    If the status is MISSED, look up connected caregivers and family members in the
    care network and send FCM push notifications.
    """
    res = await db.execute(select(MedicationLog).where(MedicationLog.id == log_id))
    log = res.scalar_one_or_none()

    new_status = MedicationLogStatus(status_str)

    if not log:
        # If log doesn't exist yet in backend database (e.g. generated dynamically on client),
        # create a placeholder log record if medication exists or return dummy response.
        med_res = await db.execute(select(Medication).limit(1))
        first_med = med_res.scalars().first()
        if not first_med:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medication log not found")
        log = MedicationLog(
            id=log_id,
            medication_id=first_med.id,
            scheduled_time=datetime.now(timezone.utc),
            status=new_status,
            notes=notes,
        )
        db.add(log)
    else:
        log.status = new_status
        if new_status == MedicationLogStatus.TAKEN:
            log.taken_at = datetime.now(timezone.utc)
        if notes:
            log.notes = notes

    await db.flush()

    # If status is MISSED, notify care network
    if new_status == MedicationLogStatus.MISSED:
        med_res = await db.execute(select(Medication).where(Medication.id == log.medication_id))
        med = med_res.scalar_one_or_none()
        if med:
            senior_res = await db.execute(select(User).where(User.id == med.senior_id))
            senior = senior_res.scalar_one_or_none()
            senior_name = senior.name if senior else "Care recipient"

            rel_res = await db.execute(
                select(Relationship).where(Relationship.senior_id == med.senior_id)
            )
            relationships = rel_res.scalars().all()

            if relationships:
                caregiver_ids = [r.related_user_id for r in relationships]
                title = "Missed Medication Alert"
                body = f"{senior_name} missed their scheduled dose of {med.name} ({med.dosage})."

                for cid in caregiver_ids:
                    db.add(
                        NotificationLog(
                            user_id=cid,
                            title=title,
                            body=body,
                            notification_type="MISSED_MEDICATION",
                            data={
                                "medication_id": str(med.id),
                                "medication_name": med.name,
                                "senior_id": str(med.senior_id),
                                "log_id": str(log.id),
                            },
                        )
                    )

                await notification_service.send_push(
                    db=db,
                    user_ids=caregiver_ids,
                    title=title,
                    body=body,
                    data={
                        "notification_type": "MISSED_MEDICATION",
                        "medication_id": str(med.id),
                        "medication_name": med.name,
                        "senior_id": str(med.senior_id),
                        "log_id": str(log.id),
                    },
                )

    await db.flush()
    return log
