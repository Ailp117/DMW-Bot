from __future__ import annotations

from bot.runtime import RewriteDiscordBot


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


def test_build_discord_log_embed_returns_none_for_unstructured_line(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo

    embed = RewriteDiscordBot._build_discord_log_embed(bot, "plain fallback message")

    assert embed is None
