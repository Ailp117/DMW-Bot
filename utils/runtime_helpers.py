from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
import logging
import math
import re
from typing import Any
from zoneinfo import ZoneInfo

from bot.discord_api import app_commands, discord
from utils.leveling import xp_needed_for_level
from utils.time_utils import BERLIN_TIMEZONE, DEFAULT_TIMEZONE_NAME, berlin_now, berlin_now_utc

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
FEATURE_FLAG_RAID_REMINDER = 1 << 4
FEATURE_FLAG_MASK = 0xFF
FEATURE_MESSAGE_XP_SHIFT = 8
FEATURE_LEVELUP_COOLDOWN_SHIFT = 24
FEATURE_INTERVAL_MASK = 0xFFFF
BOT_MESSAGE_KIND = "bot_message"
BOT_MESSAGE_CACHE_PREFIX = "botmsg"
BOT_MESSAGE_INDEX_MAX_PER_CHANNEL = 400
SLOT_TEMP_ROLE_KIND = "slot_temp_role"
SLOT_TEMP_ROLE_CACHE_PREFIX = "slotrole"
RAID_REMINDER_KIND = "raid_reminder"
RAID_REMINDER_CACHE_PREFIX = "raidrem"
RAID_REMINDER_ADVANCE_SECONDS = 10 * 60
RAID_REMINDER_WORKER_SLEEP_SECONDS = 30
RAID_CALENDAR_CONFIG_KIND = "raid_calendar_cfg"
RAID_CALENDAR_CONFIG_CACHE_PREFIX = "raid_calendar_cfg"
RAID_CALENDAR_MESSAGE_KIND = "raid_calendar_msg"
RAID_CALENDAR_MESSAGE_CACHE_PREFIX = "raid_calendar_msg"
RAID_CALENDAR_GRID_COLUMNS = 7
RAID_CALENDAR_GRID_ROWS = 5
RAID_DATE_LOOKAHEAD_DAYS = 21
RAID_DATE_CACHE_DAYS_MAX = 25
INTEGRITY_CLEANUP_SLEEP_SECONDS = 15 * 60
USERNAME_SYNC_WORKER_SLEEP_SECONDS = 10 * 60
USERNAME_SYNC_RESCAN_SECONDS = 12 * 60 * 60
LOG_FORWARD_QUEUE_MAX_SIZE = 1000
PERSIST_FLUSH_MAX_ATTEMPTS = 3
PERSIST_FLUSH_RETRY_BASE_SECONDS = 0.1
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
MONTH_NAMES_DE = (
    "Januar",
    "Februar",
    "Maerz",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)

_RESPONSE_ERRORS = {"InteractionResponded", "HTTPException", "NotFound", "Forbidden"}
_DISCORD_LOG_LINE_PATTERN = re.compile(
    r"^\[(?P<timestamp>[^\]]+)\]\s+"
    r"(?P<level>[A-Z]+)\s+"
    r"src=(?P<source>[^|]+)\s+\|\s+"
    r"(?P<body>.*)$"
)
_SLOT_ROLE_NAME_PATTERN = re.compile(r"^DMW Raid (?P<display_id>\d+)\s+.+$")


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
    raid_reminder_enabled: bool = False


@dataclass(slots=True)
class CalendarEntry:
    entry_date: date
    label: str
    source: str = "generic"


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


def _round_xp_for_display(value: Any) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(parsed):
        return 0
    if parsed <= 0:
        return 0
    return int(math.floor(parsed + 0.5))


def _xp_progress_stats(total_xp: int, level: int) -> tuple[int, int, int]:
    safe_level = max(0, int(level))
    safe_total_xp = max(0, int(total_xp))
    start_xp = xp_needed_for_level(safe_level)
    next_xp = xp_needed_for_level(safe_level + 1)
    span = max(1, next_xp - start_xp)
    gained = max(0, min(span, safe_total_xp - start_xp))
    percent = int((gained / span) * 100)
    return (gained, span, percent)


def _render_xp_progress_bar(*, progress: int, total: int, width: int = 16) -> str:
    safe_total = max(1, int(total))
    safe_progress = max(0, min(safe_total, int(progress)))
    bar_width = max(8, int(width))
    filled = int(round((safe_progress / safe_total) * bar_width))
    filled = max(0, min(bar_width, filled))
    return f"[{'#' * filled}{'-' * (bar_width - filled)}]"


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


