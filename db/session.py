from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, time as datetime_time
from typing import Any, AsyncIterator, Protocol

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, create_async_engine

from bot.config import BotConfig


log = logging.getLogger("dmw.db")

SINGLETON_LOCK_KEY = 92837465
MAX_REDACT_COLLECTION_ITEMS = 20


def _redact_sql_scalar(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, bool):
        return "<bool>"
    if isinstance(value, int):
        return "<int>"
    if isinstance(value, float):
        return "<float>"
    if isinstance(value, (str, bytes, bytearray, memoryview)):
        return "<redacted>"
    if isinstance(value, datetime):
        return "<datetime>"
    if isinstance(value, date):
        return "<date>"
    if isinstance(value, datetime_time):
        return "<time>"
    return f"<{value.__class__.__name__}>"


def _redact_sql_parameters(parameters: object, *, _depth: int = 0) -> object:
    if _depth >= 4:
        return "<max-depth>"

    if isinstance(parameters, dict):
        out: dict[str, object] = {}
        total = len(parameters)
        for index, (key, value) in enumerate(parameters.items()):
            if index >= MAX_REDACT_COLLECTION_ITEMS:
                out["..."] = f"+{total - MAX_REDACT_COLLECTION_ITEMS} more"
                break
            out[str(key)] = _redact_sql_parameters(value, _depth=_depth + 1)
        return out

    if isinstance(parameters, tuple):
        total = len(parameters)
        redacted = [
            _redact_sql_parameters(value, _depth=_depth + 1)
            for value in parameters[:MAX_REDACT_COLLECTION_ITEMS]
        ]
        if total > MAX_REDACT_COLLECTION_ITEMS:
            redacted.append(f"... +{total - MAX_REDACT_COLLECTION_ITEMS} more")
        return tuple(redacted)

    if isinstance(parameters, list):
        total = len(parameters)
        redacted = [
            _redact_sql_parameters(value, _depth=_depth + 1)
            for value in parameters[:MAX_REDACT_COLLECTION_ITEMS]
        ]
        if total > MAX_REDACT_COLLECTION_ITEMS:
            redacted.append(f"... +{total - MAX_REDACT_COLLECTION_ITEMS} more")
        return redacted

    if isinstance(parameters, (set, frozenset)):
        values = list(parameters)
        total = len(values)
        redacted = [
            _redact_sql_parameters(value, _depth=_depth + 1)
            for value in values[:MAX_REDACT_COLLECTION_ITEMS]
        ]
        if total > MAX_REDACT_COLLECTION_ITEMS:
            redacted.append(f"... +{total - MAX_REDACT_COLLECTION_ITEMS} more")
        return redacted

    return _redact_sql_scalar(parameters)


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
        def _sql_debug_enabled() -> bool:
            return log.isEnabledFor(logging.DEBUG)

        @event.listens_for(self._engine.sync_engine, "before_cursor_execute")
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            if not _sql_debug_enabled():
                return
            context._query_started_at = time.perf_counter()
            log.debug("[to-db] SQL=%s params=%s", statement, _redact_sql_parameters(parameters))

        @event.listens_for(self._engine.sync_engine, "after_cursor_execute")
        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            if not _sql_debug_enabled():
                return
            started_at = getattr(context, "_query_started_at", None)
            if isinstance(started_at, (int, float)):
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                log.debug("[from-db] rows=%s took=%.2fms", cursor.rowcount, elapsed_ms)
            else:
                log.debug("[from-db] rows=%s", cursor.rowcount)

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
