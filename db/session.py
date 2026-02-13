from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Protocol

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, create_async_engine

from bot.config import BotConfig


log = logging.getLogger("dmw.db")

SINGLETON_LOCK_KEY = 92837465


class AsyncConnectionContextFactory(Protocol):
    def __call__(self):
        ...


class SessionManager:
    def __init__(self, config: BotConfig):
        self._engine = create_async_engine(
            config.database_url,
            echo=config.db_echo,
            pool_pre_ping=True,
        )
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self._install_sql_logging()

    @property
    def engine(self):
        return self._engine

    def _install_sql_logging(self) -> None:
        @event.listens_for(self._engine.sync_engine, "before_cursor_execute")
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            context._query_started_at = time.perf_counter()
            log.debug("[to-db] SQL=%s params=%s", statement, parameters)

        @event.listens_for(self._engine.sync_engine, "after_cursor_execute")
        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            elapsed_ms = (time.perf_counter() - context._query_started_at) * 1000
            log.debug("[from-db] rows=%s took=%.2fms", cursor.rowcount, elapsed_ms)

        @event.listens_for(self._engine.sync_engine, "handle_error")
        def on_sqlalchemy_error(exception_context):
            log.exception("[from-db] query failed", exc_info=exception_context.original_exception)

    @asynccontextmanager
    async def session_scope(self) -> AsyncIterator[AsyncSession]:
        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def try_acquire_singleton_lock(self) -> bool:
        async with self._engine.begin() as conn:
            result = await conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": SINGLETON_LOCK_KEY})
            return bool(result.scalar())


async def try_acquire_singleton_lock_with_connection(connection: AsyncConnection) -> bool:
    result = await connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": SINGLETON_LOCK_KEY})
    return bool(result.scalar())
