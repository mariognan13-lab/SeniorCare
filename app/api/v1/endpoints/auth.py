"""Authentication endpoints — login, register, Firebase token sync, and current user profile."""

from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.firebase_auth import verify_firebase_id_token
from app.core.security import create_access_token, decode_access_token
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, SyncUserRequest, UserResponse
from app.services import user_service

router = APIRouter()


async def get_current_user_from_token(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    token = authorization.split("Bearer ")[1].strip()

    # 1. Firebase ID token — what the Android client sends after Firebase sign-in.
    claims = await verify_firebase_id_token(token)
    if claims:
        user = await user_service.get_user_by_firebase_uid(db, claims["sub"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No account linked to this Firebase user. Call /auth/sync-user first.",
            )
        return UserResponse.model_validate(user)

    # 2. Backend-issued JWT — from /auth/login or /auth/register.
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        )

    try:
        user_id = UUID(payload["sub"])
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token subject")

    user = await user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return UserResponse.model_validate(user)


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await user_service.authenticate_user(db, req.email, req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = create_access_token(str(user.id), user.role.value)
    return AuthResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    user = await user_service.create_user(
        db,
        name=req.name,
        email=req.email,
        password=req.password,
        phone=req.phone,
        role=req.role,
    )
    token = create_access_token(str(user.id), user.role.value)
    return AuthResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/sync-user", response_model=AuthResponse)
async def sync_user(
    req: SyncUserRequest,
    db: AsyncSession = Depends(get_db),
):
    """Synchronize a Firebase authenticated user with the SQL users table."""
    user = await user_service.sync_firebase_user(
        db=db,
        firebase_uid=req.firebase_uid,
        email=req.email,
        name=req.name,
        phone=req.phone,
        role=req.role,
        fcm_token=req.fcm_token,
    )
    token = create_access_token(str(user.id), user.role.value)
    return AuthResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def me(current_user: UserResponse = Depends(get_current_user_from_token)):
    return current_user