async def _safe_followup(interaction: Any, content: str | None, *, ephemeral: bool = False, **kwargs: Any) -> bool:
    followup = getattr(interaction, "followup", None)
    if followup is None:
        return False
    try:
        if content is None:
            await followup.send(ephemeral=ephemeral, **kwargs)
        else:
            await followup.send(content, ephemeral=ephemeral, **kwargs)
        return True
    except Exception as exc:
        _log_safe_wrapper_error("followup.send", exc)
        return False


async def _safe_send_initial(interaction: Any, content: str | None, *, ephemeral: bool = False, **kwargs: Any) -> bool:
    response = getattr(interaction, "response", None)
    if response is None:
        return False
    is_done = getattr(response, "is_done", None)
    if callable(is_done) and is_done():
        return await _safe_followup(interaction, content, ephemeral=ephemeral, **kwargs)

    try:
        if content is None:
            await response.send_message(ephemeral=ephemeral, **kwargs)
        else:
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


def _raid_weekday_short(weekday_index: int) -> str:
    names = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
    if 0 <= int(weekday_index) < len(names):
        return names[int(weekday_index)]
    return "??"


def _format_raid_date_label(value: date) -> str:
    return f"{value.isoformat()} ({_raid_weekday_short(value.weekday())})"


def _parse_raid_date_from_label(label: str) -> date | None:
    text = (label or "").strip()
    match_iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match_iso is not None:
        try:
            return date(int(match_iso.group(1)), int(match_iso.group(2)), int(match_iso.group(3)))
        except ValueError:
            return None

    match_dot = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if match_dot is not None:
        try:
            return date(int(match_dot.group(3)), int(match_dot.group(2)), int(match_dot.group(1)))
        except ValueError:
            return None
    return None


def _parse_raid_time_label(label: str) -> tuple[int, int] | None:
    text = (label or "").strip()
    match = re.search(r"^(\d{1,2})[:.](\d{2})$", text)
    if match is None:
        return None
    try:
        hour = int(match.group(1))
        minute = int(match.group(2))
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return (hour, minute)


def _month_start(value: date) -> date:
    return date(int(value.year), int(value.month), 1)


def _days_in_month(value: date) -> int:
    start = _month_start(value)
    if start.month == 12:
        next_start = date(start.year + 1, 1, 1)
    else:
        next_start = date(start.year, start.month + 1, 1)
    return int((next_start - start).days)


def _month_key(value: date) -> int:
    start = _month_start(value)
    return int(start.year * 100 + start.month)


def _month_start_from_key(value: int | None, *, fallback: date) -> date:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return _month_start(fallback)
    year = parsed // 100
    month = parsed % 100
    if year < 1970 or month < 1 or month > 12:
        return _month_start(fallback)
    return date(year, month, 1)


