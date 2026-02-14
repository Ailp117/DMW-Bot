from __future__ import annotations

from types import SimpleNamespace

import pytest

import bot.runtime as runtime_mod
from bot.runtime import RewriteDiscordBot


@pytest.mark.asyncio
async def test_runtime_persist_returns_true_when_flush_succeeds():
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = object()
    calls = {"flush": 0}

    async def _flush(_repo, *, dirty_tables=None):
        calls["flush"] += 1
        assert dirty_tables is None

    async def _load(_repo):
        raise AssertionError("load must not be called on successful flush")

    bot.persistence = SimpleNamespace(flush=_flush, load=_load)

    persisted = await RewriteDiscordBot._persist(bot)

    assert persisted is True
    assert calls["flush"] == 1


@pytest.mark.asyncio
async def test_runtime_persist_forwards_dirty_table_hints():
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = object()
    seen: list[set[str] | None] = []

    async def _flush(_repo, *, dirty_tables=None):
        if dirty_tables is None:
            seen.append(None)
        else:
            seen.append(set(dirty_tables))

    async def _load(_repo):
        raise AssertionError("load must not be called")

    bot.persistence = SimpleNamespace(flush=_flush, load=_load)

    persisted = await RewriteDiscordBot._persist(bot, dirty_tables={"user_levels"})

    assert persisted is True
    assert seen == [{"user_levels"}]


@pytest.mark.asyncio
async def test_runtime_persist_retries_and_does_not_reload_on_flush_failure(monkeypatch):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = object()
    calls = {"flush": 0, "load": 0}
    sleeps: list[float] = []

    async def _flush(_repo, *, dirty_tables=None):
        calls["flush"] += 1
        raise RuntimeError("db write failure")

    async def _load(_repo):
        calls["load"] += 1

    async def _fake_sleep(seconds: float):
        sleeps.append(float(seconds))

    monkeypatch.setattr(runtime_mod, "PERSIST_FLUSH_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(runtime_mod, "PERSIST_FLUSH_RETRY_BASE_SECONDS", 0.01)
    monkeypatch.setattr(runtime_mod.asyncio, "sleep", _fake_sleep)

    bot.persistence = SimpleNamespace(flush=_flush, load=_load)

    persisted = await RewriteDiscordBot._persist(bot)

    assert persisted is False
    assert calls["flush"] == 3
    assert sleeps == [0.01, 0.02]
    assert calls["load"] == 0
