from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text

from config import DATABASE_URL, DB_ECHO

engine = create_async_engine(
    DATABASE_URL,
    echo=DB_ECHO,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncSession:
    return SessionLocal()


SINGLETON_LOCK_KEY = 92837465  # beliebig aber konstant


async def try_acquire_singleton_lock() -> bool:
    """
    Verhindert, dass 2 Bot-Instanzen gleichzeitig laufen (causes 40060 errors).
    """
    async with engine.begin() as conn:
        res = await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": SINGLETON_LOCK_KEY})
        return bool(res.scalar())
