"""Medications endpoints — schedule creation, logs lookup, and response logging."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import get_current_user_from_token
from app.core.database import get_db
from app.schemas.auth import UserResponse
from app.schemas.medication import (
    CreateMedicationRequest,
    MedicationLogResponse,
    MedicationResponse,
    RespondMedicationLogRequest,
)
from app.services import medication_service

router = APIRouter()


@router.post("", response_model=MedicationResponse, status_code=status.HTTP_201_CREATED)
async def create_medication(
    req: CreateMedicationRequest,
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Create a medication schedule for a senior care recipient."""
    senior_id = req.senior_id or current_user.id
    med = await medication_service.create_medication(
        db=db,
        senior_id=senior_id,
        name=req.name,
        dosage=req.dosage,
        frequency=req.frequency,
        schedule_times=req.schedule_times,
        start_date=req.start_date,
        end_date=req.end_date,
        notes=req.notes,
    )
    return MedicationResponse.model_validate(med)


@router.get("/senior/{senior_id}", response_model=list[MedicationResponse])
async def get_medications_for_senior(
    senior_id: UUID,
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Get active medication schedules for a senior."""
    meds = await medication_service.get_medications_for_senior(db, senior_id)
    return [MedicationResponse.model_validate(m) for m in meds]


@router.get("/logs/senior/{senior_id}", response_model=list[MedicationLogResponse])
async def get_medication_logs_for_senior(
    senior_id: UUID,
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Get medication logs for a senior."""
    logs = await medication_service.get_medication_logs_for_senior(db, senior_id)
    result = []
    for l in logs:
        med_name = l.medication.name if hasattr(l, "medication") and l.medication else "Medication"
        result.append(
            MedicationLogResponse(
                id=l.id,
                medication_id=l.medication_id,
                medication_name=med_name,
                scheduled_time=l.scheduled_time,
                taken_at=l.taken_at,
                status=l.status.value,
                notes=l.notes,
                created_at=l.created_at,
            )
        )
    return result


@router.post("/logs/{log_id}/respond", response_model=MedicationLogResponse)
async def respond_to_medication_log(
    log_id: UUID,
    req: RespondMedicationLogRequest,
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Log response for a medication reminder (TAKEN, SKIPPED, or MISSED)."""
    log = await medication_service.respond_to_medication_log(
        db=db,
        log_id=log_id,
        status_str=req.status,
        notes=req.notes,
    )
    med_name = log.medication.name if hasattr(log, "medication") and log.medication else "Medication"
    return MedicationLogResponse(
        id=log.id,
        medication_id=log.medication_id,
        medication_name=med_name,
        scheduled_time=log.scheduled_time,
        taken_at=log.taken_at,
        status=log.status.value,
        notes=log.notes,
        created_at=log.created_at,
    )
