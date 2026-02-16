from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from bot.runtime import GuildFeatureSettings, RewriteDiscordBot
from services.raid_service import create_raid_from_modal, toggle_vote


def _enabled_feature_settings() -> GuildFeatureSettings:
    return GuildFeatureSettings(
        leveling_enabled=True,
        levelup_messages_enabled=True,
        nanomon_reply_enabled=True,
        approved_reply_enabled=True,
        raid_reminder_enabled=True,
        message_xp_interval_seconds=15,
        levelup_message_cooldown_seconds=20,
    )


def test_parse_slot_start_at_utc_parses_iso_date_and_time():
    parsed = RewriteDiscordBot._parse_slot_start_at_utc("2026-02-13 (Fr)", "20:15")
    assert parsed == datetime(2026, 2, 13, 19, 15, tzinfo=UTC)


def test_parse_slot_start_at_utc_respects_timezone():
    parsed = RewriteDiscordBot._parse_slot_start_at_utc(
        "2026-02-13 (Fr)",
        "20:15",
        timezone_name="Europe/Berlin",
    )
    assert parsed == datetime(2026, 2, 13, 19, 15, tzinfo=UTC)


@pytest.mark.asyncio
async def test_run_raid_reminders_once_sends_only_once_per_slot(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    now = datetime(2026, 2, 13, 18, 50, tzinfo=UTC)
    day_label = "2026-02-13 (Fr)"
    time_label = "20:00"

    raid = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input=day_label,
        times_input=time_label,
        min_players_input="1",
        message_id=5151,
    ).raid
    toggle_vote(repo, raid_id=raid.id, kind="day", option_label=day_label, user_id=200)
    toggle_vote(repo, raid_id=raid.id, kind="time", option_label=time_label, user_id=200)

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._get_guild_feature_settings = lambda _guild_id: _enabled_feature_settings()

    participants_channel = SimpleNamespace(id=22)
    sent_messages: list[str] = []

    async def _fake_get_text_channel(_channel_id):
        return participants_channel

    async def _fake_ensure_slot_temp_role(_raid, *, day_label: str, time_label: str):
        return SimpleNamespace(mention=f"<@&{day_label}:{time_label}>", members=[])

    async def _fake_sync_slot_role_members(_raid, *, role, user_ids):
        return None

    async def _fake_send_channel_message(_channel, **kwargs):
        sent_messages.append(str(kwargs.get("content", "")))
        return SimpleNamespace(id=7000 + len(sent_messages))

    bot._get_text_channel = _fake_get_text_channel
    bot._ensure_slot_temp_role = _fake_ensure_slot_temp_role
    bot._sync_slot_role_members = _fake_sync_slot_role_members
    bot._send_channel_message = _fake_send_channel_message

    first = await RewriteDiscordBot._run_raid_reminders_once(bot, now_utc=now)
    second = await RewriteDiscordBot._run_raid_reminders_once(bot, now_utc=now)

    assert first == 1
    assert second == 0
    assert len(sent_messages) == 1
    cache_key = RewriteDiscordBot._raid_reminder_cache_key(raid.id, day_label, time_label)
    cache_row = repo.get_debug_cache(cache_key)
    assert cache_row is not None


@pytest.mark.asyncio
async def test_run_raid_reminders_once_uses_default_timezone(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    now_utc = datetime(2026, 2, 13, 18, 50, tzinfo=UTC)
    day_label = "2026-02-13 (Fr)"
    time_label = "20:00"

    raid = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input=day_label,
        times_input=time_label,
        min_players_input="1",
        message_id=5153,
    ).raid
    toggle_vote(repo, raid_id=raid.id, kind="day", option_label=day_label, user_id=200)
    toggle_vote(repo, raid_id=raid.id, kind="time", option_label=time_label, user_id=200)

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._get_guild_feature_settings = lambda _guild_id: _enabled_feature_settings()

    participants_channel = SimpleNamespace(id=22)
    sent_messages: list[str] = []

    async def _fake_get_text_channel(_channel_id):
        return participants_channel

    async def _fake_ensure_slot_temp_role(_raid, *, day_label: str, time_label: str):
        return SimpleNamespace(mention=f"<@&{day_label}:{time_label}>", members=[])

    async def _fake_sync_slot_role_members(_raid, *, role, user_ids):
        return None

    async def _fake_send_channel_message(_channel, **kwargs):
        sent_messages.append(str(kwargs.get("content", "")))
        return SimpleNamespace(id=7100 + len(sent_messages))

    bot._get_text_channel = _fake_get_text_channel
    bot._ensure_slot_temp_role = _fake_ensure_slot_temp_role
    bot._sync_slot_role_members = _fake_sync_slot_role_members
    bot._send_channel_message = _fake_send_channel_message

    sent = await RewriteDiscordBot._run_raid_reminders_once(bot, now_utc=now_utc)

    assert sent == 1
    assert len(sent_messages) == 1
    assert "(Europe/Berlin)" in sent_messages[0]


@pytest.mark.asyncio
async def test_sync_memberlists_uses_unique_slot_roles_per_slot(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    day_one = "2026-02-13 (Fr)"
    day_two = "2026-02-14 (Sa)"
    time_label = "20:00"

    raid = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input=f"{day_one}, {day_two}",
        times_input=time_label,
        min_players_input="1",
        message_id=5152,
    ).raid
    toggle_vote(repo, raid_id=raid.id, kind="day", option_label=day_one, user_id=200)
    toggle_vote(repo, raid_id=raid.id, kind="time", option_label=time_label, user_id=200)
    toggle_vote(repo, raid_id=raid.id, kind="day", option_label=day_two, user_id=201)
    toggle_vote(repo, raid_id=raid.id, kind="time", option_label=time_label, user_id=201)

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot.config = SimpleNamespace(memberlist_debug_channel_id=0)
    participants_channel = SimpleNamespace(id=22)
    ensured_slots: list[tuple[str, str]] = []
    sent_payloads: list[str] = []
    sent_embeds: list[object] = []

    async def _fake_get_text_channel(_channel_id):
        return participants_channel

    async def _fake_ensure_slot_temp_role(_raid, *, day_label: str, time_label: str):
        ensured_slots.append((day_label, time_label))
        return SimpleNamespace(mention=f"<@&{day_label}-{time_label}>", members=[])

    async def _fake_sync_slot_role_members(_raid, *, role, user_ids):
        return None

    async def _fake_send_channel_message(_channel, **kwargs):
        sent_payloads.append(str(kwargs.get("content", "")))
        sent_embeds.append(kwargs.get("embed"))
        return SimpleNamespace(id=8000 + len(sent_payloads))

    async def _fake_mirror_debug_payload(**_kwargs):
        return None

    bot._get_text_channel = _fake_get_text_channel
    bot._ensure_slot_temp_role = _fake_ensure_slot_temp_role
    bot._sync_slot_role_members = _fake_sync_slot_role_members
    bot._send_channel_message = _fake_send_channel_message
    bot._mirror_debug_payload = _fake_mirror_debug_payload

    created, updated, deleted = await RewriteDiscordBot._sync_memberlist_messages_for_raid(bot, raid.id)

    assert created == 2
    assert updated == 0
    assert deleted == 0
    assert set(ensured_slots) == {(day_one, time_label), (day_two, time_label)}
    # Role wird nicht mehr bei der Memberliste gepingt (nur beim Raid Reminder)
    assert all(f"<@&{day_one}-{time_label}>" not in (payload or "") for payload in sent_payloads)
    assert all(f"<@&{day_two}-{time_label}>" not in (payload or "") for payload in sent_payloads)
    assert all(embed is not None for embed in sent_embeds)