def _shift_month(value: date, delta: int) -> date:
    start = _month_start(value)
    offset = (start.month - 1) + int(delta)
    year = start.year + (offset // 12)
    month = (offset % 12) + 1
    return date(year, month, 1)


def _month_label_de(value: date) -> str:
    start = _month_start(value)
    name = MONTH_NAMES_DE[start.month - 1]
    return f"{name} {start.year}"


def _normalize_timezone_name(value: str | None) -> str:
    # Time handling is locked to Berlin for the full bot runtime.
    _ = value
    return DEFAULT_TIMEZONE_NAME


@lru_cache(maxsize=16)
def _zoneinfo_for_name(value: str | None) -> ZoneInfo:
    _ = value
    return BERLIN_TIMEZONE


def _berlin_now() -> datetime:
    return berlin_now()


def _utc_now() -> datetime:
    return berlin_now_utc()


def _upcoming_raid_date_labels(
    *,
    start_date: date | None = None,
    count: int = RAID_DATE_LOOKAHEAD_DAYS,
) -> list[str]:
    if start_date is None:
        first = _berlin_now().date()
    else:
        first = start_date
    total = max(1, min(RAID_DATE_CACHE_DAYS_MAX, int(count)))
    return [_format_raid_date_label(first + timedelta(days=offset)) for offset in range(total)]


def _normalize_raid_date_selection(values: list[str], *, allowed: list[str]) -> list[str]:
    order = {value: idx for idx, value in enumerate(allowed)}
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()
        if not value or value in seen or value not in order:
            continue
        seen.add(value)
        out.append(value)
    out.sort(key=lambda item: order.get(item, 0))
    return out


def _settings_embed(
    settings,
    guild_name: str,
    feature_settings: GuildFeatureSettings | None = None,
    raid_calendar_channel_id: int | None = None,
):
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
    embed.add_field(
        name="Raid Kalender Channel",
        value=f"`{raid_calendar_channel_id}`" if raid_calendar_channel_id else "nicht gesetzt",
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
            name="Raid 10min Reminder",
            value=_on_off(feature_settings.raid_reminder_enabled),
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


__all__ = [
    "APPROVED_GIF_URL",
    "BOT_MESSAGE_CACHE_PREFIX",
    "BOT_MESSAGE_INDEX_MAX_PER_CHANNEL",
    "BOT_MESSAGE_KIND",
    "CalendarEntry",
    "DEFAULT_PRIVILEGED_USER_ID",
    "DEFAULT_TIMEZONE_NAME",
    "FEATURE_FLAG_APPROVED_REPLY",
    "FEATURE_FLAG_LEVELING",
    "FEATURE_FLAG_LEVELUP_MESSAGES",
    "FEATURE_FLAG_MASK",
    "FEATURE_FLAG_NANOMON_REPLY",
    "FEATURE_FLAG_RAID_REMINDER",
    "FEATURE_INTERVAL_MASK",
    "FEATURE_LEVELUP_COOLDOWN_SHIFT",
    "FEATURE_MESSAGE_XP_SHIFT",
    "FEATURE_SETTINGS_CACHE_PREFIX",
    "FEATURE_SETTINGS_KIND",
    "GuildFeatureSettings",
    "INTEGRITY_CLEANUP_SLEEP_SECONDS",
    "LEVEL_PERSIST_WORKER_POLL_SECONDS",
    "LOG_CHANNEL_LOGGER_NAMES",
    "LOG_FORWARD_QUEUE_MAX_SIZE",
    "MemberlistRebuildStats",
    "NANOMON_IMAGE_URL",
    "PERSIST_FLUSH_MAX_ATTEMPTS",
    "PERSIST_FLUSH_RETRY_BASE_SECONDS",
    "PRIVILEGED_ONLY_HELP_COMMANDS",
    "RAID_CALENDAR_CONFIG_CACHE_PREFIX",
    "RAID_CALENDAR_CONFIG_KIND",
    "RAID_CALENDAR_GRID_COLUMNS",
    "RAID_CALENDAR_GRID_ROWS",
    "RAID_CALENDAR_MESSAGE_CACHE_PREFIX",
    "RAID_CALENDAR_MESSAGE_KIND",
    "RAID_DATE_CACHE_DAYS_MAX",
    "RAID_DATE_LOOKAHEAD_DAYS",
    "RAID_REMINDER_ADVANCE_SECONDS",
    "RAID_REMINDER_CACHE_PREFIX",
    "RAID_REMINDER_KIND",
    "RAID_REMINDER_WORKER_SLEEP_SECONDS",
    "SLOT_TEMP_ROLE_CACHE_PREFIX",
    "SLOT_TEMP_ROLE_KIND",
    "STALE_RAID_CHECK_SECONDS",
    "STALE_RAID_HOURS",
    "USERNAME_SYNC_RESCAN_SECONDS",
    "USERNAME_SYNC_WORKER_SLEEP_SECONDS",
    "VOICE_XP_CHECK_SECONDS",
    "_DISCORD_LOG_LINE_PATTERN",
    "_SLOT_ROLE_NAME_PATTERN",
    "_admin_or_privileged_check",
    "_days_in_month",
    "_extract_slash_command_name",
    "_format_raid_date_label",
    "_is_admin_or_privileged",
    "_member_name",
    "_month_key",
    "_month_label_de",
    "_month_start",
    "_month_start_from_key",
    "_normalize_raid_date_selection",
    "_normalize_timezone_name",
    "_on_off",
    "_parse_raid_date_from_label",
    "_parse_raid_time_label",
    "_raid_weekday_short",
    "_berlin_now",
    "_render_xp_progress_bar",
    "_round_xp_for_display",
    "_safe_defer",
    "_safe_delete_message",
    "_safe_edit_message",
    "_safe_fetch_message",
    "_safe_followup",
    "_safe_send_channel_message",
    "_safe_send_initial",
    "_settings_embed",
    "_shift_month",
    "_utc_now",
    "_upcoming_raid_date_labels",
    "_xp_progress_stats",
    "_zoneinfo_for_name",
    "log",
]
