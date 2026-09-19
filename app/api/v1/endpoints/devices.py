"""Device endpoints — FCM device token registration."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import get_current_user_from_token
from app.core.database import get_db
from app.schemas.auth import UserResponse
from app.schemas.device import DeviceResponse, RegisterDeviceRequest
from app.services import device_service

router = APIRouter()


@router.post("/register", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def register_device(
    req: RegisterDeviceRequest,
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Register or update device FCM token for current authenticated user."""
    device = await device_service.register_user_device(
        db=db,
        user_id=current_user.id,
        fcm_token=req.fcm_token,
        device_type=req.device_type,
        device_name=req.device_name,
    )
    return DeviceResponse.model_validate(device)
