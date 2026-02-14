from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import bot.runtime as runtime_mod
from bot.runtime import PLANNER_MESSAGE_CACHE_PREFIX, PLANNER_MESSAGE_KIND, RewriteDiscordBot
from services.raid_service import create_raid_from_modal
import views.raid_views as raid_views_mod


@pytest.mark.asyncio
async def test_refresh_planner_message_re_registers_view_for_existing_message(repo, monkeypatch):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    raid = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="14.02.2026",
        times_input="20:00",
        min_players_input="1",
        message_id=501,
    ).raid

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    add_view_calls: list[int] = []

    async def _fake_get_text_channel(_channel_id):
        return SimpleNamespace(id=11)

    async def _fake_fetch_message(_channel, _message_id):
        return SimpleNamespace(id=501)

    async def _fake_edit_message(_message, **_kwargs):
        return True

    class _DummyVoteView:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

    bot._get_text_channel = _fake_get_text_channel
    bot._planner_embed = lambda _raid: SimpleNamespace()
    bot.add_view = lambda _view, *, message_id: add_view_calls.append(int(message_id))
    monkeypatch.setattr(runtime_mod, "_safe_fetch_message", _fake_fetch_message)
    monkeypatch.setattr(runtime_mod, "_safe_edit_message", _fake_edit_message)
    monkeypatch.setattr(raid_views_mod, "RaidVoteView", _DummyVoteView)

    await RewriteDiscordBot._refresh_planner_message(bot, raid.id)

    assert add_view_calls == [501]
    assert int(repo.get_raid(raid.id).message_id or 0) == 501
    cached_rows = repo.list_debug_cache(kind=PLANNER_MESSAGE_KIND, guild_id=1, raid_id=raid.id)
    assert len(cached_rows) == 1
    assert cached_rows[0].cache_key == f"{PLANNER_MESSAGE_CACHE_PREFIX}:1:11:{raid.id}"
    assert int(cached_rows[0].message_id) == 501


@pytest.mark.asyncio
async def test_refresh_planner_message_updates_stored_message_id_on_id_drift(repo, monkeypatch):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    raid = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="14.02.2026",
        times_input="20:00",
        min_players_input="1",
        message_id=500,
    ).raid

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    add_view_calls: list[int] = []

    async def _fake_get_text_channel(_channel_id):
        return SimpleNamespace(id=11)

    async def _fake_fetch_message(_channel, _message_id):
        return SimpleNamespace(id=999)

    async def _fake_edit_message(_message, **_kwargs):
        return True

    class _DummyVoteView:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

    bot._get_text_channel = _fake_get_text_channel
    bot._planner_embed = lambda _raid: SimpleNamespace()
    bot.add_view = lambda _view, *, message_id: add_view_calls.append(int(message_id))
    monkeypatch.setattr(runtime_mod, "_safe_fetch_message", _fake_fetch_message)
    monkeypatch.setattr(runtime_mod, "_safe_edit_message", _fake_edit_message)
    monkeypatch.setattr(raid_views_mod, "RaidVoteView", _DummyVoteView)

    await RewriteDiscordBot._refresh_planner_message(bot, raid.id)

    assert add_view_calls == [999]
    assert int(repo.get_raid(raid.id).message_id or 0) == 999
    cached_rows = repo.list_debug_cache(kind=PLANNER_MESSAGE_KIND, guild_id=1, raid_id=raid.id)
    assert len(cached_rows) == 1
    assert int(cached_rows[0].message_id) == 999


@pytest.mark.asyncio
async def test_refresh_planner_message_uses_cached_message_when_raid_message_missing(repo, monkeypatch):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    raid = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="14.02.2026",
        times_input="20:00",
        min_players_input="1",
        message_id=0,
    ).raid
    repo.upsert_debug_cache(
        cache_key=f"{PLANNER_MESSAGE_CACHE_PREFIX}:1:11:{raid.id}",
        kind=PLANNER_MESSAGE_KIND,
        guild_id=1,
        raid_id=raid.id,
        message_id=777,
        payload_hash="hash",
    )

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    add_view_calls: list[int] = []

    async def _fake_get_text_channel(_channel_id):
        return SimpleNamespace(id=11)

    async def _fake_fetch_message(_channel, _message_id):
        if int(_message_id) == 777:
            return SimpleNamespace(id=777)
        return None

    async def _fake_edit_message(_message, **_kwargs):
        return True

    class _DummyVoteView:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

    bot._get_text_channel = _fake_get_text_channel
    bot._planner_embed = lambda _raid: SimpleNamespace()
    bot.add_view = lambda _view, *, message_id: add_view_calls.append(int(message_id))
    monkeypatch.setattr(runtime_mod, "_safe_fetch_message", _fake_fetch_message)
    monkeypatch.setattr(runtime_mod, "_safe_edit_message", _fake_edit_message)
    monkeypatch.setattr(raid_views_mod, "RaidVoteView", _DummyVoteView)

    await RewriteDiscordBot._refresh_planner_message(bot, raid.id)

    assert add_view_calls == [777]
    assert int(repo.get_raid(raid.id).message_id or 0) == 777


