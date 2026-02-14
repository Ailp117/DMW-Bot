from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from bot.runtime import RewriteDiscordBot
from features.runtime_mixins import logging_background as logging_background_mod


def test_build_discord_log_embed_parses_structured_log_line(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo

    embed = RewriteDiscordBot._build_discord_log_embed(
        bot,
        "[2026-02-13 12:00:00] ERROR src=dmw.runtime/runtime.test_fn:42 | Something bad happened",
    )

    assert embed is not None
    assert "ERROR" in (embed.title or "")
    assert "Something bad happened" in (embed.description or "")
    assert any((field.name or "") == "Quelle" for field in embed.fields)
    assert any((field.name or "") == "Zeit" for field in embed.fields)


def test_build_discord_log_embed_unifies_unstructured_line(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo

    embed = RewriteDiscordBot._build_discord_log_embed(bot, "plain fallback message")

    assert embed is not None
    assert "plain fallback message" in (embed.description or "")
    assert any((field.name or "") == "Quelle" for field in embed.fields)


def test_should_forward_log_record_filters_noise(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo

    debug_record = logging.LogRecord(
        name="dmw.runtime",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=1,
        msg="debug msg",
        args=(),
        exc_info=None,
    )
    db_info_record = logging.LogRecord(
        name="dmw.db",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="db info",
        args=(),
        exc_info=None,
    )
    info_record = logging.LogRecord(
        name="dmw.runtime",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Rewrite bot ready as TestBot#0001",
        args=(),
        exc_info=None,
    )
    warning_record = logging.LogRecord(
        name="dmw.runtime",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Something odd happened",
        args=(),
        exc_info=None,
    )
    command_record = logging.LogRecord(
        name="dmw.runtime",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Command executed: command=/status user=Sebas (1234) guild=Alpha guild_id=42",
        args=(),
        exc_info=None,
    )

    assert RewriteDiscordBot._should_forward_log_record(bot, debug_record) is False
    assert RewriteDiscordBot._should_forward_log_record(bot, db_info_record) is False
    assert RewriteDiscordBot._should_forward_log_record(bot, info_record) is True
    assert RewriteDiscordBot._should_forward_log_record(bot, warning_record) is True
    assert RewriteDiscordBot._should_forward_log_record(bot, command_record) is True


def test_build_discord_log_embed_adds_guild_label(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    repo.ensure_settings(42, "Alpha Guild")
    bot._safe_get_guild = lambda _guild_id: None

    embed = RewriteDiscordBot._build_discord_log_embed(
        bot,
        "[2026-02-13 12:00:00] WARNING src=dmw.runtime/runtime.test_fn:42 | guild_id=42 stale cleanup",
    )

    assert embed is not None
    assert "Alpha Guild (42)" in (embed.description or "")
    assert any((field.name or "") == "Server" for field in embed.fields)


@pytest.mark.asyncio
async def test_resolve_log_channel_uses_fetch_fallback(repo, monkeypatch):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot.config = SimpleNamespace(log_guild_id=1, log_channel_id=22)

    class _FakeTextChannel:
        def __init__(self, channel_id: int, guild) -> None:
            self.id = channel_id
            self.guild = guild

    monkeypatch.setattr(logging_background_mod.discord, "TextChannel", _FakeTextChannel)

    guild = SimpleNamespace(id=1, get_channel=lambda _channel_id: None)
    bot.get_guild = lambda _guild_id: guild

    async def _fetch_channel(channel_id: int):
        return _FakeTextChannel(channel_id, guild)

    bot.fetch_channel = _fetch_channel

    channel = await RewriteDiscordBot._resolve_log_channel(bot)

    assert isinstance(channel, _FakeTextChannel)
    assert int(channel.id) == 22
