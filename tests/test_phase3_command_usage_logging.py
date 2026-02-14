from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.discord_api import discord
from bot.runtime import RewriteDiscordBot
from features.runtime_mixins import events as runtime_events_mod


def test_interaction_command_path_supports_subcommands(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo

    interaction = SimpleNamespace(
        command=None,
        data={
            "name": "raid",
            "options": [
                {
                    "type": 1,
                    "name": "create",
                    "options": [
                        {"type": 1, "name": "fast"},
                    ],
                }
            ],
        },
    )

    command_path = RewriteDiscordBot._interaction_command_path(interaction)

    assert command_path == "raid create fast"


def test_interaction_command_path_handles_invalid_option_type(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo

    interaction = SimpleNamespace(
        command=None,
        data={
            "name": "raid",
            "options": [
                {
                    "type": "invalid",
                    "name": "create",
                }
            ],
        },
    )

    command_path = RewriteDiscordBot._interaction_command_path(interaction)

    assert command_path == "raid"


def test_format_command_usage_log_contains_command_user_and_server(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    repo.ensure_settings(77, "Stored Guild")
    bot._safe_get_guild = lambda _guild_id: None

    interaction = SimpleNamespace(
        command=SimpleNamespace(qualified_name="raidplan"),
        data={"name": "raidplan"},
        user=SimpleNamespace(id=1234, display_name="Sebas", name="Sebas", nick=None),
        guild=SimpleNamespace(id=77, name="Alpha Guild"),
    )

    text = RewriteDiscordBot._format_command_usage_log(bot, interaction)

    assert "Command executed:" in text
    assert "command=/raidplan" in text
    assert "user=Sebas (1234)" in text
    assert "guild=Alpha Guild" in text
    assert "guild_id=77" in text


def test_format_command_usage_log_sanitizes_multiline_values(repo):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._safe_get_guild = lambda _guild_id: None

    interaction = SimpleNamespace(
        command=SimpleNamespace(qualified_name="status\nhidden"),
        data={"name": "status"},
        user=SimpleNamespace(id=1234, display_name="Sebas\nAdmin", name="Sebas", nick=None),
        guild=SimpleNamespace(id=77, name="Alpha\nGuild"),
    )

    text = RewriteDiscordBot._format_command_usage_log(bot, interaction)

    assert "\n" not in text
    assert "command=/status hidden" in text
    assert "user=Sebas Admin (1234)" in text
    assert "guild=Alpha Guild" in text


@pytest.mark.asyncio
async def test_on_interaction_logs_without_calling_missing_client_base_method(repo, monkeypatch):
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot._format_command_usage_log = lambda _interaction: "Command executed: command=/status"

    logged: list[str] = []
    monkeypatch.setattr(runtime_events_mod.log, "info", lambda _fmt, text: logged.append(text))

    interaction = SimpleNamespace(type=discord.InteractionType.application_command)
    await RewriteDiscordBot.on_interaction(bot, interaction)

    assert logged == ["Command executed: command=/status"]
