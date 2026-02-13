from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bot.runtime import (
    GuildFeatureSettings,
    RewriteDiscordBot,
    _extract_slash_command_name,
    _round_xp_for_display,
)


@pytest.mark.parametrize(
    "content,expected",
    [
        ("/status", "status"),
        (" /raidplan nanos", "raidplan"),
        ("/HELP2", "help2"),
        ("hello", None),
        ("/", None),
    ],
)
def test_extract_slash_command_name(content: str, expected: str | None):
    assert _extract_slash_command_name(content) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, 0),
        (12, 12),
        (12.4, 12),
        (12.5, 13),
        ("9.6", 10),
        (None, 0),
        (float("inf"), 0),
        (-3.2, 0),
    ],
)
def test_round_xp_for_display(value, expected: int):
    assert _round_xp_for_display(value) == expected


@pytest.mark.asyncio
async def test_on_message_skips_xp_for_registered_command():
    bot = object.__new__(RewriteDiscordBot)
    bot.log_channel = None
    bot._slash_command_names = {"status", "raidplan"}
    bot._state_lock = asyncio.Lock()
    bot._level_state_dirty = False
    bot.repo = object()

    called = {"xp": 0}

    def _update_message_xp(*_args, **_kwargs):
        called["xp"] += 1
        return SimpleNamespace(previous_level=0, current_level=0, xp=0, xp_awarded=False)

    bot.leveling_service = SimpleNamespace(
        update_message_xp=_update_message_xp,
        should_announce_levelup=lambda **_kwargs: False,
    )
    bot._get_guild_feature_settings = lambda _guild_id: GuildFeatureSettings(
        leveling_enabled=True,
        levelup_messages_enabled=True,
        nanomon_reply_enabled=False,
        approved_reply_enabled=False,
        message_xp_interval_seconds=15,
        levelup_message_cooldown_seconds=20,
    )

    async def _fake_send_channel_message(*_args, **_kwargs):
        raise AssertionError("level-up message must not be sent")

    bot._send_channel_message = _fake_send_channel_message

    async def _fake_reply(*_args, **_kwargs):
        raise AssertionError("keyword reply must not run")

    message = SimpleNamespace(
        author=SimpleNamespace(bot=False, id=42, mention="<@42>"),
        guild=SimpleNamespace(id=1),
        channel=SimpleNamespace(id=10),
        content="/status",
        reply=_fake_reply,
    )

    await RewriteDiscordBot.on_message(bot, message)

    assert called["xp"] == 0
    assert bot._level_state_dirty is False


@pytest.mark.asyncio
async def test_on_message_awards_xp_for_normal_text():
    bot = object.__new__(RewriteDiscordBot)
    bot.log_channel = None
    bot._slash_command_names = {"status", "raidplan"}
    bot._state_lock = asyncio.Lock()
    bot._level_state_dirty = False
    bot.repo = object()

    called = {"xp": 0}

    def _update_message_xp(*_args, **_kwargs):
        called["xp"] += 1
        return SimpleNamespace(previous_level=0, current_level=0, xp=10, xp_awarded=True)

    bot.leveling_service = SimpleNamespace(
        update_message_xp=_update_message_xp,
        should_announce_levelup=lambda **_kwargs: False,
    )
    bot._get_guild_feature_settings = lambda _guild_id: GuildFeatureSettings(
        leveling_enabled=True,
        levelup_messages_enabled=True,
        nanomon_reply_enabled=False,
        approved_reply_enabled=False,
        message_xp_interval_seconds=15,
        levelup_message_cooldown_seconds=20,
    )

    async def _fake_send_channel_message(*_args, **_kwargs):
        raise AssertionError("level-up message must not be sent")

    bot._send_channel_message = _fake_send_channel_message

    async def _fake_reply(*_args, **_kwargs):
        raise AssertionError("keyword reply must not run")

    message = SimpleNamespace(
        author=SimpleNamespace(bot=False, id=42, mention="<@42>"),
        guild=SimpleNamespace(id=1),
        channel=SimpleNamespace(id=10),
        content="normal chat text",
        reply=_fake_reply,
    )

    await RewriteDiscordBot.on_message(bot, message)

    assert called["xp"] == 1
    assert bot._level_state_dirty is True


@pytest.mark.asyncio
async def test_on_message_levelup_message_uses_rounded_xp_display():
    bot = object.__new__(RewriteDiscordBot)
    bot.log_channel = None
    bot._slash_command_names = {"status", "raidplan"}
    bot._state_lock = asyncio.Lock()
    bot._level_state_dirty = False
    bot.repo = object()

    called = {"xp": 0}
    sent = {"content": ""}

    def _update_message_xp(*_args, **_kwargs):
        called["xp"] += 1
        return SimpleNamespace(previous_level=1, current_level=2, xp=12.5, xp_awarded=True)

    bot.leveling_service = SimpleNamespace(
        update_message_xp=_update_message_xp,
        should_announce_levelup=lambda **_kwargs: True,
    )
    bot._get_guild_feature_settings = lambda _guild_id: GuildFeatureSettings(
        leveling_enabled=True,
        levelup_messages_enabled=True,
        nanomon_reply_enabled=False,
        approved_reply_enabled=False,
        message_xp_interval_seconds=15,
        levelup_message_cooldown_seconds=20,
    )

    async def _fake_send_channel_message(*_args, **_kwargs):
        sent["content"] = str(_kwargs.get("content", ""))
        return None

    bot._send_channel_message = _fake_send_channel_message

    async def _fake_reply(*_args, **_kwargs):
        raise AssertionError("keyword reply must not run")

    message = SimpleNamespace(
        author=SimpleNamespace(bot=False, id=42, mention="<@42>"),
        guild=SimpleNamespace(id=1),
        channel=SimpleNamespace(id=10),
        content="normal chat text",
        reply=_fake_reply,
    )

    await RewriteDiscordBot.on_message(bot, message)

    assert called["xp"] == 1
    assert "(XP: 13)" in sent["content"]
