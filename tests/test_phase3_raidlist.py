from __future__ import annotations

import asyncio

import pytest

from bot.runtime import RewriteDiscordBot
from discord.task_registry import DebouncedGuildUpdater
from services.raid_service import create_raid_from_modal
from services.raidlist_service import render_raidlist


def test_raidlist_render_contains_open_raids(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="Mon",
        times_input="20:00",
        min_players_input="2",
        message_id=5400,
    )

    render = render_raidlist(1, "Guild", repo.list_open_raids(1))
    assert "Nanos" in render.body
    assert "🆔 `1`" in render.body
    assert "https://discord.com/channels/1/11/5400" in render.body


@pytest.mark.asyncio
async def test_raidlist_updater_debounces_and_forces():
    calls: list[int] = []

    async def update(guild_id: int) -> None:
        calls.append(guild_id)

    updater = DebouncedGuildUpdater(update, debounce_seconds=0.01, cooldown_seconds=0.0)

    await updater.mark_dirty(1)
    await updater.mark_dirty(1)
    await updater.mark_dirty(1)

    await asyncio.sleep(0.05)
    assert calls == [1]

    await updater.force_update(1)
    assert calls == [1, 1]


@pytest.mark.asyncio
async def test_debounced_raidlist_refresh_persists_state():
    bot = object.__new__(RewriteDiscordBot)
    bot._state_lock = asyncio.Lock()
    calls: list[tuple] = []

    async def fake_refresh(guild_id: int, *, force: bool = False):
        calls.append(("refresh", guild_id, force))
        return True

    async def fake_persist():
        calls.append(("persist",))
        return True

    bot._refresh_raidlist_for_guild = fake_refresh
    bot._persist = fake_persist

    await RewriteDiscordBot._refresh_raidlist_for_guild_persisted(bot, 77)

    assert calls == [("refresh", 77, False), ("persist",)]


@pytest.mark.asyncio
async def test_force_raidlist_refresh_calls_direct_refresh():
    bot = object.__new__(RewriteDiscordBot)
    calls: list[tuple] = []

    class DummyUpdater:
        async def force_update(self, guild_id: int):
            raise AssertionError("force_update should not be called in direct force refresh path")

    async def fake_refresh(guild_id: int, *, force: bool = False):
        calls.append(("refresh", guild_id, force))
        return True

    bot.raidlist_updater = DummyUpdater()
    bot._refresh_raidlist_for_guild = fake_refresh

    await RewriteDiscordBot._force_raidlist_refresh(bot, 88)

    assert calls == [("refresh", 88, True)]
