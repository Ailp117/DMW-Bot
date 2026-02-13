from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import importlib.machinery
import importlib.util
import logging
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

from bot.config import load_config
from bot.logging import setup_logging
from db.repository import InMemoryRepository, RaidPostedSlotRecord, RaidRecord, UserLevelRecord
from db.schema_guard import ensure_required_schema, validate_required_tables
from services.admin_service import cancel_all_open_raids, list_active_dungeons
from services.backup_service import export_rows_to_sql
from services.leveling_service import LevelingService
from services.persistence_service import RepositoryPersistence
from services.raid_service import (
    build_raid_plan_defaults,
    create_raid_from_modal,
    finish_raid,
    planner_counts,
    slot_text,
    toggle_vote,
)
from services.raidlist_service import render_raidlist
from services.settings_service import save_channel_settings, set_templates_enabled
from services.startup_service import EXPECTED_SLASH_COMMANDS
from discord.task_registry import DebouncedGuildUpdater, SingletonTaskRegistry
from utils.hashing import sha256_text
from utils.slots import compute_qualified_slot_users, memberlist_threshold
from utils.text import contains_approved_keyword, contains_nanomon_keyword


def _import_discord_api_module():
    cwd = os.path.abspath(os.getcwd())
    search_path: list[str] = []
    for raw in sys.path:
        absolute = os.path.abspath(raw or os.getcwd())
        if absolute == cwd:
            continue
        search_path.append(raw)

    spec = importlib.machinery.PathFinder.find_spec("discord", search_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("discord.py package not found in environment")

    module = importlib.util.module_from_spec(spec)
    sys.modules["discord"] = module
    spec.loader.exec_module(module)
    return module


discord = _import_discord_api_module()
app_commands = discord.app_commands


log = logging.getLogger("dmw.runtime")
DEFAULT_PRIVILEGED_USER_ID = 403988960638009347
NANOMON_IMAGE_URL = "https://wikimon.net/images/thumb/c/cc/Nanomon_New_Century.png/200px-Nanomon_New_Century.png"
APPROVED_GIF_URL = "https://c.tenor.com/l8waltLHrxcAAAAC/tenor.gif"
STALE_RAID_HOURS = 7 * 24
STALE_RAID_CHECK_SECONDS = 15 * 60
VOICE_XP_CHECK_SECONDS = 60
LEVEL_PERSIST_WORKER_POLL_SECONDS = 5
LOG_CHANNEL_LOGGER_NAMES = ("dmw.runtime", "dmw.db")
FEATURE_SETTINGS_KIND = "feature_settings"
FEATURE_SETTINGS_CACHE_PREFIX = "feature_settings"
FEATURE_FLAG_LEVELING = 1 << 0
FEATURE_FLAG_LEVELUP_MESSAGES = 1 << 1
FEATURE_FLAG_NANOMON_REPLY = 1 << 2
FEATURE_FLAG_APPROVED_REPLY = 1 << 3
FEATURE_FLAG_MASK = 0xFF
FEATURE_MESSAGE_XP_SHIFT = 8
FEATURE_LEVELUP_COOLDOWN_SHIFT = 24
FEATURE_INTERVAL_MASK = 0xFFFF
BOT_MESSAGE_KIND = "bot_message"
BOT_MESSAGE_CACHE_PREFIX = "botmsg"
BOT_MESSAGE_INDEX_MAX_PER_CHANNEL = 400
USERNAME_SYNC_WORKER_SLEEP_SECONDS = 10 * 60
USERNAME_SYNC_RESCAN_SECONDS = 12 * 60 * 60
PRIVILEGED_ONLY_HELP_COMMANDS = frozenset(
    {
        "restart",
        "remote_guilds",
        "remote_cancel_all_raids",
        "remote_raidlist",
        "remote_rebuild_memberlists",
        "backup_db",
    }
)

_RESPONSE_ERRORS = {"InteractionResponded", "HTTPException", "NotFound", "Forbidden"}


@dataclass(slots=True)
class MemberlistRebuildStats:
    raids: int
    cleared_slot_rows: int
    deleted_slot_messages: int
    deleted_legacy_messages: int
    created: int
    updated: int
    deleted: int


@dataclass(slots=True)
class GuildFeatureSettings:
    leveling_enabled: bool
    levelup_messages_enabled: bool
    nanomon_reply_enabled: bool
    approved_reply_enabled: bool
    message_xp_interval_seconds: int
    levelup_message_cooldown_seconds: int


def _on_off(value: bool) -> str:
    return "an" if value else "aus"


def _extract_slash_command_name(content: str | None) -> str | None:
    raw = (content or "").strip()
    if not raw.startswith("/"):
        return None
    command_part = raw[1:].strip()
    if not command_part:
        return None
    first = command_part.split(maxsplit=1)[0].strip().lower()
    return first or None


def _is_response_error(exc: Exception) -> bool:
    return exc.__class__.__name__ in _RESPONSE_ERRORS


def _log_safe_wrapper_error(action: str, exc: Exception) -> None:
    if _is_response_error(exc):
        return
    log.debug("Safe Discord wrapper '%s' failed: %s", action, exc, exc_info=True)


async def _safe_defer(interaction: Any, *, ephemeral: bool = False) -> bool:
    response = getattr(interaction, "response", None)
    if response is None:
        return False
    is_done = getattr(response, "is_done", None)
    if callable(is_done) and is_done():
        return False

    try:
        await response.defer(ephemeral=ephemeral)
        return True
    except Exception as exc:
        _log_safe_wrapper_error("defer", exc)
        return False


async def _safe_followup(interaction: Any, content: str, *, ephemeral: bool = False, **kwargs: Any) -> bool:
    followup = getattr(interaction, "followup", None)
    if followup is None:
        return False
    try:
        await followup.send(content, ephemeral=ephemeral, **kwargs)
        return True
    except Exception as exc:
        _log_safe_wrapper_error("followup.send", exc)
        return False


async def _safe_send_initial(interaction: Any, content: str, *, ephemeral: bool = False, **kwargs: Any) -> bool:
    response = getattr(interaction, "response", None)
    if response is None:
        return False
    is_done = getattr(response, "is_done", None)
    if callable(is_done) and is_done():
        return await _safe_followup(interaction, content, ephemeral=ephemeral, **kwargs)

    try:
        await response.send_message(content, ephemeral=ephemeral, **kwargs)
        return True
    except Exception as exc:
        _log_safe_wrapper_error("response.send_message", exc)
        return await _safe_followup(interaction, content, ephemeral=ephemeral, **kwargs)


async def _safe_send_channel_message(channel: Any, **kwargs: Any) -> Any | None:
    send_fn = getattr(channel, "send", None)
    if send_fn is None:
        return None
    try:
        return await send_fn(**kwargs)
    except Exception as exc:
        _log_safe_wrapper_error("channel.send", exc)
        return None


async def _safe_fetch_message(channel: Any, message_id: int) -> Any | None:
    fetch_fn = getattr(channel, "fetch_message", None)
    if fetch_fn is None:
        return None
    try:
        return await fetch_fn(int(message_id))
    except Exception as exc:
        _log_safe_wrapper_error("channel.fetch_message", exc)
        return None


async def _safe_edit_message(message: Any, **kwargs: Any) -> bool:
    edit_fn = getattr(message, "edit", None)
    if edit_fn is None:
        return False
    try:
        await edit_fn(**kwargs)
        return True
    except Exception as exc:
        _log_safe_wrapper_error("message.edit", exc)
        return False


async def _safe_delete_message(message: Any) -> bool:
    delete_fn = getattr(message, "delete", None)
    if delete_fn is None:
        return False
    try:
        await delete_fn()
        return True
    except Exception as exc:
        _log_safe_wrapper_error("message.delete", exc)
        return False


def _member_name(member: Any) -> str | None:
    for attr in ("display_name", "global_name", "name"):
        value = getattr(member, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def _is_admin_or_privileged(interaction) -> bool:
    user_id = getattr(getattr(interaction, "user", None), "id", None)
    client = getattr(interaction, "client", None)
    if user_id is not None and client is not None:
        check_fn = getattr(client, "_is_privileged_user", None)
        if callable(check_fn) and check_fn(user_id):
            return True
    if user_id == DEFAULT_PRIVILEGED_USER_ID:
        return True
    perms = getattr(interaction.user, "guild_permissions", None)
    return bool(perms and getattr(perms, "administrator", False))


def _admin_or_privileged_check():
    return app_commands.check(_is_admin_or_privileged)


def _settings_embed(settings, guild_name: str, feature_settings: GuildFeatureSettings | None = None):
    embed = discord.Embed(title=f"Settings: {guild_name}", color=discord.Color.blurple())
    embed.add_field(
        name="Umfragen Channel",
        value=f"`{settings.planner_channel_id}`" if settings.planner_channel_id else "nicht gesetzt",
        inline=False,
    )
    embed.add_field(
        name="Raid Teilnehmerlisten Channel",
        value=f"`{settings.participants_channel_id}`" if settings.participants_channel_id else "nicht gesetzt",
        inline=False,
    )
    embed.add_field(
        name="Raidlist Channel",
        value=f"`{settings.raidlist_channel_id}`" if settings.raidlist_channel_id else "nicht gesetzt",
        inline=False,
    )
    embed.add_field(name="Default Min Players", value=str(settings.default_min_players), inline=True)
    embed.add_field(name="Templates Enabled", value="ja" if settings.templates_enabled else "nein", inline=True)
    if feature_settings is not None:
        embed.add_field(
            name="Levelsystem",
            value=_on_off(feature_settings.leveling_enabled),
            inline=True,
        )
        embed.add_field(
            name="Levelup Nachrichten",
            value=_on_off(feature_settings.levelup_messages_enabled),
            inline=True,
        )
        embed.add_field(
            name="Nanomon Reply",
            value=_on_off(feature_settings.nanomon_reply_enabled),
            inline=True,
        )
        embed.add_field(
            name="Approved Reply",
            value=_on_off(feature_settings.approved_reply_enabled),
            inline=True,
        )
        embed.add_field(
            name="Message XP Intervall (s)",
            value=str(int(feature_settings.message_xp_interval_seconds)),
            inline=True,
        )
        embed.add_field(
            name="Levelup Cooldown (s)",
            value=str(int(feature_settings.levelup_message_cooldown_seconds)),
            inline=True,
        )
    embed.set_footer(text="Settings unten konfigurieren und speichern.")
    return embed


class RaidCreateModal(discord.ui.Modal, title="Raid erstellen"):
    days = discord.ui.TextInput(label="Tage (Komma/Zeilen)", required=True, max_length=400)
    times = discord.ui.TextInput(label="Uhrzeiten (Komma/Zeilen)", required=True, max_length=400)
    min_players = discord.ui.TextInput(label="Min Spieler pro Slot (0=ab 1)", required=True, max_length=3)

    def __init__(
        self,
        bot: "RewriteDiscordBot",
        *,
        guild_id: int,
        guild_name: str,
        channel_id: int,
        dungeon_name: str,
        default_days: list[str],
        default_times: list[str],
        default_min_players: int,
    ):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id
        self.guild_name = guild_name
        self.channel_id = channel_id
        self.dungeon_name = dungeon_name

        if default_days:
            self.days.default = ", ".join(default_days)[:400]
        if default_times:
            self.times.default = ", ".join(default_times)[:400]
        self.min_players.default = str(max(0, int(default_min_players)))

    async def on_submit(self, interaction):
        if not interaction.guild:
            await self.bot._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
            return

        await self.bot._defer(interaction, ephemeral=True)

        try:
            min_players_value = int(str(self.min_players.value).strip())
            if min_players_value < 0:
                raise ValueError
        except ValueError:
            await _safe_followup(interaction, "Min Spieler muss Zahl >= 0 sein.", ephemeral=True)
            return

        async with self.bot._state_lock:
            try:
                result = create_raid_from_modal(
                    self.bot.repo,
                    guild_id=self.guild_id,
                    guild_name=self.guild_name,
                    planner_channel_id=self.channel_id,
                    creator_id=interaction.user.id,
                    dungeon_name=self.dungeon_name,
                    days_input=str(self.days.value),
                    times_input=str(self.times.value),
                    min_players_input=str(min_players_value),
                    message_id=0,
                )
            except ValueError as exc:
                await _safe_followup(interaction, f"Fehler: {exc}", ephemeral=True)
                return

            planner_message = await self.bot._refresh_planner_message(result.raid.id)
            if planner_message is None:
                self.bot.repo.delete_raid_cascade(result.raid.id)
                await self.bot._persist()
                await _safe_followup(interaction, "Planner-Post konnte nicht erstellt werden.", ephemeral=True)
                return

            await self.bot._sync_memberlist_messages_for_raid(result.raid.id)
            await self.bot._refresh_raidlist_for_guild(self.guild_id, force=True)
            persisted = await self.bot._persist()
            counts = planner_counts(self.bot.repo, result.raid.id)

        if not persisted:
            await _safe_followup(interaction, "Raid erstellt, aber DB-Speicherung fehlgeschlagen.", ephemeral=True)
            return
        jump_url = getattr(
            planner_message,
            "jump_url",
            f"/channels/{interaction.guild.id}/{self.channel_id}/{planner_message.id}",
        )
        await _safe_followup(
            interaction,
            (
                f"Raid erstellt: `{result.raid.display_id}` {result.raid.dungeon}\n"
                f"Day Votes: {counts['day']}\n"
                f"Time Votes: {counts['time']}\n"
                f"Planner Post: {jump_url}"
            ),
            ephemeral=True,
        )


class SettingsIntervalsModal(discord.ui.Modal, title="Allgemeine Feature Settings"):
    message_xp_interval = discord.ui.TextInput(
        label="Message XP Intervall (Sekunden)",
        required=True,
        max_length=5,
    )
    levelup_cooldown = discord.ui.TextInput(
        label="Levelup Cooldown (Sekunden)",
        required=True,
        max_length=5,
    )

    def __init__(self, bot: "RewriteDiscordBot", view: "SettingsView"):
        super().__init__()
        self.bot = bot
        self._view_ref = view
        self.message_xp_interval.default = str(int(view.message_xp_interval_seconds))
        self.levelup_cooldown.default = str(int(view.levelup_message_cooldown_seconds))

    async def on_submit(self, interaction):
        view = self._view_ref
        if not isinstance(view, SettingsView):
            await self.bot._reply(interaction, "Settings View nicht verfuegbar.", ephemeral=True)
            return
        if not interaction.guild or interaction.guild.id != view.guild_id:
            await self.bot._reply(interaction, "Ungueltiger Guild-Kontext.", ephemeral=True)
            return

        try:
            message_interval = int(str(self.message_xp_interval.value).strip())
            levelup_cooldown = int(str(self.levelup_cooldown.value).strip())
        except ValueError:
            await self.bot._reply(interaction, "Bitte gueltige Zahlen eingeben.", ephemeral=True)
            return

        if message_interval < 1 or levelup_cooldown < 1:
            await self.bot._reply(interaction, "Werte muessen >= 1 sein.", ephemeral=True)
            return
        if message_interval > FEATURE_INTERVAL_MASK or levelup_cooldown > FEATURE_INTERVAL_MASK:
            await self.bot._reply(
                interaction,
                f"Werte muessen <= {FEATURE_INTERVAL_MASK} sein.",
                ephemeral=True,
            )
            return

        view.message_xp_interval_seconds = message_interval
        view.levelup_message_cooldown_seconds = levelup_cooldown
        await self.bot._reply(interaction, "Intervall-Einstellungen vorgemerkt.", ephemeral=True)


class SettingsToggleButton(discord.ui.Button):
    def __init__(
        self,
        bot: "RewriteDiscordBot",
        *,
        guild_id: int,
        attr_name: str,
        label_prefix: str,
    ):
        super().__init__(style=discord.ButtonStyle.secondary, label=label_prefix, row=3)
        self.bot = bot
        self.guild_id = guild_id
        self.attr_name = attr_name
        self.label_prefix = label_prefix

    def _refresh_appearance(self, view: "SettingsView") -> None:
        value = bool(getattr(view, self.attr_name))
        self.style = discord.ButtonStyle.success if value else discord.ButtonStyle.danger
        self.label = f"{self.label_prefix}: {'AN' if value else 'AUS'}"

    async def callback(self, interaction):
        if not interaction.guild or interaction.guild.id != self.guild_id:
            await self.bot._reply(interaction, "Ungueltiger Guild-Kontext.", ephemeral=True)
            return

        view = self.view
        if not isinstance(view, SettingsView):
            await self.bot._reply(interaction, "Settings View nicht verfuegbar.", ephemeral=True)
            return

        current = bool(getattr(view, self.attr_name))
        setattr(view, self.attr_name, not current)
        self._refresh_appearance(view)
        await _safe_edit_message(interaction.message, view=view)
        await self.bot._reply(
            interaction,
            f"{self.label_prefix} ist jetzt {'aktiviert' if not current else 'deaktiviert'}.",
            ephemeral=True,
        )


class SettingsIntervalsButton(discord.ui.Button):
    def __init__(self, bot: "RewriteDiscordBot", *, guild_id: int):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="Intervalle einstellen",
            custom_id=f"settings:{guild_id}:intervals",
            row=4,
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction):
        if not interaction.guild or interaction.guild.id != self.guild_id:
            await self.bot._reply(interaction, "Ungueltiger Guild-Kontext.", ephemeral=True)
            return
        view = self.view
        if not isinstance(view, SettingsView):
            await self.bot._reply(interaction, "Settings View nicht verfuegbar.", ephemeral=True)
            return
        try:
            await interaction.response.send_modal(SettingsIntervalsModal(self.bot, view))
        except Exception:
            await self.bot._reply(interaction, "Modal konnte nicht geoeffnet werden.", ephemeral=True)


class SettingsView(discord.ui.View):
    def __init__(self, bot: "RewriteDiscordBot", *, guild_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        settings = bot.repo.ensure_settings(guild_id)
        feature_settings = bot._get_guild_feature_settings(guild_id)
        self.planner_channel_id: int | None = settings.planner_channel_id
        self.participants_channel_id: int | None = settings.participants_channel_id
        self.raidlist_channel_id: int | None = settings.raidlist_channel_id
        self.leveling_enabled: bool = feature_settings.leveling_enabled
        self.levelup_messages_enabled: bool = feature_settings.levelup_messages_enabled
        self.nanomon_reply_enabled: bool = feature_settings.nanomon_reply_enabled
        self.approved_reply_enabled: bool = feature_settings.approved_reply_enabled
        self.message_xp_interval_seconds: int = feature_settings.message_xp_interval_seconds
        self.levelup_message_cooldown_seconds: int = feature_settings.levelup_message_cooldown_seconds

        planner_select = discord.ui.ChannelSelect(
            placeholder="Umfragen Channel waehlen",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=0,
            max_values=1,
            custom_id=f"settings:{guild_id}:planner",
            row=0,
        )
        participants_select = discord.ui.ChannelSelect(
            placeholder="Raid Teilnehmerlisten Channel waehlen",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=0,
            max_values=1,
            custom_id=f"settings:{guild_id}:participants",
            row=1,
        )
        raidlist_select = discord.ui.ChannelSelect(
            placeholder="Raidlist Channel waehlen",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=0,
            max_values=1,
            custom_id=f"settings:{guild_id}:raidlist",
            row=2,
        )

        planner_select.callback = self._on_planner_select
        participants_select.callback = self._on_participants_select
        raidlist_select.callback = self._on_raidlist_select

        self.add_item(planner_select)
        self.add_item(participants_select)
        self.add_item(raidlist_select)

        toggle_items = [
            SettingsToggleButton(
                bot,
                guild_id=guild_id,
                attr_name="leveling_enabled",
                label_prefix="Levelsystem",
            ),
            SettingsToggleButton(
                bot,
                guild_id=guild_id,
                attr_name="levelup_messages_enabled",
                label_prefix="Levelup Msg",
            ),
            SettingsToggleButton(
                bot,
                guild_id=guild_id,
                attr_name="nanomon_reply_enabled",
                label_prefix="Nanomon Reply",
            ),
            SettingsToggleButton(
                bot,
                guild_id=guild_id,
                attr_name="approved_reply_enabled",
                label_prefix="Approved Reply",
            ),
        ]
        for item in toggle_items:
            item._refresh_appearance(self)
            self.add_item(item)

        self.add_item(SettingsIntervalsButton(bot, guild_id=guild_id))
        self.add_item(SettingsSaveButton(bot, guild_id))

    async def _on_planner_select(self, interaction):
        selected = ((interaction.data or {}).get("values") or [])
        self.planner_channel_id = int(selected[0]) if selected else None
        await self.bot._defer(interaction, ephemeral=True)
        await _safe_followup(interaction, "Umfragen Channel vorgemerkt.", ephemeral=True)

    async def _on_participants_select(self, interaction):
        selected = ((interaction.data or {}).get("values") or [])
        self.participants_channel_id = int(selected[0]) if selected else None
        await self.bot._defer(interaction, ephemeral=True)
        await _safe_followup(interaction, "Raid Teilnehmerlisten Channel vorgemerkt.", ephemeral=True)

    async def _on_raidlist_select(self, interaction):
        selected = ((interaction.data or {}).get("values") or [])
        self.raidlist_channel_id = int(selected[0]) if selected else None
        await self.bot._defer(interaction, ephemeral=True)
        await _safe_followup(interaction, "Raidlist Channel vorgemerkt.", ephemeral=True)


class SettingsSaveButton(discord.ui.Button):
    def __init__(self, bot: "RewriteDiscordBot", guild_id: int):
        super().__init__(
            style=discord.ButtonStyle.success,
            label="Speichern",
            custom_id=f"settings:{guild_id}:save",
            row=4,
        )
        self.bot = bot
        self.guild_id = guild_id

    async def callback(self, interaction):
        if not interaction.guild or interaction.guild.id != self.guild_id:
            await self.bot._reply(interaction, "Ungueltiger Guild-Kontext.", ephemeral=True)
            return

        view = self.view
        if not isinstance(view, SettingsView):
            await self.bot._reply(interaction, "Settings View nicht verfuegbar.", ephemeral=True)
            return

        await self.bot._defer(interaction, ephemeral=True)
        async with self.bot._state_lock:
            row = save_channel_settings(
                self.bot.repo,
                guild_id=interaction.guild.id,
                guild_name=interaction.guild.name,
                planner_channel_id=view.planner_channel_id,
                participants_channel_id=view.participants_channel_id,
                raidlist_channel_id=view.raidlist_channel_id,
            )
            feature_row = self.bot._set_guild_feature_settings(
                interaction.guild.id,
                GuildFeatureSettings(
                    leveling_enabled=view.leveling_enabled,
                    levelup_messages_enabled=view.levelup_messages_enabled,
                    nanomon_reply_enabled=view.nanomon_reply_enabled,
                    approved_reply_enabled=view.approved_reply_enabled,
                    message_xp_interval_seconds=view.message_xp_interval_seconds,
                    levelup_message_cooldown_seconds=view.levelup_message_cooldown_seconds,
                ),
            )
            await self.bot._refresh_raidlist_for_guild(interaction.guild.id, force=True)
            persisted = await self.bot._persist()

        if not persisted:
            await _safe_followup(interaction, "Settings konnten nicht gespeichert werden.", ephemeral=True)
            return
        await _safe_followup(
            interaction,
            (
                "Settings gespeichert:\n"
                f"Umfragen: `{row.planner_channel_id}`\n"
                f"Teilnehmerlisten: `{row.participants_channel_id}`\n"
                f"Raidlist: `{row.raidlist_channel_id}`\n"
                f"Levelsystem: `{_on_off(feature_row.leveling_enabled)}`\n"
                f"Levelup Msg: `{_on_off(feature_row.levelup_messages_enabled)}`\n"
                f"Nanomon Reply: `{_on_off(feature_row.nanomon_reply_enabled)}`\n"
                f"Approved Reply: `{_on_off(feature_row.approved_reply_enabled)}`\n"
                f"Message XP Intervall: `{feature_row.message_xp_interval_seconds}`\n"
                f"Levelup Cooldown: `{feature_row.levelup_message_cooldown_seconds}`"
            ),
            ephemeral=True,
        )


class FinishButton(discord.ui.Button):
    def __init__(self, bot: "RewriteDiscordBot", raid_id: int):
        super().__init__(
            style=discord.ButtonStyle.danger,
            label="Raid beenden",
            custom_id=f"raid:{raid_id}:finish",
        )
        self.bot = bot
        self.raid_id = raid_id

    async def callback(self, interaction):
        await self.bot._defer(interaction, ephemeral=True)
        await self.bot._finish_raid_interaction(interaction, raid_id=self.raid_id, deferred=True)


class RaidVoteView(discord.ui.View):
    def __init__(self, bot: "RewriteDiscordBot", raid_id: int, days: list[str], times: list[str]):
        super().__init__(timeout=None)
        self.bot = bot
        self.raid_id = raid_id

        day_values = days[:25]
        time_values = times[:25]

        if day_values:
            day_select = discord.ui.Select(
                placeholder="Tage waehlen/abwaehlen...",
                min_values=1,
                max_values=min(25, max(1, len(day_values))),
                options=[discord.SelectOption(label=value, value=value) for value in day_values],
                custom_id=f"raid:{raid_id}:day",
            )
            day_select.callback = self.on_day_select
            self.add_item(day_select)

        if time_values:
            time_select = discord.ui.Select(
                placeholder="Uhrzeiten waehlen/abwaehlen...",
                min_values=1,
                max_values=min(25, max(1, len(time_values))),
                options=[discord.SelectOption(label=value, value=value) for value in time_values],
                custom_id=f"raid:{raid_id}:time",
            )
            time_select.callback = self.on_time_select
            self.add_item(time_select)

        self.add_item(FinishButton(bot, raid_id))

    async def _vote(self, interaction, *, kind: str) -> None:
        if not interaction.guild:
            await self.bot._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
            return

        await self.bot._defer(interaction, ephemeral=True)
        values = [str(value) for value in ((interaction.data or {}).get("values") or [])]
        if not values:
            await _safe_followup(interaction, "Keine Werte ausgewaehlt.", ephemeral=True)
            return

        async with self.bot._state_lock:
            raid = self.bot.repo.get_raid(self.raid_id)
            if raid is None or raid.status != "open":
                await _safe_followup(interaction, "Raid ist nicht mehr aktiv.", ephemeral=True)
                return

            labels = self.bot.repo.list_raid_options(raid.id)[0 if kind == "day" else 1]
            lookup = {label.lower(): label for label in labels}
            applied = 0
            for raw in values:
                selected = lookup.get(raw.strip().lower())
                if selected is None:
                    continue
                toggle_vote(
                    self.bot.repo,
                    raid_id=raid.id,
                    kind=kind,
                    option_label=selected,
                    user_id=interaction.user.id,
                )
                applied += 1

            if applied == 0:
                await _safe_followup(interaction, "Keine gueltige Option erkannt.", ephemeral=True)
                return

            await self.bot._sync_vote_ui_after_change(raid.id)
            persisted = await self.bot._persist()

        voter = _member_name(interaction.user) or str(interaction.user.id)
        if not persisted:
            await _safe_followup(interaction, "Stimme gesetzt, aber DB-Speicherung fehlgeschlagen.", ephemeral=True)
            return
        await _safe_followup(interaction, f"Stimme aktualisiert fuer **{voter}**.", ephemeral=True)

    async def on_day_select(self, interaction):
        await self._vote(interaction, kind="day")

    async def on_time_select(self, interaction):
        await self._vote(interaction, kind="time")


class RewriteDiscordBot(discord.Client):
    def __init__(self, repo: InMemoryRepository, config) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = config.enable_message_content_intent
        super().__init__(intents=intents)

        self.repo = repo
        self.config = config
        self.persistence = RepositoryPersistence(config)
        self.tree = app_commands.CommandTree(self)
        self.task_registry = SingletonTaskRegistry()
        self.raidlist_updater = DebouncedGuildUpdater(
            self._refresh_raidlist_for_guild_persisted,
            debounce_seconds=1.5,
            cooldown_seconds=0.8,
        )
        self.leveling_service = LevelingService()

        self.log_channel = None
        self.log_forward_queue: asyncio.Queue[str] = asyncio.Queue()
        self.pending_log_buffer: deque[str] = deque(maxlen=250)
        self.log_forwarder_active = False
        self.last_self_test_ok_at: datetime | None = None
        self.last_self_test_error: str | None = None

        self._commands_registered = False
        self._state_loaded = False
        self._views_restored = False
        self._commands_synced = False
        self._runtime_restored = False
        self._slash_command_names: set[str] = set()

        self._ack_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._application_owner_ids: set[int] = set()
        self._guild_feature_settings: dict[int, GuildFeatureSettings] = {}
        self._acked_interactions: set[int] = set()
        self._raidlist_hash_by_guild: dict[int, str] = {}
        self._username_sync_next_run_by_guild: dict[int, float] = {}
        self._level_state_dirty = False
        self._last_level_persist_monotonic = time.monotonic()
        self._discord_log_handler = self._build_discord_log_handler()
        self._discord_loggers: list[logging.Logger] = []
        self._attach_discord_log_handler()

    async def setup_hook(self) -> None:
        if not self._state_loaded:
            await self._bootstrap_repository()
            self._state_loaded = True
        if not self._commands_registered:
            self._register_commands()
            self._slash_command_names = {cmd.name.lower() for cmd in self.tree.get_commands()}
            self._commands_registered = True
        if not self._views_restored:
            self._restore_persistent_vote_views()
            self._views_restored = True

    async def _bootstrap_repository(self) -> None:
        if not await self.persistence.session_manager.try_acquire_singleton_lock():
            log.warning("Another instance holds singleton lock. Exiting.")
            raise SystemExit(0)

        async with self.persistence.session_manager.engine.begin() as connection:
            changes = await ensure_required_schema(connection)
            await validate_required_tables(connection)
            if changes:
                log.info("Applied DB schema changes: %s", ", ".join(changes))

        await self.persistence.load(self.repo)
        if not self.repo.dungeons:
            self._seed_default_dungeons()
            await self.persistence.flush(self.repo)

    def _restore_persistent_vote_views(self) -> None:
        restored = 0
        for raid in self.repo.list_open_raids():
            if not raid.message_id:
                continue
            days, times = self.repo.list_raid_options(raid.id)
            if not days or not times:
                continue
            self.add_view(RaidVoteView(self, raid.id, days, times), message_id=raid.message_id)
            restored += 1
        if restored:
            log.info("Restored %s persistent raid vote views", restored)

    async def on_ready(self) -> None:
        await self._refresh_application_owner_ids()

        if not self._commands_synced:
            synced: list[int] = []
            for guild in self.guilds:
                try:
                    await self.tree.sync(guild=discord.Object(id=guild.id))
                    synced.append(guild.id)
                except Exception:
                    log.exception("Guild sync failed for %s", guild.id)

            try:
                await self.tree.sync()
            except Exception:
                log.exception("Global command sync failed")

            self._commands_synced = True
            log.info("Command sync completed (guild_sync=%s)", synced)

        async with self._state_lock:
            guild_settings_changed = self._sync_connected_guild_settings()
            if not self._runtime_restored:
                await self._restore_runtime_messages()
                self._runtime_restored = True
            elif guild_settings_changed:
                await self._persist()

        if not self._runtime_restored:
            return

        self._start_background_loops()

        if self.log_channel is None:
            self.log_channel = await self._resolve_log_channel()
        self.log_forwarder_active = True
        self._flush_pending_logs()

        log.info("Rewrite bot ready as %s", self.user)

    async def _restore_runtime_messages(self) -> None:
        for raid in list(self.repo.list_open_raids()):
            await self._refresh_planner_message(raid.id)
            await self._sync_memberlist_messages_for_raid(raid.id, recreate_existing=True)
        await self._refresh_raidlists_for_all_guilds(force=True)
        await self._persist()

    def _sync_connected_guild_settings(self) -> bool:
        changed = False
        for guild in self.guilds:
            existing = self.repo.settings.get(int(guild.id))
            current_name = (guild.name or "").strip() or None
            before_name = existing.guild_name if existing else None
            if existing is None or before_name != current_name:
                self.repo.ensure_settings(int(guild.id), current_name)
                changed = True
        return changed

    def _start_background_loops(self) -> None:
        self.task_registry.start_once("stale_raid_worker", self._stale_raid_worker)
        self.task_registry.start_once("voice_xp_worker", self._voice_xp_worker)
        self.task_registry.start_once("level_persist_worker", self._level_persist_worker)
        self.task_registry.start_once("username_sync_worker", self._username_sync_worker)
        self.task_registry.start_once("self_test_worker", self._self_test_worker)
        self.task_registry.start_once("backup_worker", self._backup_worker)
        self.task_registry.start_once("log_forwarder_worker", self._log_forwarder_worker)

    async def on_guild_join(self, guild) -> None:
        async with self._state_lock:
            self.repo.ensure_settings(guild.id, guild.name)
            self._username_sync_next_run_by_guild[int(guild.id)] = 0.0
            await self._force_raidlist_refresh(guild.id)
            await self._persist()

        try:
            await self._sync_guild_usernames(guild, force=True)
        except Exception:
            log.exception("Initial username sync failed for joined guild %s", getattr(guild, "id", None))

        try:
            await self.tree.sync(guild=discord.Object(id=guild.id))
        except Exception:
            log.exception("Guild sync failed for joined guild %s", guild.id)

    async def on_guild_remove(self, guild) -> None:
        async with self._state_lock:
            self._guild_feature_settings.pop(int(guild.id), None)
            self._username_sync_next_run_by_guild.pop(int(guild.id), None)
            self.repo.purge_guild_data(guild.id)
            await self._persist()

    async def on_member_join(self, member) -> None:
        if getattr(member, "bot", False):
            return
        guild_id = int(getattr(getattr(member, "guild", None), "id", 0) or 0)
        user_id = int(getattr(member, "id", 0) or 0)
        username = _member_name(member)
        if guild_id <= 0 or user_id <= 0 or not username:
            return

        changed = False
        async with self._state_lock:
            changed = self._upsert_member_username(guild_id=guild_id, user_id=user_id, username=username)
            if changed:
                self._level_state_dirty = True
        if changed:
            log.info("Username sync join guild_id=%s user_id=%s", guild_id, user_id)

    async def on_member_update(self, before, after) -> None:
        if getattr(after, "bot", False):
            return
        before_name = _member_name(before)
        after_name = _member_name(after)
        if not after_name or before_name == after_name:
            return

        guild_id = int(getattr(getattr(after, "guild", None), "id", 0) or 0)
        user_id = int(getattr(after, "id", 0) or 0)
        if guild_id <= 0 or user_id <= 0:
            return

        changed = False
        async with self._state_lock:
            changed = self._upsert_member_username(guild_id=guild_id, user_id=user_id, username=after_name)
            if changed:
                self._level_state_dirty = True
        if changed:
            log.info("Username sync update guild_id=%s user_id=%s", guild_id, user_id)

    async def on_message(self, message) -> None:
        if message.author.bot:
            return

        if (
            self.log_channel is not None
            and message.guild is not None
            and message.channel.id == getattr(self.log_channel, "id", None)
            and bool(getattr(getattr(message.author, "guild_permissions", None), "administrator", False))
        ):
            handled = await self._execute_console_command(message)
            if handled:
                return

        guild_feature_settings = self._get_guild_feature_settings(message.guild.id) if message.guild is not None else None
        if guild_feature_settings is not None:
            now = datetime.now(UTC)
            is_command_message = self._is_registered_command_message(getattr(message, "content", None))
            if guild_feature_settings.leveling_enabled and not is_command_message:
                async with self._state_lock:
                    result = self.leveling_service.update_message_xp(
                        self.repo,
                        guild_id=message.guild.id,
                        user_id=message.author.id,
                        username=_member_name(message.author),
                        now=now,
                        min_award_interval=timedelta(
                            seconds=max(1, int(guild_feature_settings.message_xp_interval_seconds))
                        ),
                    )
                    if result.xp_awarded:
                        self._level_state_dirty = True
                if (
                    guild_feature_settings.levelup_messages_enabled
                    and result.xp_awarded
                    and result.current_level > result.previous_level
                ):
                    should_announce = self.leveling_service.should_announce_levelup(
                        guild_id=message.guild.id,
                        user_id=message.author.id,
                        level=result.current_level,
                        now=now,
                        min_announce_interval=timedelta(
                            seconds=max(1, int(guild_feature_settings.levelup_message_cooldown_seconds))
                        ),
                    )
                    if should_announce:
                        try:
                            await self._send_channel_message(
                                message.channel,
                                content=(
                                f"🎉 {message.author.mention} ist auf **Level {result.current_level}** aufgestiegen! "
                                f"(XP: {result.xp})"
                                ),
                            )
                        except Exception:
                            log.exception("Failed to send level-up message")
        if (
            guild_feature_settings is not None
            and guild_feature_settings.nanomon_reply_enabled
            and contains_nanomon_keyword(message.content)
        ):
            try:
                posted = await message.reply(NANOMON_IMAGE_URL, mention_author=False)
                if posted is not None:
                    self._track_bot_message(posted)
            except Exception:
                log.exception("Failed to send nanomon reply")
        if (
            guild_feature_settings is not None
            and guild_feature_settings.approved_reply_enabled
            and contains_approved_keyword(message.content)
        ):
            try:
                posted = await message.reply(APPROVED_GIF_URL, mention_author=False)
                if posted is not None:
                    self._track_bot_message(posted)
            except Exception:
                log.exception("Failed to send approved reply")

    async def on_voice_state_update(self, member, before, after) -> None:
        if getattr(member, "bot", False):
            return
        guild = getattr(member, "guild", None)
        if guild is None:
            return

        if getattr(after, "channel", None) is None:
            self.leveling_service.on_voice_disconnect(guild.id, member.id)
        elif getattr(before, "channel", None) is None:
            self.leveling_service.on_voice_connect(guild.id, member.id, datetime.now(UTC))

    async def _execute_console_command(self, message) -> bool:
        raw = (getattr(message, "content", "") or "").strip()
        if not raw:
            return False
        command = raw.lstrip("/").strip().split()[0].lower()
        if command != "restart":
            return False
        try:
            await self._send_channel_message(message.channel, content="♻️ Neustart wird eingeleitet ...")
        except Exception:
            pass
        await self.close()
        return True

    def _build_discord_log_handler(self) -> logging.Handler:
        bot = self

        class _DiscordQueueHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    msg = self.format(record)
                    bot.enqueue_discord_log(msg)
                except Exception:
                    self.handleError(record)

        handler = _DiscordQueueHandler(level=getattr(logging, self.config.discord_log_level, logging.DEBUG))
        handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] %(levelname)s "
                "src=%(name)s/%(module)s.%(funcName)s:%(lineno)d | %(message)s",
                "%Y-%m-%d %H:%M:%S",
            )
        )
        return handler

    def _attach_discord_log_handler(self) -> None:
        attached: list[logging.Logger] = []
        for logger_name in LOG_CHANNEL_LOGGER_NAMES:
            logger = logging.getLogger(logger_name)
            if self._discord_log_handler not in logger.handlers:
                logger.addHandler(self._discord_log_handler)
            attached.append(logger)
        self._discord_loggers = attached

    def enqueue_discord_log(self, message: str) -> None:
        if not message:
            return
        text = message if len(message) <= 1800 else f"{message[:1797]}..."
        if self.log_forwarder_active:
            self.log_forward_queue.put_nowait(text)
            return
        self.pending_log_buffer.append(text)

    def _flush_pending_logs(self) -> None:
        while self.pending_log_buffer:
            self.log_forward_queue.put_nowait(self.pending_log_buffer.popleft())

    async def _resolve_log_channel(self):
        if self.config.log_guild_id <= 0 or self.config.log_channel_id <= 0:
            return None
        guild = self.get_guild(self.config.log_guild_id)
        if guild is None:
            return None
        channel = guild.get_channel(self.config.log_channel_id)
        if isinstance(channel, discord.TextChannel):
            return channel
        return None

    async def _log_forwarder_worker(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            message = await self.log_forward_queue.get()
            channel = self.log_channel
            if channel is None:
                continue
            try:
                await self._send_channel_message(channel, content=f"```\n{message}\n```")
            except Exception:
                continue

    async def _run_self_tests_once(self) -> None:
        registered = sorted(cmd.name for cmd in self.tree.get_commands())
        reg_set = set(registered)
        missing = sorted(name for name in EXPECTED_SLASH_COMMANDS if name not in reg_set)
        if missing:
            raise RuntimeError(f"Missing commands: {', '.join(missing)}")
        unexpected = sorted(name for name in reg_set if name not in EXPECTED_SLASH_COMMANDS)
        if unexpected:
            log.warning("Unexpected extra commands registered: %s", ", ".join(unexpected))
        self.last_self_test_ok_at = datetime.now(UTC)
        self.last_self_test_error = None

    async def _self_test_worker(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self._run_self_tests_once()
            except Exception as exc:
                self.last_self_test_error = str(exc)
                log.exception("Background self-test failed")
            await asyncio.sleep(max(30, int(self.config.self_test_interval_seconds)))

    def _snapshot_rows_by_table(self) -> dict[str, list[dict[str, object]]]:
        return {
            "guild_settings": [asdict(row) for row in self.repo.settings.values()],
            "raids": [asdict(row) for row in self.repo.raids.values()],
            "raid_options": [asdict(row) for row in self.repo.raid_options.values()],
            "raid_votes": [asdict(row) for row in self.repo.raid_votes.values()],
            "raid_posted_slots": [asdict(row) for row in self.repo.raid_posted_slots.values()],
            "raid_templates": [asdict(row) for row in self.repo.raid_templates.values()],
            "raid_attendance": [asdict(row) for row in self.repo.raid_attendance.values()],
            "user_levels": [asdict(row) for row in self.repo.user_levels.values()],
            "debug_mirror_cache": [asdict(row) for row in self.repo.debug_cache.values()],
            "dungeons": [asdict(row) for row in self.repo.dungeons.values()],
        }

    async def _run_backup_once(self) -> Path:
        log.info("Automatic backup started")
        rows = self._snapshot_rows_by_table()
        path = await export_rows_to_sql(Path("backups/db_backup.sql"), rows_by_table=rows)
        log.info("Automatic backup completed: %s", path.as_posix())
        return path

    async def _backup_worker(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                async with self._state_lock:
                    await self._run_backup_once()
            except Exception:
                log.exception("Background backup failed")
            await asyncio.sleep(max(300, int(self.config.backup_interval_seconds)))

    async def _voice_xp_worker(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            changed = False
            now = datetime.now(UTC)
            async with self._state_lock:
                for guild in self.guilds:
                    feature_settings = self._get_guild_feature_settings(guild.id)
                    if not feature_settings.leveling_enabled:
                        continue
                    for voice_channel in guild.voice_channels:
                        for member in voice_channel.members:
                            if member.bot:
                                continue
                            awarded = self.leveling_service.award_voice_xp_once(
                                self.repo,
                                now=now,
                                guild_id=guild.id,
                                user_id=member.id,
                                username=_member_name(member),
                            )
                            changed = changed or awarded
                if changed:
                    self._level_state_dirty = True
            await asyncio.sleep(VOICE_XP_CHECK_SECONDS)

    async def _flush_level_state_if_due(self, *, force: bool = False) -> bool:
        if not self._level_state_dirty:
            return True
        interval = max(5, int(self.config.level_persist_interval_seconds))
        now = time.monotonic()
        if not force and (now - self._last_level_persist_monotonic) < interval:
            return False

        persisted = await self._persist()
        if persisted:
            self._level_state_dirty = False
            self._last_level_persist_monotonic = now
            return True
        return False

    async def _level_persist_worker(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(LEVEL_PERSIST_WORKER_POLL_SECONDS)
            async with self._state_lock:
                await self._flush_level_state_if_due()

    async def _username_sync_worker(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            total_scanned = 0
            total_changed = 0
            for guild in list(self.guilds):
                scanned, changed = await self._sync_guild_usernames(guild)
                total_scanned += scanned
                total_changed += changed
                await asyncio.sleep(0)

            if total_changed > 0:
                log.info(
                    "Username sync updated rows=%s scanned_members=%s guilds=%s",
                    total_changed,
                    total_scanned,
                    len(self.guilds),
                )
            await asyncio.sleep(USERNAME_SYNC_WORKER_SLEEP_SECONDS)

    async def _cleanup_stale_raids_once(self) -> int:
        cutoff_hours = STALE_RAID_HOURS

        stale_ids: list[int] = []
        for raid in self.repo.list_open_raids():
            created_at = raid.created_at
            if created_at.tzinfo is None:
                created_utc = created_at.replace(tzinfo=UTC)
            else:
                created_utc = created_at.astimezone(UTC)
            now = datetime.now(UTC)
            age_seconds = (now - created_utc).total_seconds()
            if age_seconds >= cutoff_hours * 3600:
                stale_ids.append(raid.id)

        removed = 0
        for raid_id in stale_ids:
            raid = self.repo.get_raid(raid_id)
            if raid is None:
                continue
            slot_rows = list(self.repo.list_posted_slots(raid.id).values())
            await self._close_planner_message(
                guild_id=raid.guild_id,
                channel_id=raid.channel_id,
                message_id=raid.message_id,
                reason="stale-cleanup",
            )
            await self._cleanup_temp_role(raid)
            for row in slot_rows:
                await self._delete_slot_message(row)
            self.repo.delete_raid_cascade(raid.id)
            await self._refresh_raidlist_for_guild(raid.guild_id, force=True)
            removed += 1

        if removed:
            await self._persist()
        return removed

    async def _stale_raid_worker(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                async with self._state_lock:
                    await self._cleanup_stale_raids_once()
            except Exception:
                log.exception("Stale raid cleanup failed")
            await asyncio.sleep(STALE_RAID_CHECK_SECONDS)

    def _seed_default_dungeons(self) -> None:
        self.repo.add_dungeon(name="Nanos", short_code="NAN", sort_order=1)
        self.repo.add_dungeon(name="Skull", short_code="SKL", sort_order=2)

    async def _mark_interaction_once(self, interaction: Any) -> bool:
        interaction_id = int(getattr(interaction, "id", 0) or 0)
        if interaction_id <= 0:
            return True
        async with self._ack_lock:
            if interaction_id in self._acked_interactions:
                return False
            self._acked_interactions.add(interaction_id)
            if len(self._acked_interactions) > 20_000:
                self._acked_interactions.clear()
            return True

    async def _reply(self, interaction: Any, content: str, *, ephemeral: bool = True) -> None:
        first = await self._mark_interaction_once(interaction)
        if first and await _safe_send_initial(interaction, content, ephemeral=ephemeral):
            return
        await _safe_followup(interaction, content, ephemeral=ephemeral)

    async def _defer(self, interaction: Any, *, ephemeral: bool = True) -> bool:
        first = await self._mark_interaction_once(interaction)
        if not first:
            return False
        return await _safe_defer(interaction, ephemeral=ephemeral)

    async def _persist(self) -> bool:
        try:
            await self.persistence.flush(self.repo)
            return True
        except Exception:
            log.exception("Failed to flush state. Reloading repository snapshot.")
            try:
                await self.persistence.load(self.repo)
            except Exception:
                log.exception("Failed to reload repository after flush error.")
            return False

    def _find_open_raid_by_display_id(self, guild_id: int, display_id: int) -> RaidRecord | None:
        for raid in self.repo.list_open_raids(guild_id):
            if raid.display_id is None:
                continue
            if int(raid.display_id) == int(display_id):
                return raid
        return None

    def _public_help_command_names(self) -> list[str]:
        names = sorted(cmd.name for cmd in self.tree.get_commands())
        return [name for name in names if name not in PRIVILEGED_ONLY_HELP_COMMANDS]

    def _default_guild_feature_settings(self) -> GuildFeatureSettings:
        return GuildFeatureSettings(
            leveling_enabled=True,
            levelup_messages_enabled=True,
            nanomon_reply_enabled=True,
            approved_reply_enabled=True,
            message_xp_interval_seconds=max(1, int(self.config.message_xp_interval_seconds)),
            levelup_message_cooldown_seconds=max(1, int(self.config.levelup_message_cooldown_seconds)),
        )

    @staticmethod
    def _feature_settings_cache_key(guild_id: int) -> str:
        return f"{FEATURE_SETTINGS_CACHE_PREFIX}:{int(guild_id)}"

    @staticmethod
    def _pack_feature_settings(settings: GuildFeatureSettings) -> int:
        flags = 0
        if settings.leveling_enabled:
            flags |= FEATURE_FLAG_LEVELING
        if settings.levelup_messages_enabled:
            flags |= FEATURE_FLAG_LEVELUP_MESSAGES
        if settings.nanomon_reply_enabled:
            flags |= FEATURE_FLAG_NANOMON_REPLY
        if settings.approved_reply_enabled:
            flags |= FEATURE_FLAG_APPROVED_REPLY

        message_interval = max(1, min(FEATURE_INTERVAL_MASK, int(settings.message_xp_interval_seconds)))
        levelup_cooldown = max(1, min(FEATURE_INTERVAL_MASK, int(settings.levelup_message_cooldown_seconds)))

        return (
            (flags & FEATURE_FLAG_MASK)
            | (message_interval << FEATURE_MESSAGE_XP_SHIFT)
            | (levelup_cooldown << FEATURE_LEVELUP_COOLDOWN_SHIFT)
        )

    def _unpack_feature_settings(self, packed: int, defaults: GuildFeatureSettings) -> GuildFeatureSettings:
        value = int(packed)
        flags = value & FEATURE_FLAG_MASK
        raw_message_interval = (value >> FEATURE_MESSAGE_XP_SHIFT) & FEATURE_INTERVAL_MASK
        raw_levelup_cooldown = (value >> FEATURE_LEVELUP_COOLDOWN_SHIFT) & FEATURE_INTERVAL_MASK

        message_interval = raw_message_interval if raw_message_interval > 0 else defaults.message_xp_interval_seconds
        levelup_cooldown = (
            raw_levelup_cooldown if raw_levelup_cooldown > 0 else defaults.levelup_message_cooldown_seconds
        )

        return GuildFeatureSettings(
            leveling_enabled=bool(flags & FEATURE_FLAG_LEVELING),
            levelup_messages_enabled=bool(flags & FEATURE_FLAG_LEVELUP_MESSAGES),
            nanomon_reply_enabled=bool(flags & FEATURE_FLAG_NANOMON_REPLY),
            approved_reply_enabled=bool(flags & FEATURE_FLAG_APPROVED_REPLY),
            message_xp_interval_seconds=max(1, int(message_interval)),
            levelup_message_cooldown_seconds=max(1, int(levelup_cooldown)),
        )

    @staticmethod
    def _feature_settings_payload(settings: GuildFeatureSettings) -> str:
        return (
            f"leveling={int(settings.leveling_enabled)}|"
            f"levelup_messages={int(settings.levelup_messages_enabled)}|"
            f"nanomon={int(settings.nanomon_reply_enabled)}|"
            f"approved={int(settings.approved_reply_enabled)}|"
            f"xp_interval={int(settings.message_xp_interval_seconds)}|"
            f"levelup_cooldown={int(settings.levelup_message_cooldown_seconds)}"
        )

    def _get_guild_feature_settings(self, guild_id: int) -> GuildFeatureSettings:
        normalized_guild_id = int(guild_id)
        cached = self._guild_feature_settings.get(normalized_guild_id)
        if cached is not None:
            return cached

        defaults = self._default_guild_feature_settings()
        row = self.repo.get_debug_cache(self._feature_settings_cache_key(normalized_guild_id))
        if row is None or row.kind != FEATURE_SETTINGS_KIND:
            self._guild_feature_settings[normalized_guild_id] = defaults
            return defaults

        try:
            loaded = self._unpack_feature_settings(int(row.message_id), defaults)
        except Exception:
            loaded = defaults
        self._guild_feature_settings[normalized_guild_id] = loaded
        return loaded

    def _set_guild_feature_settings(self, guild_id: int, settings: GuildFeatureSettings) -> GuildFeatureSettings:
        normalized_guild_id = int(guild_id)
        defaults = self._default_guild_feature_settings()
        packed = self._pack_feature_settings(settings)
        normalized = self._unpack_feature_settings(packed, defaults)
        packed = self._pack_feature_settings(normalized)
        payload_hash = sha256_text(self._feature_settings_payload(normalized))

        self.repo.upsert_debug_cache(
            cache_key=self._feature_settings_cache_key(normalized_guild_id),
            kind=FEATURE_SETTINGS_KIND,
            guild_id=normalized_guild_id,
            raid_id=None,
            message_id=packed,
            payload_hash=payload_hash,
        )
        self._guild_feature_settings[normalized_guild_id] = normalized
        return normalized

    async def _refresh_application_owner_ids(self) -> None:
        if self._application_owner_ids:
            return
        try:
            app_info = await self.application_info()
        except Exception:
            log.exception("Failed to load application owner IDs for privileged checks.")
            return

        owner_ids: set[int] = set()
        owner = getattr(app_info, "owner", None)
        owner_id = getattr(owner, "id", None)
        if owner_id is not None:
            owner_ids.add(int(owner_id))

        team = getattr(app_info, "team", None)
        members = getattr(team, "members", None) if team is not None else None
        if members:
            for member in members:
                member_id = getattr(member, "id", None)
                if member_id is not None:
                    owner_ids.add(int(member_id))

        self._application_owner_ids = owner_ids
        log.info(
            "Privileged access configured_user_id=%s owner_ids=%s",
            int(getattr(self.config, "privileged_user_id", DEFAULT_PRIVILEGED_USER_ID)),
            sorted(owner_ids),
        )

    def _is_privileged_user(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        try:
            parsed_user_id = int(user_id)
        except (TypeError, ValueError):
            return False

        configured = int(getattr(self.config, "privileged_user_id", DEFAULT_PRIVILEGED_USER_ID))
        if parsed_user_id == configured:
            return True
        return parsed_user_id in self._application_owner_ids

    def _current_bot_user_id(self) -> int:
        connection = getattr(self, "_connection", None)
        user = getattr(connection, "user", None) if connection is not None else None
        raw_user_id = getattr(user, "id", None)
        if raw_user_id is None:
            return 0
        try:
            return int(raw_user_id)
        except (TypeError, ValueError):
            return 0

    def _is_registered_command_message(self, content: str | None) -> bool:
        command_name = _extract_slash_command_name(content)
        if command_name is None:
            return False

        if self._slash_command_names:
            return command_name in self._slash_command_names

        return any(command_name == cmd.name.lower() for cmd in self.tree.get_commands())

    def _upsert_member_username(self, *, guild_id: int, user_id: int, username: str) -> bool:
        normalized = (username or "").strip()
        if not normalized:
            return False

        key = (int(guild_id), int(user_id))
        row = self.repo.user_levels.get(key)
        if row is None:
            self.repo.user_levels[key] = UserLevelRecord(
                guild_id=int(guild_id),
                user_id=int(user_id),
                xp=0,
                level=0,
                username=normalized,
            )
            return True

        if (row.username or "") == normalized:
            return False
        row.username = normalized
        return True

    async def _collect_guild_member_usernames(self, guild: Any) -> dict[int, str]:
        users: dict[int, str] = {}
        for member in list(getattr(guild, "members", []) or []):
            if getattr(member, "bot", False):
                continue
            username = _member_name(member)
            user_id = int(getattr(member, "id", 0) or 0)
            if user_id <= 0 or not username:
                continue
            users[user_id] = username

        expected_count = int(getattr(guild, "member_count", 0) or 0)
        if expected_count > 0 and len(users) >= expected_count:
            return users

        fetch_members = getattr(guild, "fetch_members", None)
        if not callable(fetch_members):
            return users

        intents = getattr(self, "intents", None)
        members_intent_enabled = bool(getattr(intents, "members", False))
        if not members_intent_enabled:
            return users

        try:
            async for member in fetch_members(limit=None):
                if getattr(member, "bot", False):
                    continue
                username = _member_name(member)
                user_id = int(getattr(member, "id", 0) or 0)
                if user_id <= 0 or not username:
                    continue
                users[user_id] = username
        except discord.ClientException as exc:
            if "Intents.members must be enabled" in str(exc):
                log.debug(
                    "Skipping guild member fetch because members intent is disabled for guild_id=%s",
                    getattr(guild, "id", None),
                )
            else:
                log.debug("Guild member fetch failed for guild_id=%s", getattr(guild, "id", None), exc_info=True)
        except Exception:
            log.debug("Guild member fetch failed for guild_id=%s", getattr(guild, "id", None), exc_info=True)

        return users

    async def _sync_guild_usernames(self, guild: Any, *, force: bool = False) -> tuple[int, int]:
        guild_id = int(getattr(guild, "id", 0) or 0)
        if guild_id <= 0:
            return (0, 0)

        now_mono = time.monotonic()
        next_due = self._username_sync_next_run_by_guild.get(guild_id, 0.0)
        if not force and now_mono < next_due:
            return (0, 0)

        usernames = await self._collect_guild_member_usernames(guild)
        self._username_sync_next_run_by_guild[guild_id] = now_mono + USERNAME_SYNC_RESCAN_SECONDS
        if not usernames:
            return (0, 0)

        changed = 0
        async with self._state_lock:
            for user_id, username in usernames.items():
                if self._upsert_member_username(guild_id=guild_id, user_id=user_id, username=username):
                    changed += 1
            if changed > 0:
                self._level_state_dirty = True
        return (len(usernames), changed)

    @staticmethod
    def _bot_message_cache_key(guild_id: int, channel_id: int, bot_user_id: int, message_id: int) -> str:
        return (
            f"{BOT_MESSAGE_CACHE_PREFIX}:{int(guild_id)}:{int(channel_id)}:"
            f"{int(bot_user_id)}:{int(message_id)}"
        )

    def _track_bot_message(self, message: Any) -> None:
        message_id = int(getattr(message, "id", 0) or 0)
        if message_id <= 0:
            return

        channel = getattr(message, "channel", None)
        channel_id = int(getattr(channel, "id", 0) or 0)
        if channel_id <= 0:
            return

        guild = getattr(message, "guild", None)
        if guild is None and channel is not None:
            guild = getattr(channel, "guild", None)
        guild_id = int(getattr(guild, "id", 0) or 0)
        if guild_id <= 0:
            return

        author = getattr(message, "author", None)
        bot_user_id = int(getattr(author, "id", 0) or 0)
        if bot_user_id <= 0:
            bot_user_id = self._current_bot_user_id()
        if bot_user_id <= 0:
            return

        payload_hash = sha256_text(f"{bot_user_id}:{message_id}")
        self.repo.upsert_debug_cache(
            cache_key=self._bot_message_cache_key(guild_id, channel_id, bot_user_id, message_id),
            kind=BOT_MESSAGE_KIND,
            guild_id=guild_id,
            raid_id=channel_id,
            message_id=message_id,
            payload_hash=payload_hash,
        )

        # Keep only the newest bot-message index rows per channel to avoid unbounded DB churn.
        indexed_rows = self.repo.list_debug_cache(kind=BOT_MESSAGE_KIND, guild_id=guild_id, raid_id=channel_id)
        if len(indexed_rows) <= BOT_MESSAGE_INDEX_MAX_PER_CHANNEL:
            return
        oldest_first = sorted(indexed_rows, key=lambda row: int(row.message_id))
        for stale_row in oldest_first[: max(0, len(oldest_first) - BOT_MESSAGE_INDEX_MAX_PER_CHANNEL)]:
            self.repo.delete_debug_cache(stale_row.cache_key)

    async def _send_channel_message(self, channel: Any, **kwargs: Any) -> Any | None:
        posted = await _safe_send_channel_message(channel, **kwargs)
        if posted is not None:
            self._track_bot_message(posted)
        return posted

    def _resolve_remote_target_by_name(self, raw_value: str) -> tuple[int | None, str | None]:
        value = (raw_value or "").strip()
        if not value:
            return None, "❌ Bitte einen Servernamen angeben."

        suffix_match = re.search(r"\((\d+)\)\s*$", value)
        if suffix_match:
            guild_id = int(suffix_match.group(1))
            guild = self.get_guild(guild_id)
            if guild is None:
                return None, "❌ Bot ist auf diesem Server nicht aktiv."
            return guild_id, None

        lowered = value.casefold()
        exact = [guild for guild in self.guilds if (guild.name or "").strip().casefold() == lowered]
        if len(exact) == 1:
            return int(exact[0].id), None
        if len(exact) > 1:
            return None, "❌ Mehrdeutiger Servername. Bitte genauer eingeben."

        partial = [guild for guild in self.guilds if lowered in (guild.name or "").strip().casefold()]
        if len(partial) == 1:
            return int(partial[0].id), None
        if len(partial) > 1:
            return None, "❌ Mehrere passende Server gefunden. Bitte genauer eingeben."

        return None, "❌ Ungültiger Servername / kein passender Server gefunden."

    def _remote_guild_autocomplete_choices(self, query: str) -> list[app_commands.Choice[str]]:
        search = (query or "").strip().casefold()
        guilds = sorted(self.guilds, key=lambda guild: ((guild.name or "").casefold(), int(guild.id)))
        name_counts: dict[str, int] = {}
        for guild in guilds:
            key = ((guild.name or "").strip() or str(guild.id)).casefold()
            name_counts[key] = name_counts.get(key, 0) + 1

        choices: list[app_commands.Choice[str]] = []
        for guild in guilds:
            guild_name = (guild.name or "").strip() or f"Server {guild.id}"
            unique_key = guild_name.casefold()
            value = guild_name if name_counts.get(unique_key, 0) == 1 else f"{guild_name} ({guild.id})"
            if search and search not in guild_name.casefold() and search not in value.casefold():
                continue
            choices.append(app_commands.Choice(name=value[:100], value=value))
            if len(choices) >= 25:
                break
        return choices

    async def _get_text_channel(self, channel_id: int | None):
        if not channel_id:
            return None
        channel = self.get_channel(int(channel_id))
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            return channel
        try:
            fetched = await self.fetch_channel(int(channel_id))
        except Exception:
            return None
        if isinstance(fetched, (discord.TextChannel, discord.Thread)):
            return fetched
        return None

    async def _mirror_debug_payload(
        self,
        *,
        debug_channel_id: int,
        cache_key: str,
        kind: str,
        guild_id: int,
        raid_id: int | None,
        content: str,
    ) -> None:
        if debug_channel_id <= 0:
            return
        channel = await self._get_text_channel(debug_channel_id)
        if channel is None:
            return

        payload = content if len(content) <= 1900 else f"{content[:1897]}..."
        payload_hash = sha256_text(payload)
        cached = self.repo.get_debug_cache(cache_key)

        if cached is not None and cached.payload_hash == payload_hash and cached.message_id:
            existing = await _safe_fetch_message(channel, cached.message_id)
            if existing is not None:
                return

        if cached is not None and cached.message_id:
            existing = await _safe_fetch_message(channel, cached.message_id)
            if existing is not None:
                edited = await _safe_edit_message(existing, content=payload)
                if edited:
                    self.repo.upsert_debug_cache(
                        cache_key=cache_key,
                        kind=kind,
                        guild_id=guild_id,
                        raid_id=raid_id,
                        message_id=existing.id,
                        payload_hash=payload_hash,
                    )
                    return

        posted = await self._send_channel_message(channel, content=payload)
        if posted is None:
            return
        self.repo.upsert_debug_cache(
            cache_key=cache_key,
            kind=kind,
            guild_id=guild_id,
            raid_id=raid_id,
            message_id=posted.id,
            payload_hash=payload_hash,
        )

    def _planner_embed(self, raid: RaidRecord):
        counts = planner_counts(self.repo, raid.id)
        day_users, time_users = self.repo.vote_user_sets(raid.id)
        day_voters = set().union(*day_users.values()) if day_users else set()
        time_voters = set().union(*time_users.values()) if time_users else set()
        complete_voters = day_voters.intersection(time_voters)

        day_lines = [
            f"• **{label}** — `{count}`"
            for label, count in sorted(counts["day"].items(), key=lambda item: (-item[1], item[0].lower()))
        ]
        time_lines = [
            f"• **{label}** — `{count}`"
            for label, count in sorted(counts["time"].items(), key=lambda item: (-item[1], item[0].lower()))
        ]
        embed = discord.Embed(
            title=f"🗓️ Raid Planer: {raid.dungeon}",
            description=f"Raid ID: `{raid.display_id}`",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Min Spieler pro Slot", value=str(raid.min_players), inline=True)
        embed.add_field(name="📅 Tage Votes", value="\n".join(day_lines) if day_lines else "—", inline=False)
        embed.add_field(name="🕒 Uhrzeiten Votes", value="\n".join(time_lines) if time_lines else "—", inline=False)
        embed.add_field(
            name="✅ Vollständig abgestimmt (Tag + Zeit)",
            value=self._plain_user_list_for_embed(raid.guild_id, complete_voters),
            inline=False,
        )
        embed.set_footer(text="Wähle Tag und Uhrzeit. Namensliste ohne @-Mention.")
        return embed

    def _plain_user_list_for_embed(self, guild_id: int, user_ids: set[int], *, limit: int = 30) -> str:
        if not user_ids:
            return "—"

        guild = self.get_guild(guild_id)
        labels: list[str] = []
        for user_id in sorted(user_ids):
            label: str | None = None
            if guild is not None:
                member = guild.get_member(int(user_id))
                if member is not None:
                    label = _member_name(member)
            if not label:
                row = self.repo.user_levels.get((int(guild_id), int(user_id)))
                if row is not None:
                    label = (row.username or "").strip() or None
            labels.append(label or f"User {user_id}")

        unique_labels = sorted(set(labels), key=lambda value: value.casefold())
        lines = [f"• {label}" for label in unique_labels]
        text = "\n".join(lines[:limit])
        if len(lines) > limit:
            text += f"\n... +{len(lines) - limit} weitere"
        if len(text) > 1024:
            text = text[:1021] + "..."
        return text

    async def _refresh_planner_message(self, raid_id: int):
        raid = self.repo.get_raid(raid_id)
        if raid is None or raid.status != "open":
            return None

        channel = await self._get_text_channel(raid.channel_id)
        if channel is None:
            return None

        days, times = self.repo.list_raid_options(raid.id)
        if not days or not times:
            return None

        embed = self._planner_embed(raid)
        view = RaidVoteView(self, raid.id, days, times)

        if raid.message_id:
            existing = await _safe_fetch_message(channel, raid.message_id)
            if existing is not None:
                edited = await _safe_edit_message(existing, embed=embed, view=view, content=None)
                if edited:
                    return existing

        posted = await self._send_channel_message(channel, embed=embed, view=view)
        if posted is None:
            return None
        self.repo.set_raid_message_id(raid.id, posted.id)
        self.add_view(view, message_id=posted.id)
        return posted

    async def _close_planner_message(
        self,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int | None,
        reason: str,
        attendance_rows: int | None = None,
    ) -> None:
        if not message_id:
            return
        channel = await self._get_text_channel(channel_id)
        if channel is None:
            return
        message = await _safe_fetch_message(channel, message_id)
        if message is None:
            return

        title = f"Raid geschlossen: {reason}"
        description = f"Guild `{guild_id}`"
        if attendance_rows is not None:
            description += f"\nAttendance Rows: `{attendance_rows}`"
        embed = discord.Embed(title=title, description=description, color=discord.Color.red())
        await _safe_edit_message(message, embed=embed, view=None, content=None)

    async def _delete_slot_message(self, row: RaidPostedSlotRecord) -> bool:
        if row.channel_id is None or row.message_id is None:
            return False
        channel = await self._get_text_channel(row.channel_id)
        if channel is None:
            return False
        message = await _safe_fetch_message(channel, row.message_id)
        if message is None:
            return False
        return await _safe_delete_message(message)

    def _indexed_bot_message_ids_for_channel(self, guild_id: int, channel_id: int) -> set[int]:
        message_ids: set[int] = set()
        for raid in self.repo.list_open_raids(guild_id):
            if raid.channel_id == channel_id and raid.message_id:
                message_ids.add(int(raid.message_id))

        for row in self.repo.raid_posted_slots.values():
            if row.channel_id == channel_id and row.message_id:
                message_ids.add(int(row.message_id))

        settings = self.repo.settings.get(int(guild_id))
        if settings and settings.raidlist_channel_id == channel_id and settings.raidlist_message_id:
            message_ids.add(int(settings.raidlist_message_id))

        for row in self.repo.list_debug_cache(kind=BOT_MESSAGE_KIND, guild_id=guild_id, raid_id=channel_id):
            if row.message_id:
                message_ids.add(int(row.message_id))
        return message_ids

    def _clear_bot_message_index_for_id(self, *, guild_id: int, channel_id: int, message_id: int) -> None:
        bot_user_id = self._current_bot_user_id()
        cache_key = self._bot_message_cache_key(guild_id, channel_id, bot_user_id, message_id)
        self.repo.delete_debug_cache(cache_key)

    def _clear_known_message_refs_for_id(self, *, guild_id: int, channel_id: int, message_id: int) -> None:
        for raid in self.repo.list_open_raids(guild_id):
            if raid.channel_id == channel_id and int(raid.message_id or 0) == int(message_id):
                raid.message_id = None

        for row in self.repo.raid_posted_slots.values():
            if row.channel_id == channel_id and int(row.message_id or 0) == int(message_id):
                row.message_id = None

        settings = self.repo.settings.get(int(guild_id))
        if (
            settings is not None
            and settings.raidlist_channel_id == channel_id
            and int(settings.raidlist_message_id or 0) == int(message_id)
        ):
            settings.raidlist_message_id = None

    async def _delete_indexed_bot_messages_in_channel(self, channel: Any, *, history_limit: int = 5000) -> int:
        guild = getattr(channel, "guild", None)
        guild_id = int(getattr(guild, "id", 0) or 0)
        channel_id = int(getattr(channel, "id", 0) or 0)
        if guild_id <= 0 or channel_id <= 0:
            return 0

        bot_user_id = self._current_bot_user_id()
        if bot_user_id <= 0:
            return 0

        limit = max(1, min(5000, int(history_limit)))
        indexed_ids = self._indexed_bot_message_ids_for_channel(guild_id, channel_id)
        if not indexed_ids:
            return 0

        deleted = 0
        for message_id in sorted(indexed_ids, reverse=True)[:limit]:
            try:
                message = await _safe_fetch_message(channel, int(message_id))
                if message is None:
                    self._clear_bot_message_index_for_id(guild_id=guild_id, channel_id=channel_id, message_id=message_id)
                    self._clear_known_message_refs_for_id(guild_id=guild_id, channel_id=channel_id, message_id=message_id)
                    continue

                author_id = int(getattr(getattr(message, "author", None), "id", 0) or 0)
                if author_id > 0 and author_id != bot_user_id:
                    self._clear_bot_message_index_for_id(guild_id=guild_id, channel_id=channel_id, message_id=message_id)
                    continue

                if await _safe_delete_message(message):
                    deleted += 1
                self._clear_bot_message_index_for_id(guild_id=guild_id, channel_id=channel_id, message_id=message_id)
                self._clear_known_message_refs_for_id(guild_id=guild_id, channel_id=channel_id, message_id=message_id)
            except Exception:
                log.exception(
                    "Failed indexed bot-message delete channel_id=%s message_id=%s",
                    channel_id,
                    int(message_id),
                )
                self._clear_bot_message_index_for_id(guild_id=guild_id, channel_id=channel_id, message_id=message_id)
        return deleted

    async def _delete_bot_messages_in_channel(
        self,
        channel: Any,
        *,
        history_limit: int = 5000,
        scan_history: bool = True,
    ) -> int:
        bot_user_id = self._current_bot_user_id()
        if bot_user_id <= 0:
            return 0

        limit = max(1, min(5000, int(history_limit)))
        deleted = await self._delete_indexed_bot_messages_in_channel(channel, history_limit=limit)
        if not scan_history or deleted >= limit:
            return min(limit, deleted)

        remaining = max(0, limit - deleted)
        if remaining <= 0:
            return min(limit, deleted)

        history = getattr(channel, "history", None)
        if history is None:
            return min(limit, deleted)

        guild_id = int(getattr(getattr(channel, "guild", None), "id", 0) or 0)
        channel_id = int(getattr(channel, "id", 0) or 0)
        try:
            async for message in history(limit=remaining):
                if getattr(getattr(message, "author", None), "id", None) != bot_user_id:
                    continue
                message_id = int(getattr(message, "id", 0) or 0)
                if await _safe_delete_message(message):
                    deleted += 1
                if guild_id > 0 and channel_id > 0 and message_id > 0:
                    self._clear_bot_message_index_for_id(
                        guild_id=guild_id,
                        channel_id=channel_id,
                        message_id=message_id,
                    )
                    self._clear_known_message_refs_for_id(
                        guild_id=guild_id,
                        channel_id=channel_id,
                        message_id=message_id,
                    )
        except Exception:
            log.exception(
                "Failed to sweep bot-authored messages in channel_id=%s",
                getattr(channel, "id", None),
            )
        return min(limit, deleted)

    async def _rebuild_memberlists_for_guild(self, guild_id: int, *, participants_channel: Any) -> MemberlistRebuildStats:
        raids = list(self.repo.list_open_raids(guild_id))
        cleared_slot_rows = 0
        deleted_slot_messages = 0

        for raid in raids:
            slot_rows = list(self.repo.list_posted_slots(raid.id).values())
            for row in slot_rows:
                if await self._delete_slot_message(row):
                    deleted_slot_messages += 1
                self.repo.delete_posted_slot(row.id)
                cleared_slot_rows += 1

        deleted_legacy_messages = await self._delete_bot_messages_in_channel(participants_channel, history_limit=5000)

        created = 0
        updated = 0
        deleted = 0
        for raid in raids:
            c_count, u_count, d_count = await self._sync_memberlist_messages_for_raid(raid.id)
            created += c_count
            updated += u_count
            deleted += d_count

        return MemberlistRebuildStats(
            raids=len(raids),
            cleared_slot_rows=cleared_slot_rows,
            deleted_slot_messages=deleted_slot_messages,
            deleted_legacy_messages=deleted_legacy_messages,
            created=created,
            updated=updated,
            deleted=deleted,
        )

    async def _ensure_temp_role(self, raid: RaidRecord):
        if raid.min_players <= 0:
            return None
        guild = self.get_guild(raid.guild_id)
        if guild is None:
            return None

        if raid.temp_role_id:
            role = guild.get_role(int(raid.temp_role_id))
            if role is not None:
                return role

        role_name = f"DMW Raid: {raid.dungeon}"
        role = discord.utils.get(guild.roles, name=role_name)
        if role is not None:
            raid.temp_role_id = role.id
            raid.temp_role_created = False
            return role

        try:
            role = await guild.create_role(name=role_name, mentionable=True, reason="DMW Raid temp role")
        except Exception:
            return None

        raid.temp_role_id = role.id
        raid.temp_role_created = True
        return role

    async def _cleanup_temp_role(self, raid: RaidRecord) -> None:
        if not raid.temp_role_id:
            return
        guild = self.get_guild(raid.guild_id)
        if guild is None:
            return
        role = guild.get_role(int(raid.temp_role_id))
        if role is None:
            return

        for member in list(role.members):
            try:
                await member.remove_roles(role, reason="DMW Raid finished")
            except Exception:
                continue

        if raid.temp_role_created:
            try:
                await role.delete(reason="DMW Raid finished")
            except Exception:
                pass

    async def _sync_memberlist_messages_for_raid(
        self,
        raid_id: int,
        *,
        recreate_existing: bool = False,
    ) -> tuple[int, int, int]:
        raid = self.repo.get_raid(raid_id)
        if raid is None or raid.status != "open":
            return (0, 0, 0)

        settings = self.repo.ensure_settings(raid.guild_id)
        if not settings.participants_channel_id:
            return (0, 0, 0)

        participants_channel = await self._get_text_channel(settings.participants_channel_id)
        if participants_channel is None:
            return (0, 0, 0)

        days, times = self.repo.list_raid_options(raid.id)
        day_users, time_users = self.repo.vote_user_sets(raid.id)
        threshold = memberlist_threshold(raid.min_players)
        qualified_slots, _ = compute_qualified_slot_users(
            days=days,
            times=times,
            day_users=day_users,
            time_users=time_users,
            threshold=threshold,
        )

        existing_rows = self.repo.list_posted_slots(raid.id)
        active_keys: set[tuple[str, str]] = set()
        created = 0
        updated = 0
        deleted = 0
        debug_lines: list[str] = []
        role = await self._ensure_temp_role(raid)

        for (day_label, time_label), users in qualified_slots.items():
            active_keys.add((day_label, time_label))
            content = slot_text(raid, day_label, time_label, users)
            if role is not None:
                content = f"{content}\n{role.mention}"
            debug_lines.append(f"- {day_label} {time_label}: {', '.join(f'<@{u}>' for u in users)}")
            row = existing_rows.get((day_label, time_label))
            old_msg_for_recreate = None

            edited = False
            if row is not None and row.message_id is not None and not recreate_existing:
                existing_channel = await self._get_text_channel(row.channel_id or participants_channel.id)
                if existing_channel is not None:
                    old_msg = await _safe_fetch_message(existing_channel, row.message_id)
                    if old_msg is not None:
                        edited = await _safe_edit_message(
                            old_msg,
                            content=content,
                            allowed_mentions=discord.AllowedMentions(users=True, roles=True),
                        )
                        if edited:
                            self.repo.upsert_posted_slot(
                                raid_id=raid.id,
                                day_label=day_label,
                                time_label=time_label,
                                channel_id=existing_channel.id,
                                message_id=old_msg.id,
                            )
                            updated += 1

            if row is not None and row.message_id is not None and recreate_existing:
                existing_channel = await self._get_text_channel(row.channel_id or participants_channel.id)
                if existing_channel is not None:
                    old_msg_for_recreate = await _safe_fetch_message(existing_channel, row.message_id)

            if edited:
                continue

            new_msg = await self._send_channel_message(
                participants_channel,
                content=content,
                allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            )
            if new_msg is None:
                continue
            self.repo.upsert_posted_slot(
                raid_id=raid.id,
                day_label=day_label,
                time_label=time_label,
                channel_id=participants_channel.id,
                message_id=new_msg.id,
            )
            if row is None:
                created += 1
            else:
                updated += 1

            if old_msg_for_recreate is not None and getattr(old_msg_for_recreate, "id", None) != getattr(new_msg, "id", None):
                await _safe_delete_message(old_msg_for_recreate)

        for key, row in list(existing_rows.items()):
            if key in active_keys:
                continue
            await self._delete_slot_message(row)
            self.repo.delete_posted_slot(row.id)
            deleted += 1

        debug_body = (
            f"Memberlist Debug Guild `{raid.guild_id}` Raid `{raid.display_id}`\n"
            + ("\n".join(debug_lines) if debug_lines else "Keine qualifizierten Slots.")
        )
        await self._mirror_debug_payload(
            debug_channel_id=int(self.config.memberlist_debug_channel_id),
            cache_key=f"memberlist:{raid.guild_id}:{raid.id}",
            kind="memberlist",
            guild_id=raid.guild_id,
            raid_id=raid.id,
            content=debug_body,
        )

        return (created, updated, deleted)

    async def _refresh_raidlist_for_guild(self, guild_id: int, *, force: bool = False) -> bool:
        settings = self.repo.ensure_settings(guild_id)
        if not settings.raidlist_channel_id:
            return False

        guild = self.get_guild(guild_id)
        guild_name = guild.name if guild is not None else (settings.guild_name or str(guild_id))
        render = render_raidlist(guild_id, guild_name, self.repo.list_open_raids(guild_id))
        debug_payload = f"Raidlist Debug Guild `{guild_id}` ({guild_name})\n{render.title}\n{render.body}"

        if not force and self._raidlist_hash_by_guild.get(guild_id) == render.payload_hash:
            await self._mirror_debug_payload(
                debug_channel_id=int(self.config.raidlist_debug_channel_id),
                cache_key=f"raidlist:{guild_id}:0",
                kind="raidlist",
                guild_id=guild_id,
                raid_id=None,
                content=debug_payload,
            )
            return False

        channel = await self._get_text_channel(settings.raidlist_channel_id)
        if channel is None:
            return False

        content = f"**{render.title}**\n{render.body}"
        if settings.raidlist_message_id:
            message = await _safe_fetch_message(channel, settings.raidlist_message_id)
            if message is not None:
                if await _safe_edit_message(message, content=content):
                    self._raidlist_hash_by_guild[guild_id] = render.payload_hash
                    await self._mirror_debug_payload(
                        debug_channel_id=int(self.config.raidlist_debug_channel_id),
                        cache_key=f"raidlist:{guild_id}:0",
                        kind="raidlist",
                        guild_id=guild_id,
                        raid_id=None,
                        content=debug_payload,
                    )
                    return True

        posted = await self._send_channel_message(channel, content=content)
        if posted is None:
            return False
        settings.raidlist_message_id = posted.id
        self._raidlist_hash_by_guild[guild_id] = render.payload_hash
        await self._mirror_debug_payload(
            debug_channel_id=int(self.config.raidlist_debug_channel_id),
            cache_key=f"raidlist:{guild_id}:0",
            kind="raidlist",
            guild_id=guild_id,
            raid_id=None,
            content=debug_payload,
        )
        return True

    async def _schedule_raidlist_refresh(self, guild_id: int) -> None:
        await self.raidlist_updater.mark_dirty(guild_id)

    async def _force_raidlist_refresh(self, guild_id: int) -> None:
        await self._refresh_raidlist_for_guild(guild_id, force=True)

    async def _refresh_raidlist_for_guild_persisted(self, guild_id: int) -> None:
        async with self._state_lock:
            await self._refresh_raidlist_for_guild(guild_id)
            persisted = await self._persist()
        if not persisted:
            log.warning("Debounced raidlist refresh persisted failed for guild %s", guild_id)

    async def _refresh_raidlists_for_all_guilds(self, *, force: bool) -> None:
        guild_ids = set(self.repo.settings.keys())
        guild_ids.update(raid.guild_id for raid in self.repo.list_open_raids())
        for guild_id in sorted(guild_ids):
            await self._refresh_raidlist_for_guild(guild_id, force=force)

    async def _sync_vote_ui_after_change(self, raid_id: int) -> None:
        raid = self.repo.get_raid(raid_id)
        if raid is None or raid.status != "open":
            return
        await self._refresh_planner_message(raid.id)
        await self._sync_memberlist_messages_for_raid(raid.id)
        await self._schedule_raidlist_refresh(raid.guild_id)

    async def _finish_raid_interaction(self, interaction, *, raid_id: int, deferred: bool) -> None:
        async with self._state_lock:
            raid = self.repo.get_raid(raid_id)
            if raid is None:
                msg = "Raid existiert nicht mehr."
                if deferred:
                    await _safe_followup(interaction, msg, ephemeral=True)
                else:
                    await self._reply(interaction, msg, ephemeral=True)
                return

            slot_rows = list(self.repo.list_posted_slots(raid.id).values())
            planner_message_id = raid.message_id
            planner_channel_id = raid.channel_id
            guild_id = raid.guild_id
            display_id = raid.display_id

            result = finish_raid(self.repo, raid_id=raid.id, actor_user_id=interaction.user.id)
            if not result.success:
                if result.reason == "only_creator":
                    msg = "Nur der Raid-Ersteller darf den Raid beenden."
                else:
                    msg = "Raid konnte nicht beendet werden."
                if deferred:
                    await _safe_followup(interaction, msg, ephemeral=True)
                else:
                    await self._reply(interaction, msg, ephemeral=True)
                return

            await self._cleanup_temp_role(raid)
            for row in slot_rows:
                await self._delete_slot_message(row)

            await self._close_planner_message(
                guild_id=guild_id,
                channel_id=planner_channel_id,
                message_id=planner_message_id,
                reason="beendet",
                attendance_rows=result.attendance_rows,
            )
            await self._force_raidlist_refresh(guild_id)
            persisted = await self._persist()

        if not persisted:
            msg = "Raid beendet, aber DB-Speicherung fehlgeschlagen."
        else:
            msg = f"Raid `{display_id}` beendet. Attendance Rows: `{result.attendance_rows}`"
        if deferred:
            await _safe_followup(interaction, msg, ephemeral=True)
        else:
            await self._reply(interaction, msg, ephemeral=True)

    async def _cancel_raids_for_guild(self, guild_id: int, *, reason: str) -> int:
        raids = list(self.repo.list_open_raids(guild_id))
        for raid in raids:
            slot_rows = list(self.repo.list_posted_slots(raid.id).values())
            await self._close_planner_message(
                guild_id=raid.guild_id,
                channel_id=raid.channel_id,
                message_id=raid.message_id,
                reason=reason,
            )
            await self._cleanup_temp_role(raid)
            for row in slot_rows:
                await self._delete_slot_message(row)

        count = cancel_all_open_raids(self.repo, guild_id=guild_id)
        await self._force_raidlist_refresh(guild_id)
        return count

    def _register_commands(self) -> None:
        def _can_use_privileged(interaction: Any) -> bool:
            return self._is_privileged_user(getattr(getattr(interaction, "user", None), "id", None))

        async def _require_privileged(interaction: Any) -> bool:
            if _can_use_privileged(interaction):
                return True
            user_id = getattr(getattr(interaction, "user", None), "id", None)
            log.warning(
                "Privileged command denied user_id=%s configured_user_id=%s owner_ids=%s command=%s",
                user_id,
                int(getattr(self.config, "privileged_user_id", DEFAULT_PRIVILEGED_USER_ID)),
                sorted(self._application_owner_ids),
                getattr(getattr(interaction, "command", None), "name", None),
            )
            await self._reply(interaction, "❌ Nur für den Debug-Owner erlaubt.", ephemeral=True)
            return False

        @self.tree.command(
            name="settings",
            description="Setzt Umfragen-/Teilnehmerlisten-/Raidlist-Channel und Feature-Toggles.",
        )
        @_admin_or_privileged_check()
        async def settings_cmd(interaction):
            if not interaction.guild:
                await self._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
                return

            async with self._state_lock:
                settings = self.repo.ensure_settings(interaction.guild.id, interaction.guild.name)
                feature_settings = self._get_guild_feature_settings(interaction.guild.id)
            view = SettingsView(self, guild_id=interaction.guild.id)
            sent = await _safe_send_initial(
                interaction,
                "Settings",
                ephemeral=True,
                embed=_settings_embed(settings, interaction.guild.name, feature_settings),
                view=view,
            )
            if not sent:
                await self._reply(interaction, "Settings-Ansicht konnte nicht geoeffnet werden.", ephemeral=True)

        @self.tree.command(name="status", description="Zeigt den aktuellen Bot-Status")
        async def status_cmd(interaction):
            if not interaction.guild:
                await self._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
                return

            settings = self.repo.ensure_settings(interaction.guild.id, interaction.guild.name)
            feature_settings = self._get_guild_feature_settings(interaction.guild.id)
            open_raids = self.repo.list_open_raids(interaction.guild.id)
            self_test_ok = self.last_self_test_ok_at.isoformat() if self.last_self_test_ok_at else "-"
            self_test_err = self.last_self_test_error or "-"
            await self._reply(
                interaction,
                (
                    f"Guild: **{interaction.guild.name}**\n"
                    f"Privileged User ID (configured): `{int(getattr(self.config, 'privileged_user_id', DEFAULT_PRIVILEGED_USER_ID))}`\n"
                    f"Level Persist Interval (s): `{int(self.config.level_persist_interval_seconds)}`\n"
                    f"Levelsystem: `{_on_off(feature_settings.leveling_enabled)}`\n"
                    f"Levelup Nachrichten: `{_on_off(feature_settings.levelup_messages_enabled)}`\n"
                    f"Nanomon Reply: `{_on_off(feature_settings.nanomon_reply_enabled)}`\n"
                    f"Approved Reply: `{_on_off(feature_settings.approved_reply_enabled)}`\n"
                    f"Message XP Interval (s): `{int(feature_settings.message_xp_interval_seconds)}`\n"
                    f"Levelup Cooldown (s): `{int(feature_settings.levelup_message_cooldown_seconds)}`\n"
                    f"Umfragen Channel: `{settings.planner_channel_id}`\n"
                    f"Raid Teilnehmerlisten Channel: `{settings.participants_channel_id}`\n"
                    f"Raidlist Channel: `{settings.raidlist_channel_id}`\n"
                    f"Raidlist Message: `{settings.raidlist_message_id}`\n"
                    f"Open Raids: `{len(open_raids)}`\n"
                    f"Self-Test OK: `{self_test_ok}`\n"
                    f"Self-Test Error: `{self_test_err}`"
                ),
                ephemeral=True,
            )

        @self.tree.command(name="help", description="Zeigt verfuegbare Commands")
        async def help_cmd(interaction):
            names = self._public_help_command_names()
            await self._reply(
                interaction,
                "Verfuegbare Commands:\n" + "\n".join(f"- /{name}" for name in names),
                ephemeral=True,
            )

        @self.tree.command(name="help2", description="Postet eine kurze Anleitung")
        async def help2_cmd(interaction):
            if not isinstance(interaction.channel, discord.TextChannel):
                await self._reply(interaction, "Nur im Textchannel nutzbar.", ephemeral=True)
                return
            await self._send_channel_message(
                interaction.channel,
                content=(
                    "1) /settings\n"
                    "2) /raidplan\n"
                    "3) Abstimmung im Raid-Post per Selects\n"
                    "4) /raidlist fuer Live-Refresh\n"
                    "5) Raid beenden ueber Button oder /raid_finish\n"
                    "6) /purgebot scope=channel|server fuer Bot-Nachrichten-Reset"
                ),
            )
            await self._reply(interaction, "Anleitung gepostet.", ephemeral=True)

        @self.tree.command(name="restart", description="Stoppt den Prozess (Runner startet neu)")
        async def restart_cmd(interaction):
            if not await _require_privileged(interaction):
                return
            await self._reply(interaction, "Neustart wird eingeleitet.", ephemeral=True)
            await self.close()

        @self.tree.command(name="dungeonlist", description="Aktive Dungeons")
        async def dungeonlist_cmd(interaction):
            names = list_active_dungeons(self.repo)
            if not names:
                await self._reply(interaction, "Keine aktiven Dungeons.", ephemeral=True)
                return
            await self._reply(interaction, "\n".join(f"- {name}" for name in names), ephemeral=True)

        @self.tree.command(name="raidplan", description="Erstellt einen Raid Plan (Modal)")
        @app_commands.describe(dungeon="Dungeon Name")
        async def raidplan_cmd(interaction, dungeon: str):
            if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
                await self._reply(interaction, "Nur im Text-Serverchannel nutzbar.", ephemeral=True)
                return

            async with self._state_lock:
                settings = self.repo.ensure_settings(interaction.guild.id, interaction.guild.name)
                if not settings.planner_channel_id or not settings.participants_channel_id:
                    await self._reply(
                        interaction,
                        "Bitte zuerst /settings konfigurieren (Umfragen + Teilnehmerlisten Channel).",
                        ephemeral=True,
                    )
                    return

                try:
                    defaults = build_raid_plan_defaults(
                        self.repo,
                        guild_id=interaction.guild.id,
                        guild_name=interaction.guild.name,
                        dungeon_name=dungeon,
                    )
                except ValueError as exc:
                    await self._reply(interaction, f"Fehler: {exc}", ephemeral=True)
                    return

            modal = RaidCreateModal(
                self,
                guild_id=interaction.guild.id,
                guild_name=interaction.guild.name,
                channel_id=int(settings.planner_channel_id),
                dungeon_name=dungeon,
                default_days=defaults.days,
                default_times=defaults.times,
                default_min_players=defaults.min_players,
            )
            try:
                await interaction.response.send_modal(modal)
            except Exception:
                await self._reply(interaction, "Raid-Modal konnte nicht geoeffnet werden.", ephemeral=True)

        @raidplan_cmd.autocomplete("dungeon")
        async def raidplan_dungeon_autocomplete(interaction, current: str):
            query = (current or "").strip().lower()
            rows = self.repo.list_active_dungeons()
            if query:
                rows = [row for row in rows if query in row.name.lower()]
            return [app_commands.Choice(name=row.name, value=row.name) for row in rows[:25]]

        @self.tree.command(name="raid_finish", description="Schliesst einen Raid und erstellt Attendance")
        async def raid_finish_cmd(interaction, raid_id: int):
            if not interaction.guild:
                await self._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
                return

            raid = self._find_open_raid_by_display_id(interaction.guild.id, raid_id)
            if raid is None:
                await self._reply(interaction, f"Kein offener Raid mit ID `{raid_id}` gefunden.", ephemeral=True)
                return
            await self._finish_raid_interaction(interaction, raid_id=raid.id, deferred=False)

        @self.tree.command(name="raidlist", description="Aktualisiert die Raidlist Nachricht")
        async def raidlist_cmd(interaction):
            if not interaction.guild:
                await self._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
                return
            async with self._state_lock:
                await self._force_raidlist_refresh(interaction.guild.id)
                persisted = await self._persist()
            if not persisted:
                await self._reply(interaction, "Raidlist Refresh fehlgeschlagen (DB).", ephemeral=True)
                return
            await self._reply(interaction, "Raidlist aktualisiert.", ephemeral=True)

        @self.tree.command(name="cancel_all_raids", description="Bricht alle offenen Raids ab")
        @_admin_or_privileged_check()
        async def cancel_all_raids_cmd(interaction):
            if not interaction.guild:
                await self._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
                return
            async with self._state_lock:
                count = await self._cancel_raids_for_guild(interaction.guild.id, reason="abgebrochen")
                persisted = await self._persist()
            if not persisted:
                await self._reply(interaction, "Raids gecancelt, aber DB-Speicherung fehlgeschlagen.", ephemeral=True)
                return
            await self._reply(interaction, f"{count} offene Raids gecancelt.", ephemeral=True)

        @self.tree.command(name="template_config", description="Aktiviert/Deaktiviert Templates")
        @_admin_or_privileged_check()
        @app_commands.describe(enabled="Templates aktiv")
        async def template_config_cmd(interaction, enabled: bool):
            if not interaction.guild:
                await self._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
                return
            async with self._state_lock:
                row = set_templates_enabled(self.repo, interaction.guild.id, interaction.guild.name, enabled)
                persisted = await self._persist()
            if not persisted:
                await self._reply(interaction, "Template-Config konnte nicht gespeichert werden.", ephemeral=True)
                return
            await self._reply(interaction, f"templates_enabled={row.templates_enabled}", ephemeral=True)

        @self.tree.command(name="purge", description="Loescht letzte N Nachrichten")
        @_admin_or_privileged_check()
        async def purge_cmd(interaction, amount: int = 10):
            channel = interaction.channel
            purge_fn = getattr(channel, "purge", None)
            if channel is None or not callable(purge_fn):
                await self._reply(interaction, "Nur im Textchannel nutzbar.", ephemeral=True)
                return
            await self._defer(interaction, ephemeral=True)
            amount = max(1, min(100, int(amount)))
            deleted = await purge_fn(limit=amount)
            await _safe_followup(interaction, f"{len(deleted)} Nachrichten geloescht.", ephemeral=True)

        @self.tree.command(name="purgebot", description="Loescht Bot-Nachrichten im Channel oder serverweit")
        @_admin_or_privileged_check()
        @app_commands.describe(
            scope="`channel` = aktueller Channel, `server` = alle Textchannels",
            limit="Max. gepruefte Nachrichten je Channel (1-5000)",
        )
        @app_commands.choices(
            scope=[
                app_commands.Choice(name="channel", value="channel"),
                app_commands.Choice(name="server", value="server"),
            ]
        )
        async def purgebot_cmd(interaction, scope: app_commands.Choice[str], limit: int = 500):
            if interaction.guild is None:
                await self._reply(interaction, "Nur im Server nutzbar.", ephemeral=True)
                return
            await self._defer(interaction, ephemeral=True)

            limit = max(1, min(5000, int(limit)))
            me = interaction.guild.me or interaction.guild.get_member(getattr(self.user, "id", 0))
            if me is None:
                await _safe_followup(interaction, "Bot-Mitglied im Server nicht gefunden.", ephemeral=True)
                return

            channels: list[discord.TextChannel]
            if scope.value == "channel":
                if not isinstance(interaction.channel, discord.TextChannel):
                    await _safe_followup(interaction, "Nur im Textchannel nutzbar.", ephemeral=True)
                    return
                channels = [interaction.channel]
            else:
                channels = [
                    channel
                    for channel in interaction.guild.text_channels
                    if channel.permissions_for(me).read_message_history
                ]

            total_deleted = 0
            touched_channels = 0
            scan_history = scope.value == "channel"
            scan_limit = limit if scan_history else min(limit, 150)
            for channel in channels:
                try:
                    perms = channel.permissions_for(me)
                    if not (perms.read_message_history and perms.manage_messages):
                        continue
                    deleted_here = await self._delete_bot_messages_in_channel(
                        channel,
                        history_limit=scan_limit,
                        scan_history=scan_history,
                    )
                    if deleted_here > 0:
                        total_deleted += deleted_here
                        touched_channels += 1
                except Exception:
                    log.exception(
                        "purgebot failed for channel_id=%s guild_id=%s",
                        getattr(channel, "id", None),
                        getattr(interaction.guild, "id", None),
                    )
                    continue

            where = "aktueller Channel" if scope.value == "channel" else f"{touched_channels} Channel(s)"
            await _safe_followup(
                interaction,
                (
                    f"{total_deleted} Bot-Nachrichten geloescht ({where}, "
                    f"Limit je Channel: {scan_limit}, History-Scan: {'an' if scan_history else 'reduziert'})."
                ),
                ephemeral=True,
            )

        @self.tree.command(name="remote_guilds", description="Zeigt bekannte Server für Fernwartung an (privileged).")
        async def remote_guilds_cmd(interaction):
            if not await _require_privileged(interaction):
                return
            await self._defer(interaction, ephemeral=True)
            guilds = sorted(self.guilds, key=lambda guild: ((guild.name or "").casefold(), int(guild.id)))
            if not guilds:
                await _safe_followup(interaction, "Keine verbundenen Server gefunden.", ephemeral=True)
                return
            lines: list[str] = []
            for guild in guilds[:50]:
                name = (guild.name or "").strip() or "(unbekannt)"
                lines.append(f"• **{name}**")
            await _safe_followup(interaction, "\n".join(lines), ephemeral=True)

        @self.tree.command(name="remote_cancel_all_raids", description="Fernwartung: Alle offenen Raids eines Servers abbrechen.")
        @app_commands.describe(guild_name="Zielservername (Autocomplete)")
        async def remote_cancel_all_raids_cmd(interaction, guild_name: str):
            if not await _require_privileged(interaction):
                return
            target, err = self._resolve_remote_target_by_name(guild_name)
            if target is None:
                await self._reply(interaction, err or "❌ Zielserver konnte nicht aufgelöst werden.", ephemeral=True)
                return

            await self._defer(interaction, ephemeral=True)
            async with self._state_lock:
                count = await self._cancel_raids_for_guild(target, reason="remote-abgebrochen")
                persisted = await self._persist()

            if not persisted:
                await _safe_followup(
                    interaction,
                    "Remote-Cancel ausgeführt, aber DB-Speicherung fehlgeschlagen.",
                    ephemeral=True,
                )
                return
            target_guild = self.get_guild(target)
            target_name = (target_guild.name if target_guild else None) or guild_name
            await _safe_followup(interaction, f"✅ {count} offene Raids in **{target_name}** abgebrochen.", ephemeral=True)

        @remote_cancel_all_raids_cmd.autocomplete("guild_name")
        async def remote_cancel_all_raids_autocomplete(interaction, current: str):
            if not _can_use_privileged(interaction):
                return []
            return self._remote_guild_autocomplete_choices(current)

        @self.tree.command(name="remote_raidlist", description="Fernwartung: Raidlist eines Zielservers neu aufbauen.")
        @app_commands.describe(guild_name="Zielservername (Autocomplete)")
        async def remote_raidlist_cmd(interaction, guild_name: str):
            if not await _require_privileged(interaction):
                return
            target, err = self._resolve_remote_target_by_name(guild_name)
            if target is None:
                await self._reply(interaction, err or "❌ Zielserver konnte nicht aufgelöst werden.", ephemeral=True)
                return

            await self._defer(interaction, ephemeral=True)
            async with self._state_lock:
                await self._refresh_raidlist_for_guild(target, force=True)
                persisted = await self._persist()

            if not persisted:
                await _safe_followup(interaction, "Remote-Raidlist-Refresh fehlgeschlagen (DB).", ephemeral=True)
                return

            target_guild = self.get_guild(target)
            target_name = (target_guild.name if target_guild else None) or guild_name
            await _safe_followup(interaction, f"✅ Raidlist für **{target_name}** aktualisiert.", ephemeral=True)

        @remote_raidlist_cmd.autocomplete("guild_name")
        async def remote_raidlist_autocomplete(interaction, current: str):
            if not _can_use_privileged(interaction):
                return []
            return self._remote_guild_autocomplete_choices(current)

        @self.tree.command(
            name="remote_rebuild_memberlists",
            description="Fernwartung: Teilnehmerlisten eines Zielservers vollständig neu aufbauen.",
        )
        @app_commands.describe(guild_name="Zielservername (Autocomplete)")
        async def remote_rebuild_memberlists_cmd(interaction, guild_name: str):
            if not await _require_privileged(interaction):
                return
            target, err = self._resolve_remote_target_by_name(guild_name)
            if target is None:
                await self._reply(interaction, err or "❌ Zielserver konnte nicht aufgelöst werden.", ephemeral=True)
                return

            await self._defer(interaction, ephemeral=True)
            async with self._state_lock:
                settings = self.repo.ensure_settings(target)
                if not settings.participants_channel_id:
                    await _safe_followup(
                        interaction,
                        "❌ Zielserver hat keinen Participants-Channel konfiguriert.",
                        ephemeral=True,
                    )
                    return
                participants_channel = await self._get_text_channel(settings.participants_channel_id)
                if participants_channel is None:
                    await _safe_followup(
                        interaction,
                        "❌ Participants-Channel des Zielservers ist nicht erreichbar.",
                        ephemeral=True,
                    )
                    return

                stats = await self._rebuild_memberlists_for_guild(target, participants_channel=participants_channel)
                persisted = await self._persist()

            if not persisted:
                await _safe_followup(
                    interaction,
                    "Remote-Rebuild ausgeführt, aber DB-Speicherung fehlgeschlagen.",
                    ephemeral=True,
                )
                return

            target_guild = self.get_guild(target)
            target_name = (target_guild.name if target_guild else None) or guild_name
            await _safe_followup(
                interaction,
                (
                    f"✅ Teilnehmerlisten für **{target_name}** neu aufgebaut.\n"
                    f"Raids: `{stats.raids}`\n"
                    f"Cleared Slot Rows: `{stats.cleared_slot_rows}`\n"
                    f"Deleted Slot Messages: `{stats.deleted_slot_messages}`\n"
                    f"Deleted Legacy Bot Messages: `{stats.deleted_legacy_messages}`\n"
                    f"Created: `{stats.created}` Updated: `{stats.updated}` Deleted: `{stats.deleted}`"
                ),
                ephemeral=True,
            )

        @remote_rebuild_memberlists_cmd.autocomplete("guild_name")
        async def remote_rebuild_memberlists_autocomplete(interaction, current: str):
            if not _can_use_privileged(interaction):
                return []
            return self._remote_guild_autocomplete_choices(current)

        @self.tree.command(name="backup_db", description="Schreibt ein SQL Backup")
        async def backup_db_cmd(interaction):
            if not await _require_privileged(interaction):
                return
            await self._defer(interaction, ephemeral=True)
            log.info(
                "Manual backup requested by user_id=%s guild_id=%s",
                getattr(interaction.user, "id", None),
                getattr(getattr(interaction, "guild", None), "id", None),
            )

            try:
                async with self._state_lock:
                    rows = self._snapshot_rows_by_table()
                out = await export_rows_to_sql(Path("backups/db_backup.sql"), rows_by_table=rows)
            except Exception:
                log.exception("Manual backup failed")
                await _safe_followup(interaction, "Backup fehlgeschlagen. Bitte Logs pruefen.", ephemeral=True)
                return

            log.info("Manual backup completed: %s", out.as_posix())
            await _safe_followup(interaction, f"Backup geschrieben: {out.as_posix()}", ephemeral=True)

    async def close(self) -> None:
        try:
            async with self._state_lock:
                await self._flush_level_state_if_due(force=True)
        except Exception:
            log.exception("Failed to flush pending level state during shutdown.")
        try:
            await self.task_registry.cancel_all()
        except Exception:
            pass
        try:
            for logger in self._discord_loggers:
                logger.removeHandler(self._discord_log_handler)
        except Exception:
            pass
        await super().close()


def run() -> int:
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))

    try:
        config = load_config()
    except ValueError as exc:
        log.error("Config error: %s", exc)
        return 1

    setup_logging(config.discord_log_level)
    if not config.discord_token:
        log.error("DISCORD_TOKEN missing")
        return 1

    repo = InMemoryRepository()
    bot = RewriteDiscordBot(repo=repo, config=config)

    try:
        bot.run(config.discord_token)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
