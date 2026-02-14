from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.runtime import RewriteDiscordBot


def test_format_debug_report_uses_guild_name_from_settings(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    repo.ensure_settings(1, "Stored Guild Name")
    bot._safe_get_guild = lambda _guild_id: None

    payload = RewriteDiscordBot._format_debug_report(
        bot,
        topic="Raidlist Debug",
        guild_id=1,
        summary=["Title: Raidlist"],
        lines=["- no raids"],
    )

    assert "[Raidlist Debug]" in payload
    assert "Guild: Stored Guild Name" in payload
    assert "Guild `1`" not in payload


@pytest.mark.asyncio
async def test_refresh_raidlist_does_not_emit_debug_payload(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._raidlist_hash_by_guild = {}
    bot.get_guild = lambda _guild_id: SimpleNamespace(name="Alpha Guild")
    bot.config = SimpleNamespace(raidlist_debug_channel_id=999)

    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    mirror_calls = 0

    async def _fake_get_text_channel(_channel_id):
        return SimpleNamespace(id=33)

    async def _fake_send_channel_message(_channel, **_kwargs):
        return SimpleNamespace(id=555)

    async def _fake_mirror_debug_payload(**_kwargs):
        nonlocal mirror_calls
        mirror_calls += 1

    bot._get_text_channel = _fake_get_text_channel
    bot._send_channel_message = _fake_send_channel_message
    bot._mirror_debug_payload = _fake_mirror_debug_payload

    changed = await RewriteDiscordBot._refresh_raidlist_for_guild(bot, 1, force=True)

    assert changed is True
    assert mirror_calls == 0


@pytest.mark.asyncio
async def test_sync_memberlist_does_not_emit_debug_payload(repo):
    from services.raid_service import create_raid_from_modal, toggle_vote

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
    toggle_vote(repo, raid_id=raid.id, kind="day", option_label="13.02.2026", user_id=200)
    toggle_vote(repo, raid_id=raid.id, kind="time", option_label="20:00", user_id=200)

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot.config = SimpleNamespace(memberlist_debug_channel_id=999)
    mirror_calls = 0

    async def _fake_get_text_channel(_channel_id):
        return SimpleNamespace(id=22)

    async def _fake_ensure_slot_temp_role(_raid, *, day_label: str, time_label: str):
        return None

    async def _fake_sync_slot_role_members(_raid, *, role, user_ids):
        return None

    async def _fake_send_channel_message(_channel, **_kwargs):
        return SimpleNamespace(id=6000)

    async def _fake_mirror_debug_payload(**_kwargs):
        nonlocal mirror_calls
        mirror_calls += 1

    bot._get_text_channel = _fake_get_text_channel
    bot._ensure_slot_temp_role = _fake_ensure_slot_temp_role
    bot._sync_slot_role_members = _fake_sync_slot_role_members
    bot._send_channel_message = _fake_send_channel_message
    bot._mirror_debug_payload = _fake_mirror_debug_payload

    created, updated, deleted = await RewriteDiscordBot._sync_memberlist_messages_for_raid(bot, raid.id)

    assert (created, updated, deleted) == (1, 0, 0)
    assert mirror_calls == 0
