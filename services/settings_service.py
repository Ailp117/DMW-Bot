from __future__ import annotations

from db.repository import GuildSettingsRecord, InMemoryRepository


def ensure_settings(repo: InMemoryRepository, guild_id: int, guild_name: str | None = None) -> GuildSettingsRecord:
    return repo.ensure_settings(guild_id, guild_name)


def save_channel_settings(
    repo: InMemoryRepository,
    *,
    guild_id: int,
    guild_name: str | None,
    planner_channel_id: int | None,
    participants_channel_id: int | None,
    raidlist_channel_id: int | None,
) -> GuildSettingsRecord:
    repo.ensure_settings(guild_id, guild_name)
    return repo.configure_channels(
        guild_id,
        planner_channel_id=planner_channel_id,
        participants_channel_id=participants_channel_id,
        raidlist_channel_id=raidlist_channel_id,
    )


def save_language_setting(repo: InMemoryRepository, guild_id: int, language: str) -> GuildSettingsRecord:
    """Saves the language preference for a guild."""
    settings = repo.ensure_settings(guild_id)
    settings.language = language
    return settings


def set_templates_enabled(repo: InMemoryRepository, guild_id: int, guild_name: str | None, enabled: bool) -> GuildSettingsRecord:
    """Enables or disables auto-templates for a guild."""
    return repo.set_templates_enabled(guild_id, guild_name, enabled)


