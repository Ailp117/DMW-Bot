from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text
from models import Base
from config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    return SessionLocal()


async def ensure_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("DB schema ensured (create/migrate).")


# =============================
# Singleton Bot Lock (Prevents multiple instances)
# =============================

SINGLETON_LOCK_KEY = 92837465  # Keep constant


async def try_acquire_singleton_lock() -> bool:
    """
    Uses PostgreSQL advisory lock to ensure only one bot instance runs.
    If another instance already holds the lock, this returns False.
    """
    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": SINGLETON_LOCK_KEY},
        )
        return bool(result.scalar())
