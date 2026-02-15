from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.runtime import RewriteDiscordBot
from services.raid_service import create_raid_from_modal, toggle_vote


def test_build_raidlist_embed_contains_structured_raid_data(repo):
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
        days_input="2026-02-13 (Fr)",
        times_input="20:00",
        min_players_input="1",
        message_id=5151,
    ).raid
    toggle_vote(repo, raid_id=raid.id, kind="day", option_label="2026-02-13 (Fr)", user_id=200)
    toggle_vote(repo, raid_id=raid.id, kind="time", option_label="20:00", user_id=200)

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo

    embed, payload_hash, debug_lines = RewriteDiscordBot._build_raidlist_embed(
        bot,
        guild_id=1,
        guild_name="Guild",
        raids=repo.list_open_raids(1),
    )

    assert embed is not None
    assert "Raidlist" in (embed.title or "")
    assert len(embed.fields) >= 3  # Overview + Raid + Statistics
    # Find raid field
    raid_field = next((f for f in embed.fields if "Raid #1" in f.name), None)
    assert raid_field is not None
    assert "Zeitzone `Europe/Berlin`" in (raid_field.value or "")
    assert "https://discord.com/channels/1/11/5151" in (raid_field.value or "")
    assert payload_hash
    assert any("Raid 1" in line for line in debug_lines)


@pytest.mark.asyncio
async def test_refresh_raidlist_for_guild_posts_embed(repo):
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
        days_input="2026-02-13 (Fr)",
        times_input="20:00",
        min_players_input="1",
        message_id=5151,
    )

    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._raidlist_hash_by_guild = {}
    bot.config = SimpleNamespace(raidlist_debug_channel_id=0)
    bot.get_guild = lambda _guild_id: SimpleNamespace(name="Guild")

    sent_kwargs: dict[str, object] = {}

    async def _fake_get_text_channel(_channel_id):
        return SimpleNamespace(id=33)

    async def _fake_send_channel_message(_channel, **kwargs):
        sent_kwargs.update(kwargs)
        return SimpleNamespace(id=888)

    async def _fake_mirror_debug_payload(**_kwargs):
        return None

    bot._get_text_channel = _fake_get_text_channel
    bot._send_channel_message = _fake_send_channel_message
    bot._mirror_debug_payload = _fake_mirror_debug_payload

    changed = await RewriteDiscordBot._refresh_raidlist_for_guild(bot, 1, force=True)

    assert changed is True
    assert sent_kwargs.get("embed") is not None
    assert sent_kwargs.get("content") is None
    assert repo.ensure_settings(1).raidlist_message_id == 888
