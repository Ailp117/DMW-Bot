from __future__ import annotations

from types import SimpleNamespace

from bot.runtime import (
    FEATURE_INTERVAL_MASK,
    FEATURE_SETTINGS_KIND,
    GuildFeatureSettings,
    RewriteDiscordBot,
)


def _make_bot(repo) -> RewriteDiscordBot:
    bot = object.__new__(RewriteDiscordBot)
    bot.repo = repo
    bot.config = SimpleNamespace(
        message_xp_interval_seconds=15,
        levelup_message_cooldown_seconds=20,
    )
    bot._guild_feature_settings = {}
    return bot


def test_feature_settings_defaults_come_from_config(repo):
    bot = _make_bot(repo)

    loaded = RewriteDiscordBot._get_guild_feature_settings(bot, 77)

    assert loaded.leveling_enabled is True
    assert loaded.levelup_messages_enabled is True
    assert loaded.nanomon_reply_enabled is True
    assert loaded.approved_reply_enabled is True
    assert loaded.raid_reminder_enabled is False
    assert loaded.message_xp_interval_seconds == 15
    assert loaded.levelup_message_cooldown_seconds == 20


def test_feature_settings_roundtrip_uses_debug_cache(repo):
    bot = _make_bot(repo)

    stored = RewriteDiscordBot._set_guild_feature_settings(
        bot,
        99,
        GuildFeatureSettings(
            leveling_enabled=False,
            levelup_messages_enabled=True,
            nanomon_reply_enabled=False,
            approved_reply_enabled=True,
            raid_reminder_enabled=True,
            message_xp_interval_seconds=35,
            levelup_message_cooldown_seconds=90,
        ),
    )
    bot._guild_feature_settings.clear()
    loaded = RewriteDiscordBot._get_guild_feature_settings(bot, 99)

    assert loaded == stored

    row = repo.get_debug_cache("feature_settings:99")
    assert row is not None
    assert row.kind == FEATURE_SETTINGS_KIND
    assert row.guild_id == 99
    assert row.message_id == RewriteDiscordBot._pack_feature_settings(stored)


def test_feature_settings_intervals_are_clamped(repo):
    bot = _make_bot(repo)

    loaded = RewriteDiscordBot._set_guild_feature_settings(
        bot,
        123,
        GuildFeatureSettings(
            leveling_enabled=True,
            levelup_messages_enabled=True,
            nanomon_reply_enabled=True,
            approved_reply_enabled=True,
            raid_reminder_enabled=True,
            message_xp_interval_seconds=999_999,
            levelup_message_cooldown_seconds=999_999,
        ),
    )

    assert loaded.message_xp_interval_seconds == FEATURE_INTERVAL_MASK
    assert loaded.levelup_message_cooldown_seconds == FEATURE_INTERVAL_MASK
