from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from bot.runtime import RewriteDiscordBot
from services.raid_service import create_raid_from_modal


def test_build_raid_calendar_embed_contains_grid_and_raid_entries(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="GuildOne",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="2026-03-04 (Mi)\n2026-03-10 (Di)",
        times_input="20:00",
        min_players_input="1",
        message_id=5151,
    )

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo

    embed, payload_hash, debug_lines = RewriteDiscordBot._build_raid_calendar_embed(
        bot,
        guild_id=1,
        guild_name="GuildOne",
        month_start=date(2026, 3, 1),
    )

    assert "Raid Kalender" in (embed.title or "")
    assert "Maerz 2026" in (embed.title or "")
    assert payload_hash
    assert any("2026-03-04" in line for line in debug_lines)

    grid_field = next((field for field in embed.fields if field.name == "Monatsansicht"), None)
    assert grid_field is not None
    assert "2026-03-04" not in (grid_field.value or "")
    assert "01" in (grid_field.value or "")
    assert "04+" in (grid_field.value or "")

    details_field = next((field for field in embed.fields if field.name == "Raid Termine"), None)
    assert details_field is not None
    assert "2026-03-04" in (details_field.value or "")
    assert "#1 Nanos" in (details_field.value or "")


def test_build_raid_calendar_embed_uses_ansi_colors(repo, monkeypatch):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="GuildOne",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="2026-03-04 (Mi)\n2026-03-10 (Di)",
        times_input="20:00",
        min_players_input="1",
        message_id=5151,
    )

    import features.runtime_mixins.state_calendar as state_calendar_mod

    monkeypatch.setattr(state_calendar_mod, "_berlin_now", lambda: datetime(2026, 3, 4, 12, 0, 0))

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo

    embed, _payload_hash, _debug_lines = RewriteDiscordBot._build_raid_calendar_embed(
        bot,
        guild_id=1,
        guild_name="GuildOne",
        month_start=date(2026, 3, 1),
    )

    grid_field = next((field for field in embed.fields if field.name == "Monatsansicht"), None)
    assert grid_field is not None
    grid_value = grid_field.value or ""
    assert grid_value.startswith("```ansi")
    assert "\u001b[0;31m" in grid_value
    assert "\u001b[0;33m" in grid_value
    assert "\u001b[0;37m" in grid_value


@pytest.mark.asyncio
async def test_refresh_raid_calendar_posts_embed_and_stores_message_state(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="GuildOne",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="2026-03-04 (Mi)",
        times_input="20:00",
        min_players_input="1",
        message_id=5151,
    )

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._raid_calendar_hash_by_guild = {}
    bot._raid_calendar_month_key_by_guild = {}
    bot.get_guild = lambda _guild_id: SimpleNamespace(id=1, name="GuildOne")

    sent_payload: dict[str, object] = {}

    async def _fake_get_text_channel(_channel_id):
        return SimpleNamespace(id=777)

    async def _fake_send_channel_message(_channel, **kwargs):
        sent_payload.update(kwargs)
        return SimpleNamespace(id=999)

    bot._get_text_channel = _fake_get_text_channel
    bot._send_channel_message = _fake_send_channel_message

    RewriteDiscordBot._set_raid_calendar_channel_id(bot, 1, 777)
    changed = await RewriteDiscordBot._refresh_raid_calendar_for_guild(
        bot,
        1,
        force=True,
        month_start=date(2026, 3, 1),
    )

    assert changed is True
    assert sent_payload.get("embed") is not None
    assert sent_payload.get("view") is not None

    state = repo.get_debug_cache(RewriteDiscordBot._raid_calendar_message_cache_key(1))
    assert state is not None
    assert state.kind == "raid_calendar_msg"
    assert state.message_id == 999
    assert state.raid_id == 202603


def test_indexed_bot_message_ids_include_calendar_message(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._raid_calendar_hash_by_guild = {}
    bot._raid_calendar_month_key_by_guild = {}

    RewriteDiscordBot._set_raid_calendar_channel_id(bot, 1, 777)
    repo.upsert_debug_cache(
        cache_key=RewriteDiscordBot._raid_calendar_message_cache_key(1),
        kind="raid_calendar_msg",
        guild_id=1,
        raid_id=202603,
        message_id=4242,
        payload_hash="hash",
    )

    indexed = RewriteDiscordBot._indexed_bot_message_ids_for_channel(bot, guild_id=1, channel_id=777)
    assert 4242 in indexed


def test_clear_known_message_refs_clears_calendar_state(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._raid_calendar_hash_by_guild = {1: "old"}
    bot._raid_calendar_month_key_by_guild = {1: 202603}

    repo.upsert_debug_cache(
        cache_key=RewriteDiscordBot._raid_calendar_message_cache_key(1),
        kind="raid_calendar_msg",
        guild_id=1,
        raid_id=202603,
        message_id=4242,
        payload_hash="hash",
    )

    RewriteDiscordBot._clear_known_message_refs_for_id(bot, guild_id=1, channel_id=777, message_id=4242)

    assert repo.get_debug_cache(RewriteDiscordBot._raid_calendar_message_cache_key(1)) is None
    assert 1 not in bot._raid_calendar_hash_by_guild
    assert 1 not in bot._raid_calendar_month_key_by_guild


@pytest.mark.asyncio
async def test_rebuild_raid_calendar_message_deletes_old_message_and_reposts(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._raid_calendar_hash_by_guild = {}
    bot._raid_calendar_month_key_by_guild = {}

    RewriteDiscordBot._set_raid_calendar_channel_id(bot, 1, 777)
    repo.upsert_debug_cache(
        cache_key=RewriteDiscordBot._raid_calendar_message_cache_key(1),
        kind="raid_calendar_msg",
        guild_id=1,
        raid_id=202603,
        message_id=999,
        payload_hash="old",
    )

    deleted_calls: list[tuple[int, int, int | None]] = []
    refresh_calls: list[tuple[int, bool, object]] = []

    async def _fake_delete(guild_id: int, message_id: int, *, preferred_channel_id: int | None = None):
        deleted_calls.append((guild_id, message_id, preferred_channel_id))
        return True

    async def _fake_refresh(guild_id: int, *, force: bool = False, month_start=None):
        refresh_calls.append((guild_id, force, month_start))
        return True

    bot._delete_raid_calendar_message_by_id = _fake_delete
    bot._refresh_raid_calendar_for_guild = _fake_refresh

    rebuilt = await RewriteDiscordBot._rebuild_raid_calendar_message_for_guild(bot, 1)

    assert rebuilt is True
    assert deleted_calls == [(1, 999, 777)]
    assert refresh_calls
    assert refresh_calls[0][0] == 1
    assert refresh_calls[0][1] is True
