from __future__ import annotations

from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text

from config import DATABASE_URL, DB_ECHO

engine = create_async_engine(
    DATABASE_URL,
    echo=DB_ECHO,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

@asynccontextmanager
async def session_scope() -> AsyncSession:
    session = SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


SINGLETON_LOCK_KEY = 92837465

async def try_acquire_singleton_lock() -> bool:
    """
    Prevents multiple bot instances from responding to the same interaction (40060).
    Holds a Postgres advisory lock for the lifetime of a DB connection.
    """
    async with engine.begin() as conn:
        res = await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": SINGLETON_LOCK_KEY})
        return bool(res.scalar())
