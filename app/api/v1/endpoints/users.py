"""Users endpoints — user search and profile lookup."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import get_current_user_from_token
from app.core.database import get_db
from app.db.models import User
from app.schemas.auth import UserResponse
from app.schemas.user import UpdateFcmTokenRequest, UserSearchResult
from app.services import user_service

router = APIRouter()


@router.get("/search", response_model=list[UserSearchResult])
async def search_users(
    query: str = Query(..., min_length=2, description="Search by name, email, or phone"),
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Find someone to connect with, by name, email or phone.

    Returns name and role only. The search itself still matches on email and
    phone — if you already know someone's address you can confirm you have the
    right person — but the *results* do not echo contact details back. Those
    arrive once a connection is accepted and the care network can show them.

    Previously this returned the full UserResponse, which handed every signed-in
    account the name, email and phone number of every user in the system.
    """
    q_str = f"%{query.strip()}%"
    stmt = (
        select(User)
        .where(
            User.id != current_user.id,
            or_(
                User.email.ilike(q_str),
                User.name.ilike(q_str),
                User.phone.ilike(q_str),
            ),
        )
        .limit(20)
    )
    res = await db.execute(stmt)
    users = res.scalars().all()
    return [UserSearchResult.model_validate(u) for u in users]


@router.post("/fcm-token")
async def update_fcm_token(
    req: UpdateFcmTokenRequest,
    current_user: UserResponse = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Update FCM token for current user."""
    await user_service.update_fcm_token(db, current_user.id, req.fcm_token)
    return {"message": "FCM token updated successfully"}
