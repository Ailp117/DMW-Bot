from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from bot.main import BotApplication
from services.startup_service import SingletonGate


@pytest.mark.asyncio
async def test_singleton_lock_gate(config, repo, monkeypatch):
    gate = SingletonGate()
    app_one = BotApplication(config=config, repo=repo, singleton_gate=gate)
    app_two = BotApplication(config=config, repo=repo, singleton_gate=gate)

    monkeypatch.setattr(app_one, "_start_background_loops", lambda: None)
    monkeypatch.setattr(app_two, "_start_background_loops", lambda: None)

    await app_one.setup()
    with pytest.raises(SystemExit):
        await app_two.setup()


@pytest.mark.asyncio
async def test_boot_smoke_check_required_tables(app):
    with pytest.raises(RuntimeError, match="Missing required DB tables"):
        app.run_boot_smoke_checks(existing_tables=["guild_settings", "raids"])


@pytest.mark.asyncio
async def test_background_loops_singleton(config, repo, monkeypatch):
    app = BotApplication(config=config, repo=repo)

    async def long_worker(_name: str):
        await asyncio.sleep(60)

    monkeypatch.setattr(app, "_background_worker", long_worker)

    app._start_background_loops()
    first_tasks = {name: app.task_registry.get(name) for name in app.task_registry._tasks}

    app._start_background_loops()
    second_tasks = {name: app.task_registry.get(name) for name in app.task_registry._tasks}

    assert set(first_tasks.keys()) == set(second_tasks.keys())
    for name in first_tasks:
        assert first_tasks[name] is second_tasks[name]

    await app.close()


@pytest.mark.asyncio
async def test_run_self_tests_updates_state(app):
    await app.run_self_tests_once()
    assert app.self_test_state.last_ok_at is not None
    assert app.self_test_state.last_error is None


@pytest.mark.asyncio
async def test_cleanup_stale_raids_only(app, repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )

    old_raid = repo.create_raid(
        guild_id=1,
        planner_channel_id=11,
        creator_id=10,
        dungeon="Nanos",
        min_players=1,
    )
    old_raid.created_at = datetime(2020, 1, 1)

    recent_raid = repo.create_raid(
        guild_id=1,
        planner_channel_id=11,
        creator_id=11,
        dungeon="Skull",
        min_players=1,
    )

    cleaned, guilds = await app.cleanup_stale_raids_once(now=datetime(2026, 2, 13))

    assert cleaned == 1
    assert guilds == [1]
    assert repo.get_raid(old_raid.id) is None
    assert repo.get_raid(recent_raid.id) is not None
