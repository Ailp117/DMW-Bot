from __future__ import annotations

from types import SimpleNamespace

import pytest

import bot.runtime as runtime_mod
from bot.runtime import RewriteDiscordBot
from services.raid_service import create_raid_from_modal, toggle_vote


@pytest.mark.asyncio
async def test_restore_runtime_messages_uses_recreate_mode():
    bot = object.__new__(RewriteDiscordBot)

    raid = SimpleNamespace(id=99)
    bot.repo = SimpleNamespace(list_open_raids=lambda: [raid])

    calls: list[tuple[str, object]] = []

    async def _fake_refresh_planner(raid_id: int):
        calls.append(("planner", raid_id))

    async def _fake_sync_memberlists(raid_id: int, *, recreate_existing: bool = False):
        calls.append(("memberlist", raid_id, recreate_existing))
        return (0, 0, 0)

    async def _fake_refresh_raidlists(*, force: bool):
        calls.append(("raidlists", force))

    async def _fake_persist(*, dirty_tables=None):
        calls.append(("persist", dirty_tables))
        return True

    bot._refresh_planner_message = _fake_refresh_planner
    bot._sync_memberlist_messages_for_raid = _fake_sync_memberlists
    bot._refresh_raidlists_for_all_guilds = _fake_refresh_raidlists
    bot._persist = _fake_persist

    await RewriteDiscordBot._restore_runtime_messages(bot)

    assert ("planner", 99) in calls
    assert ("memberlist", 99, True) in calls
    assert ("raidlists", True) in calls
    assert ("persist", None) in calls


@pytest.mark.asyncio
async def test_sync_memberlists_recreate_replaces_old_message(repo, monkeypatch):
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
        days_input="Mon",
        times_input="20:00",
        min_players_input="1",
        message_id=5200,
    ).raid

    toggle_vote(repo, raid_id=raid.id, kind="day", option_label="Mon", user_id=200)
    toggle_vote(repo, raid_id=raid.id, kind="time", option_label="20:00", user_id=200)
    repo.upsert_posted_slot(raid_id=raid.id, day_label="Mon", time_label="20:00", channel_id=22, message_id=501)

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot.config = SimpleNamespace(memberlist_debug_channel_id=0)

    participants_channel = SimpleNamespace(id=22)
    old_msg = SimpleNamespace(id=501)
    new_msg = SimpleNamespace(id=777)
    deleted_ids: list[int] = []
    edit_calls = 0

    async def _fake_get_text_channel(_channel_id):
        return participants_channel

    async def _fake_ensure_temp_role(_raid):
        return None

    async def _fake_ensure_slot_temp_role(_raid, *, day_label: str, time_label: str):
        return None

    async def _fake_sync_slot_role_members(_raid, *, role, user_ids):
        return None

    async def _fake_mirror_debug_payload(**_kwargs):
        return None

    async def _fake_fetch_message(_channel, _message_id):
        return old_msg

    async def _fake_edit_message(*_args, **_kwargs):
        nonlocal edit_calls
        edit_calls += 1
        return True

    async def _fake_send_channel_message(_channel, **_kwargs):
        return new_msg

    async def _fake_delete_message(message):
        deleted_ids.append(int(getattr(message, "id", 0)))
        return True

    bot._get_text_channel = _fake_get_text_channel
    bot._ensure_temp_role = _fake_ensure_temp_role
    bot._ensure_slot_temp_role = _fake_ensure_slot_temp_role
    bot._sync_slot_role_members = _fake_sync_slot_role_members
    bot._mirror_debug_payload = _fake_mirror_debug_payload
    monkeypatch.setattr(runtime_mod, "_safe_fetch_message", _fake_fetch_message)
    monkeypatch.setattr(runtime_mod, "_safe_edit_message", _fake_edit_message)
    monkeypatch.setattr(runtime_mod, "_safe_send_channel_message", _fake_send_channel_message)
    monkeypatch.setattr(runtime_mod, "_safe_delete_message", _fake_delete_message)

    created, updated, deleted = await RewriteDiscordBot._sync_memberlist_messages_for_raid(
        bot,
        raid.id,
        recreate_existing=True,
    )

    assert created == 0
    assert updated == 1
    assert deleted == 0
    assert edit_calls == 0
    assert deleted_ids == [501]
    slot_row = repo.list_posted_slots(raid.id)[("Mon", "20:00")]
    assert slot_row.message_id == 777