def test_restore_persistent_vote_views_uses_cached_planner_message_id(repo, monkeypatch):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    raid = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="14.02.2026",
        times_input="20:00",
        min_players_input="1",
        message_id=0,
    ).raid
    repo.upsert_debug_cache(
        cache_key=f"{PLANNER_MESSAGE_CACHE_PREFIX}:1:11:{raid.id}",
        kind=PLANNER_MESSAGE_KIND,
        guild_id=1,
        raid_id=raid.id,
        message_id=888,
        payload_hash="hash",
    )

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    add_view_calls: list[int] = []
    bot.add_view = lambda _view, *, message_id: add_view_calls.append(int(message_id))

    class _DummyVoteView:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

    monkeypatch.setattr(raid_views_mod, "RaidVoteView", _DummyVoteView)

    RewriteDiscordBot._restore_persistent_vote_views(bot)

    assert add_view_calls == [888]
    assert int(repo.get_raid(raid.id).message_id or 0) == 888


@pytest.mark.asyncio
async def test_finish_raid_interaction_clears_planner_message_cache(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    raid = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="14.02.2026",
        times_input="20:00",
        min_players_input="1",
        message_id=501,
    ).raid
    cache_key = f"{PLANNER_MESSAGE_CACHE_PREFIX}:1:11:{raid.id}"
    repo.upsert_debug_cache(
        cache_key=cache_key,
        kind=PLANNER_MESSAGE_KIND,
        guild_id=1,
        raid_id=raid.id,
        message_id=501,
        payload_hash="hash",
    )

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._state_lock = asyncio.Lock()
    bot._cleanup_temp_role = lambda _raid: asyncio.sleep(0)
    bot._delete_slot_message = lambda _row: asyncio.sleep(0)
    bot._close_planner_message = lambda **_kwargs: asyncio.sleep(0)
    bot._force_raidlist_refresh = lambda _guild_id: asyncio.sleep(0)
    bot._force_raid_calendar_refresh = lambda _guild_id: asyncio.sleep(0)
    bot._persist = lambda: asyncio.sleep(0, result=True)
    bot._reply = lambda *_args, **_kwargs: asyncio.sleep(0)

    interaction = SimpleNamespace(user=SimpleNamespace(id=100))
    await RewriteDiscordBot._finish_raid_interaction(bot, interaction, raid_id=raid.id, deferred=False)

    assert repo.get_debug_cache(cache_key) is None


@pytest.mark.asyncio
async def test_cancel_raids_for_guild_clears_planner_message_cache(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    raid = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="14.02.2026",
        times_input="20:00",
        min_players_input="1",
        message_id=502,
    ).raid
    cache_key = f"{PLANNER_MESSAGE_CACHE_PREFIX}:1:11:{raid.id}"
    repo.upsert_debug_cache(
        cache_key=cache_key,
        kind=PLANNER_MESSAGE_KIND,
        guild_id=1,
        raid_id=raid.id,
        message_id=502,
        payload_hash="hash",
    )

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._close_planner_message = lambda **_kwargs: asyncio.sleep(0)
    bot._cleanup_temp_role = lambda _raid: asyncio.sleep(0)
    bot._delete_slot_message = lambda _row: asyncio.sleep(0)
    bot._force_raidlist_refresh = lambda _guild_id: asyncio.sleep(0)
    bot._force_raid_calendar_refresh = lambda _guild_id: asyncio.sleep(0)

    cancelled = await RewriteDiscordBot._cancel_raids_for_guild(bot, 1, reason="remote-abgebrochen")

    assert cancelled == 1
    assert repo.get_debug_cache(cache_key) is None
