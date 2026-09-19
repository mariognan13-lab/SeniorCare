"""
Async SQLAlchemy engine and session factory for database connection with SQLite fallback.
"""

import logging
import socket
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_effective_db_url() -> str:
    db_url = settings.DATABASE_URL
    if "postgresql" in db_url:
        try:
            # Quick probe to see if local PostgreSQL port is reachable
            h = "localhost"
            p = 5432
            if "@" in db_url:
                host_port = db_url.split("@")[-1].split("/")[0]
                if ":" in host_port:
                    h, p_str = host_port.split(":")
                    p = int(p_str)
                else:
                    h = host_port
            with socket.create_connection((h, p), timeout=0.8):
                pass
        except Exception:
            logger.warning(
                "PostgreSQL server not reachable at %s. Falling back to SQLite (sqlite+aiosqlite:///./scc.db)",
                db_url,
            )
            return "sqlite+aiosqlite:///./scc.db"
    return db_url


effective_url = get_effective_db_url()
engine = create_async_engine(
    effective_url,
    echo=settings.DEBUG,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields a database session per request."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
