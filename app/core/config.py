"""
Application configuration loaded from environment variables.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database — defaults to local SQLite db (scc.db)
    DATABASE_URL: str = "sqlite+aiosqlite:///./scc.db"

    # JWT
    JWT_SECRET_KEY: str = "dev-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 1440  # 24 hours

    # Assignment
    ASSIGNMENT_TIMEOUT_SECONDS: int = 120  # 2 minutes for demo

    # Firebase (Batch 2)
    FIREBASE_CREDENTIALS_PATH: str = ""
    FIREBASE_CREDENTIALS_JSON: str = ""
    FIREBASE_DATABASE_URL: str = "https://yarin-dc220-default-rtdb.asia-southeast1.firebasedatabase.app/"
    # Project ID used to verify Firebase ID tokens presented by the Android client.
    # Must match google-services.json -> project_info.project_id.
    FIREBASE_PROJECT_ID: str = "yarin-dc220"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
