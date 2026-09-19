"""API v1 router — aggregates all endpoint routers."""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, devices, medications, relationships, sos, users

api_v1_router = APIRouter()

api_v1_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_v1_router.include_router(users.router, prefix="/users", tags=["Users"])
api_v1_router.include_router(devices.router, prefix="/devices", tags=["Devices"])
api_v1_router.include_router(relationships.router, prefix="/relationships", tags=["Relationships"])
api_v1_router.include_router(sos.router, prefix="/sos", tags=["Emergency SOS"])
api_v1_router.include_router(medications.router, prefix="/medications", tags=["Medications"])
