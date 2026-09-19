"""
User service — handles user creation, lookup, and profile updates.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.db.models import CaregiverProfile, User, UserRole


async def create_user(
    db: AsyncSession,
    name: str,
    email: str,
    password: str,
    phone: str | None,
    role: str,
) -> User:
    """Register a new user. Creates a caregiver_profile automatically for CAREGIVER role."""

    # Check duplicate email
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )

    user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
        phone=phone,
        role=UserRole(role),
    )
    db.add(user)
    await db.flush()  # Get the user ID before creating profile

    # Auto-create caregiver profile
    if user.role == UserRole.CAREGIVER:
        profile = CaregiverProfile(user_id=user.id)
        db.add(profile)

    await db.flush()
    return user


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str,
) -> User | None:
    """Verify credentials. Returns the user or None."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    # password_hash is NULL for accounts created via Firebase sync, which have
    # no local password. Treat those as "no match" rather than raising.
    if user and user.password_hash and verify_password(password, user.password_hash):
        return user
    return None


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_firebase_uid(db: AsyncSession, firebase_uid: str) -> User | None:
    result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    return result.scalar_one_or_none()


async def update_fcm_token(db: AsyncSession, user_id: UUID, fcm_token: str) -> None:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.fcm_token = fcm_token
    await db.flush()


async def sync_firebase_user(
    db: AsyncSession,
    firebase_uid: str,
    email: str,
    name: str = "User",
    phone: str | None = None,
    role: str = "SENIOR",
    fcm_token: str | None = None,
) -> User:
    """Synchronize Firebase authenticated user with SQL users table."""
    # 1. Lookup by firebase_uid
    res = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    user = res.scalar_one_or_none()

    # 2. If not found by firebase_uid, lookup by email
    if not user:
        res_email = await db.execute(select(User).where(User.email == email))
        user = res_email.scalar_one_or_none()
        if user:
            user.firebase_uid = firebase_uid

    # 3. Create new user if still not found
    if not user:
        valid_role = UserRole.SENIOR
        try:
            valid_role = UserRole(role)
        except ValueError:
            pass

        user = User(
            firebase_uid=firebase_uid,
            name=name,
            email=email,
            phone=phone,
            role=valid_role,
            fcm_token=fcm_token,
        )
        db.add(user)
        await db.flush()

        if user.role == UserRole.CAREGIVER:
            profile = CaregiverProfile(user_id=user.id)
            db.add(profile)
    else:
        if fcm_token:
            user.fcm_token = fcm_token
        if name and user.name == "User":
            user.name = name

    await db.flush()
    return user

