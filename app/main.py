"""
Senior Citizen Care — FastAPI Backend Entry Point

Initializes the FastAPI application, mounts API routers,
and configures CORS for Android client access.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.database import async_session_factory, engine
from app.core.firebase import get_firebase_app
from app.db.models import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup and initialize Firebase push backend."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    get_firebase_app()
    yield


app = FastAPI(
    title="Senior Citizen Care API",
    version="1.0.0",
    description="Backend API for the Senior Citizen Care & Assistance Network",
    lifespan=lifespan,
)

# CORS — allow Android emulator and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API v1 routes
app.include_router(api_v1_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "senior-citizen-care-api"}
