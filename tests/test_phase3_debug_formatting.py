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
async def test_refresh_raidlist_debug_payload_uses_runtime_guild_name(repo):
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
    captured: dict[str, str] = {}

    async def _fake_get_text_channel(_channel_id):
        return SimpleNamespace(id=33)

    async def _fake_send_channel_message(_channel, **_kwargs):
        return SimpleNamespace(id=555)

    async def _fake_mirror_debug_payload(**kwargs):
        captured["content"] = str(kwargs.get("content", ""))

    bot._get_text_channel = _fake_get_text_channel
    bot._send_channel_message = _fake_send_channel_message
    bot._mirror_debug_payload = _fake_mirror_debug_payload

    changed = await RewriteDiscordBot._refresh_raidlist_for_guild(bot, 1, force=True)

    assert changed is True
    assert "Guild: Alpha Guild" in captured["content"]
    assert "Guild `1`" not in captured["content"]
