"""SOS endpoints — trigger, accept, resolve, and cancel emergency alerts."""

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import get_current_user_from_token
from app.core.database import get_db
from app.schemas.auth import UserResponse
from app.schemas.sos import SOSActionResponse, SOSResponse, SOSTriggerRequest
from app.services import sos_service

router = APIRouter()


@router.post("/trigger", response_model=SOSResponse, status_code=status.HTTP_201_CREATED)
async def trigger_sos(
    req: SOSTriggerRequest,
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Trigger an emergency SOS alert."""
    emergency = await sos_service.trigger_sos(
        db=db,
        senior_id=current_user.id,
        emergency_type=req.emergency_type,
        description=req.description,
        priority=req.priority,
        latitude=req.latitude,
        longitude=req.longitude,
    )
    return SOSResponse.model_validate(emergency)


@router.get("/active", response_model=SOSResponse | None)
async def get_active_sos(
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Get active emergency for current user or connected senior."""
    emergency = await sos_service.get_active_emergency_for_user(db, current_user.id)
    if not emergency:
        return None
    return SOSResponse.model_validate(emergency)


@router.post("/{emergency_id}/accept", response_model=SOSActionResponse)
async def accept_sos(
    emergency_id: UUID,
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Caregiver or partner accepts an emergency response."""
    emergency = await sos_service.accept_emergency(db, emergency_id, current_user.id)
    return SOSActionResponse(
        success=True,
        message="Emergency accepted successfully.",
        emergency=SOSResponse.model_validate(emergency),
    )


@router.post("/{emergency_id}/resolve", response_model=SOSActionResponse)
async def resolve_sos(
    emergency_id: UUID,
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Mark emergency as RESOLVED."""
    emergency = await sos_service.resolve_emergency(db, emergency_id, current_user.id)
    return SOSActionResponse(
        success=True,
        message="Emergency resolved.",
        emergency=SOSResponse.model_validate(emergency),
    )


@router.post("/{emergency_id}/cancel", response_model=SOSActionResponse)
async def cancel_sos(
    emergency_id: UUID,
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Cancel active emergency."""
    emergency = await sos_service.cancel_emergency(db, emergency_id, current_user.id)
    return SOSActionResponse(
        success=True,
        message="Emergency cancelled.",
        emergency=SOSResponse.model_validate(emergency),
    )
