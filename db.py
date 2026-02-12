from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import event, text

from config import DATABASE_URL, DB_ECHO

log = logging.getLogger("dmw-raid-bot.database")

engine = create_async_engine(
    DATABASE_URL,
    echo=DB_ECHO,
    pool_pre_ping=True,
)


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._query_started_at = time.perf_counter()
    log.debug("[to-db] SQL=%s | params=%s", statement, parameters)


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    elapsed_ms = (time.perf_counter() - context._query_started_at) * 1000
    log.debug("[from-db] rows=%s | took=%.2fms", cursor.rowcount, elapsed_ms)


@event.listens_for(engine.sync_engine, "handle_error")
def _on_sqlalchemy_error(exception_context):
    log.exception("[from-db] query failed", exc_info=exception_context.original_exception)

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
