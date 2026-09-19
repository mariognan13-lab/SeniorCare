"""
Device service — handles FCM device token registration and user_devices updates.
"""

from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserDevice


async def register_user_device(
    db: AsyncSession,
    user_id: UUID,
    fcm_token: str,
    device_type: str = "android",
    device_name: str | None = None,
) -> UserDevice:
    """Register or update device FCM token for user."""
    # Also update user's primary fcm_token
    res_user = await db.execute(select(User).where(User.id == user_id))
    user = res_user.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # A token names a *device*, and a device is signed in as exactly one person at
    # a time. The unique constraint below is on (user_id, fcm_token) — so without
    # this, signing in as someone else on the same phone would add a second row
    # for the new user and leave the previous user's row still pointing at this
    # handset. The push fan-out reads those rows, so the previous account's
    # emergency alerts would be delivered to whoever is holding the phone now.
    #
    # Deleting rather than reassigning: the old row is not stale data to keep, it
    # is an address that no longer belongs to its owner.
    await db.execute(
        delete(UserDevice).where(
            UserDevice.fcm_token == fcm_token,
            UserDevice.user_id != user_id,
        )
    )
    # The same address is recorded on `users.fcm_token`. Nothing reads it today —
    # `send_push` goes through `user_devices` — but leaving a second copy pointing
    # at a device that has changed hands is a trap for whoever reads it first.
    await db.execute(
        update(User)
        .where(User.fcm_token == fcm_token, User.id != user_id)
        .values(fcm_token=None)
    )

    user.fcm_token = fcm_token

    # Upsert user_devices table entry
    res = await db.execute(
        select(UserDevice).where(
            UserDevice.user_id == user_id,
            UserDevice.fcm_token == fcm_token,
        )
    )
    device = res.scalar_one_or_none()

    if not device:
        device = UserDevice(
            user_id=user_id,
            fcm_token=fcm_token,
            device_type=device_type,
            device_name=device_name,
        )
        db.add(device)
    else:
        device.device_type = device_type
        if device_name:
            device.device_name = device_name

    await db.flush()
    return device
