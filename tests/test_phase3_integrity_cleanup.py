from __future__ import annotations

import pytest

from bot.runtime import (
    PLANNER_MESSAGE_KIND,
    RAID_REMINDER_KIND,
    SLOT_TEMP_ROLE_KIND,
    RewriteDiscordBot,
)
from services.raid_service import create_raid_from_modal


@pytest.mark.asyncio
async def test_integrity_cleanup_removes_orphan_debug_cache_rows(repo):
    repo.ensure_settings(1, "Guild")
    repo.upsert_debug_cache(
        cache_key="raidrem:999:abc",
        kind=RAID_REMINDER_KIND,
        guild_id=1,
        raid_id=999,
        message_id=777,
        payload_hash="hash",
    )
    repo.upsert_debug_cache(
        cache_key="slotrole:999:abc",
        kind=SLOT_TEMP_ROLE_KIND,
        guild_id=1,
        raid_id=999,
        message_id=888,
        payload_hash="hash",
    )
    repo.upsert_debug_cache(
        cache_key="plannermsg:1:11:999",
        kind=PLANNER_MESSAGE_KIND,
        guild_id=1,
        raid_id=999,
        message_id=889,
        payload_hash="hash",
    )

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._safe_get_guild = lambda _guild_id: None

    removed_count = await RewriteDiscordBot._run_integrity_cleanup_once(bot)

    assert removed_count == 3
    assert repo.get_debug_cache("raidrem:999:abc") is None
    assert repo.get_debug_cache("slotrole:999:abc") is None
    assert repo.get_debug_cache("plannermsg:1:11:999") is None


@pytest.mark.asyncio
async def test_integrity_cleanup_keeps_rows_for_open_raid(repo):
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
        days_input="13.02.2026",
        times_input="20:00",
        min_players_input="1",
        message_id=5151,
    ).raid

    repo.upsert_debug_cache(
        cache_key="raidrem:1:abc",
        kind=RAID_REMINDER_KIND,
        guild_id=1,
        raid_id=raid.id,
        message_id=777,
        payload_hash="hash",
    )
    repo.upsert_debug_cache(
        cache_key="slotrole:1:abc",
        kind=SLOT_TEMP_ROLE_KIND,
        guild_id=1,
        raid_id=raid.id,
        message_id=888,
        payload_hash="hash",
    )
    repo.upsert_debug_cache(
        cache_key=f"plannermsg:1:11:{raid.id}",
        kind=PLANNER_MESSAGE_KIND,
        guild_id=1,
        raid_id=raid.id,
        message_id=889,
        payload_hash="hash",
    )

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._safe_get_guild = lambda _guild_id: None

    removed_count = await RewriteDiscordBot._run_integrity_cleanup_once(bot)

    assert removed_count == 0
    assert repo.get_debug_cache("raidrem:1:abc") is not None
    assert repo.get_debug_cache("slotrole:1:abc") is not None
    assert repo.get_debug_cache(f"plannermsg:1:11:{raid.id}") is not None
