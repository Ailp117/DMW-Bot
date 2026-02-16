from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
import inspect
import logging
from pathlib import Path
import time
from typing import Any, AsyncIterable, Awaitable, TYPE_CHECKING, cast

from bot.discord_api import app_commands, discord
from db.repository import RaidPostedSlotRecord, RaidRecord, UserLevelRecord
from db.schema_guard import ensure_required_schema, validate_required_tables
from features.runtime_mixins._typing import RuntimeMixinBase
from services.admin_service import cancel_all_open_raids
from services.backup_service import export_rows_to_sql
from services.raid_service import finish_raid, planner_counts
from utils.hashing import sha256_text
from utils.runtime_helpers import *  # noqa: F401,F403
from utils.runtime_helpers import FEATURE_FLAG_AUTO_REMINDER
from utils.slots import compute_qualified_slot_users, memberlist_target_label, memberlist_threshold
from utils.text import contains_approved_keyword, contains_nanomon_keyword

if TYPE_CHECKING:
    from bot.runtime import RewriteDiscordBot


class RuntimeStateCalendarMixin(RuntimeMixinBase):
    @staticmethod
    def _runtime_mod():
        import bot.runtime as runtime_mod

        return runtime_mod

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

    async def _reply(self, interaction: Any, content: str, *, ephemeral: bool = True, embed: Any | None = None) -> None:
        first = await self._mark_interaction_once(interaction)
        if first and await _safe_send_initial(interaction, content, ephemeral=ephemeral, embed=embed):
            if AUTO_DELETE_COMMAND_MESSAGES and hasattr(interaction, "message") and interaction.message:
                try:
                    await interaction.message.delete()
                except Exception:
                    pass
            return
        await _safe_followup(interaction, content, ephemeral=ephemeral, embed=embed)

    async def _defer(self, interaction: Any, *, ephemeral: bool = True) -> bool:
        first = await self._mark_interaction_once(interaction)
        if not first:
            return False
        return await _safe_defer(interaction, ephemeral=ephemeral)

    async def _persist(self, *, dirty_tables: set[str] | None = None) -> bool:
        runtime_mod = self._runtime_mod()
        max_attempts = max(1, int(getattr(runtime_mod, "PERSIST_FLUSH_MAX_ATTEMPTS", PERSIST_FLUSH_MAX_ATTEMPTS)))
        retry_base_seconds = float(
            getattr(runtime_mod, "PERSIST_FLUSH_RETRY_BASE_SECONDS", PERSIST_FLUSH_RETRY_BASE_SECONDS)
        )
        hints = {str(name) for name in (dirty_tables or set()) if str(name).strip()}
        for attempt in range(1, max_attempts + 1):
            try:
                await self.persistence.flush(self.repo, dirty_tables=hints or None)
                return True
            except Exception as exc:
                if attempt >= max_attempts:
                    log.exception(
                        "Failed to flush state after %s attempts. Keeping in-memory state.",
                        max_attempts,
                    )
                    return False
                delay_seconds = retry_base_seconds * (2 ** (attempt - 1))
                log.warning(
                    "Flush attempt %s/%s failed (%s). Retrying in %.2fs.",
                    attempt,
                    max_attempts,
                    exc,
                    delay_seconds,
                )
                await asyncio.sleep(delay_seconds)
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
            raid_reminder_enabled=False,
            auto_reminder_enabled=False,
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
        if settings.raid_reminder_enabled:
            flags |= FEATURE_FLAG_RAID_REMINDER
        if settings.auto_reminder_enabled:
            flags |= FEATURE_FLAG_AUTO_REMINDER

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
            raid_reminder_enabled=bool(flags & FEATURE_FLAG_RAID_REMINDER),
            auto_reminder_enabled=bool(flags & FEATURE_FLAG_AUTO_REMINDER),
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
            f"raid_reminder={int(settings.raid_reminder_enabled)}|"
            f"auto_reminder={int(settings.auto_reminder_enabled)}|"
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

    @staticmethod
    def _raid_calendar_config_cache_key(guild_id: int) -> str:
        return f"{RAID_CALENDAR_CONFIG_CACHE_PREFIX}:{int(guild_id)}"

    @staticmethod
    def _raid_calendar_message_cache_key(guild_id: int) -> str:
        return f"{RAID_CALENDAR_MESSAGE_CACHE_PREFIX}:{int(guild_id)}"

    def _current_calendar_month_start(self) -> date:
        timezone = _zoneinfo_for_name(DEFAULT_TIMEZONE_NAME)
        return _month_start(datetime.now(timezone).date())

    def _get_raid_calendar_channel_id(self, guild_id: int) -> int | None:
        row = self.repo.get_debug_cache(self._raid_calendar_config_cache_key(guild_id))
        if row is None or row.kind != RAID_CALENDAR_CONFIG_KIND:
            return None
        channel_id = int(row.message_id or 0)
        if channel_id <= 0:
            return None
        return channel_id

    def _set_raid_calendar_channel_id(self, guild_id: int, channel_id: int | None) -> int | None:
        normalized_guild_id = int(guild_id)
        normalized_channel_id = int(channel_id or 0)
        config_key = self._raid_calendar_config_cache_key(normalized_guild_id)
        message_key = self._raid_calendar_message_cache_key(normalized_guild_id)

        if normalized_channel_id <= 0:
            self.repo.delete_debug_cache(config_key)
            self.repo.delete_debug_cache(message_key)
            self._raid_calendar_hash_by_guild.pop(normalized_guild_id, None)
            self._raid_calendar_month_key_by_guild.pop(normalized_guild_id, None)
            return None

        payload_hash = sha256_text(f"channel={normalized_channel_id}")
        self.repo.upsert_debug_cache(
            cache_key=config_key,
            kind=RAID_CALENDAR_CONFIG_KIND,
            guild_id=normalized_guild_id,
            raid_id=None,
            message_id=normalized_channel_id,
            payload_hash=payload_hash,
        )
        return normalized_channel_id

    def _get_raid_calendar_state_row(self, guild_id: int):
        row = self.repo.get_debug_cache(self._raid_calendar_message_cache_key(guild_id))
        if row is None or row.kind != RAID_CALENDAR_MESSAGE_KIND:
            return None
        return row

    def _resolve_raid_calendar_month_start(self, guild_id: int, month_start: date | None = None) -> date:
        if month_start is not None:
            return _month_start(month_start)

        cached_key = self._raid_calendar_month_key_by_guild.get(int(guild_id))
        if cached_key is not None:
            return _month_start_from_key(cached_key, fallback=self._current_calendar_month_start())

        state_row = self._get_raid_calendar_state_row(guild_id)
        if state_row is not None:
            return _month_start_from_key(state_row.raid_id, fallback=self._current_calendar_month_start())
        return self._current_calendar_month_start()

    def _collect_raid_calendar_entries(
        self,
        *,
        guild_id: int,
        month_start: date,
        month_end: date,
    ) -> list[CalendarEntry]:
        entries: list[CalendarEntry] = []
        for raid in self.repo.list_open_raids(guild_id):
            day_labels, _time_labels = self.repo.list_raid_options(raid.id)
            seen_dates: set[date] = set()
            for day_label in day_labels:
                parsed_date = _parse_raid_date_from_label(day_label)
                if parsed_date is None:
                    continue
                if parsed_date < month_start or parsed_date > month_end:
                    continue
                if parsed_date in seen_dates:
                    continue
                seen_dates.add(parsed_date)
                entries.append(
                    CalendarEntry(
                        entry_date=parsed_date,
                        label=f"#{raid.display_id} {raid.dungeon}",
                        source="raid",
                    )
                )
        return entries

    def _collect_calendar_entries(
        self,
        *,
        guild_id: int,
        month_start: date,
        month_end: date,
    ) -> list[CalendarEntry]:
        # Extension hook: future sources (birthdays, events, reminders) should append
        # additional CalendarEntry rows here without changing the calendar renderer.
        entries = self._collect_raid_calendar_entries(
            guild_id=guild_id,
            month_start=month_start,
            month_end=month_end,
        )
        entries.sort(key=lambda row: (row.entry_date, row.source, row.label.casefold()))
        return entries

    def _build_raid_calendar_embed(
        self,
        *,
        guild_id: int,
        guild_name: str,
        month_start: date,
    ) -> tuple[Any, str, list[str]]:
        normalized_month = _month_start(month_start)
        month_days = _days_in_month(normalized_month)
        month_end = normalized_month + timedelta(days=month_days - 1)
        timezone = _zoneinfo_for_name(DEFAULT_TIMEZONE_NAME)
        today_local = datetime.now(timezone).date()
        open_raids = self.repo.list_open_raids(guild_id)
        entries = self._collect_calendar_entries(
            guild_id=guild_id,
            month_start=normalized_month,
            month_end=month_end,
        )

        entries_by_day: dict[date, list[CalendarEntry]] = {}
        for row in entries:
            entries_by_day.setdefault(row.entry_date, []).append(row)

        grid_rows: list[str] = []
        debug_lines: list[str] = []
        payload_parts = [f"month={normalized_month.isoformat()}", f"open_raids={len(open_raids)}"]
        for row_index in range(RAID_CALENDAR_GRID_ROWS):
            token_parts: list[str] = []
            for col_index in range(RAID_CALENDAR_GRID_COLUMNS):
                offset = row_index * RAID_CALENDAR_GRID_COLUMNS + col_index
                slot_date = normalized_month + timedelta(days=offset)
                in_current_month = slot_date.month == normalized_month.month and slot_date.year == normalized_month.year
                entry_count = len(entries_by_day.get(slot_date, []))
                is_today = slot_date == today_local and in_current_month

                base = f"{slot_date.day:02d}"
                if not in_current_month:
                    base += ">"
                if is_today:
                    base = f"🟩{base}"
                if entry_count > 0:
                    token = f"{base}[{entry_count}]"
                else:
                    token = base
                token_parts.append(token.rjust(8))
                payload_parts.append(f"{slot_date.isoformat()}:{entry_count}:{int(in_current_month)}")
            grid_rows.append("".join(token_parts).rstrip())

        detail_lines: list[str] = []
        for day_key in sorted(entries_by_day.keys()):
            labels = sorted({row.label for row in entries_by_day[day_key]}, key=lambda value: value.casefold())
            if not labels:
                continue
            line = f"{day_key.isoformat()} ({_raid_weekday_short(day_key.weekday())}): " + ", ".join(labels[:6])
            if len(labels) > 6:
                line += f" ... +{len(labels) - 6}"
            detail_lines.append(line)
            debug_lines.append(line)
            payload_parts.append(f"detail={line}")

        grid_block = "```text\n" + "\n".join(grid_rows) + "\n```"
        embed = discord.Embed(
            title=f"📅 Raid Kalender • {_month_label_de(normalized_month)}",
            description=(
                f"Server: **{guild_name}**\n"
                f"Offene Raids gesamt: `{len(open_raids)}`"
            ),
            color=discord.Color.green(),
            timestamp=datetime.now(UTC),
        )
        embed.add_field(name="Monatsansicht", value=grid_block, inline=False)
        if detail_lines:
            details = "\n".join(f"• {line}" for line in detail_lines[:14])
            if len(detail_lines) > 14:
                details += f"\n... +{len(detail_lines) - 14} weitere Tage"
        else:
            details = "Keine offenen Raids in diesem Monat."
        if len(details) > 1024:
            details = details[:1021] + "..."
        embed.add_field(name="Raid Termine", value=details, inline=False)
        embed.set_footer(
            text=(
                "Legende: 🟩DD = heute, DD = Monatstag, DD>[n] = Folgemonatstag, [n] = Anzahl Eintraege | "
                "Monat per Buttons wechseln"
            )
        )

        payload_hash = sha256_text("\n".join(payload_parts))
        return embed, payload_hash, debug_lines

    async def _refresh_raid_calendar_for_guild(
        self,
        guild_id: int,
        *,
        force: bool = False,
        month_start: date | None = None,
    ) -> bool:
        channel_id = self._get_raid_calendar_channel_id(guild_id)
        if channel_id is None:
            return False

        # Raid Calendar Feature deaktiviert
        return False
        if state_row is not None and int(state_row.message_id or 0) > 0:
            existing = await _safe_fetch_message(channel, int(state_row.message_id))
            if existing is not None:
                edited = await _safe_edit_message(existing, content=None, embed=embed, view=view)
                if edited:
                    self.repo.upsert_debug_cache(
                        cache_key=self._raid_calendar_message_cache_key(guild_id),
                        kind=RAID_CALENDAR_MESSAGE_KIND,
                        guild_id=int(guild_id),
                        raid_id=month_key,
                        message_id=int(existing.id),
                        payload_hash=payload_hash,
                    )
                    self._raid_calendar_hash_by_guild[int(guild_id)] = payload_hash
                    self._raid_calendar_month_key_by_guild[int(guild_id)] = month_key
                    return True

        posted = await self._send_channel_message(channel, embed=embed, view=view)
        if posted is None:
            return False

        self.repo.upsert_debug_cache(
            cache_key=self._raid_calendar_message_cache_key(guild_id),
            kind=RAID_CALENDAR_MESSAGE_KIND,
            guild_id=int(guild_id),
            raid_id=month_key,
            message_id=int(posted.id),
            payload_hash=payload_hash,
        )
        self._raid_calendar_hash_by_guild[int(guild_id)] = payload_hash
        self._raid_calendar_month_key_by_guild[int(guild_id)] = month_key
        return True

    async def _delete_raid_calendar_message_by_id(
        self,
        guild_id: int,
        message_id: int,
        *,
        preferred_channel_id: int | None = None,
    ) -> bool:
        normalized_guild_id = int(guild_id)
        normalized_message_id = int(message_id or 0)
        if normalized_guild_id <= 0 or normalized_message_id <= 0:
            return False

        channel_candidates: list[int] = []
        if preferred_channel_id is not None and int(preferred_channel_id) > 0:
            channel_candidates.append(int(preferred_channel_id))

        configured_channel_id = self._get_raid_calendar_channel_id(normalized_guild_id)
        if configured_channel_id is not None and int(configured_channel_id) > 0:
            channel_candidates.append(int(configured_channel_id))

        for row in self.repo.list_debug_cache(kind=BOT_MESSAGE_KIND, guild_id=normalized_guild_id):
            if int(row.message_id or 0) != normalized_message_id:
                continue
            channel_id = int(row.raid_id or 0)
            if channel_id > 0:
                channel_candidates.append(channel_id)

        deduped_channel_ids: list[int] = []
        seen_channel_ids: set[int] = set()
        for channel_id in channel_candidates:
            if channel_id <= 0 or channel_id in seen_channel_ids:
                continue
            seen_channel_ids.add(channel_id)
            deduped_channel_ids.append(channel_id)

        for channel_id in deduped_channel_ids:
            channel = await self._get_text_channel(channel_id)
            if channel is None:
                continue
            message = await _safe_fetch_message(channel, normalized_message_id)
            if message is None:
                continue
            deleted = await _safe_delete_message(message)
            self._clear_bot_message_index_for_id(
                guild_id=normalized_guild_id,
                channel_id=channel_id,
                message_id=normalized_message_id,
            )
            self._clear_known_message_refs_for_id(
                guild_id=normalized_guild_id,
                channel_id=channel_id,
                message_id=normalized_message_id,
            )
            return bool(deleted)

        self._clear_known_message_refs_for_id(
            guild_id=normalized_guild_id,
            channel_id=int(preferred_channel_id or 0),
            message_id=normalized_message_id,
        )
        return False

    async def _rebuild_raid_calendar_message_for_guild(self, guild_id: int) -> bool:
        normalized_guild_id = int(guild_id)
        configured_channel_id = self._get_raid_calendar_channel_id(normalized_guild_id)
        state_row = self._get_raid_calendar_state_row(normalized_guild_id)
        state_message_id = int(getattr(state_row, "message_id", 0) or 0)

        if state_message_id > 0:
            await self._delete_raid_calendar_message_by_id(
                normalized_guild_id,
                state_message_id,
                preferred_channel_id=configured_channel_id,
            )

        self.repo.delete_debug_cache(self._raid_calendar_message_cache_key(normalized_guild_id))
        self._raid_calendar_hash_by_guild.pop(normalized_guild_id, None)
        self._raid_calendar_month_key_by_guild.pop(normalized_guild_id, None)

        if configured_channel_id is None:
            return False
        return await self._refresh_raid_calendar_for_guild(
            normalized_guild_id,
            force=True,
            month_start=self._current_calendar_month_start(),
        )

    async def _shift_raid_calendar_month(self, guild_id: int, *, delta_months: int) -> date:
        current_month = self._resolve_raid_calendar_month_start(guild_id)
        target_month = _shift_month(current_month, int(delta_months))
        await self._refresh_raid_calendar_for_guild(guild_id, force=True, month_start=target_month)
        return target_month

    async def _force_raid_calendar_refresh(self, guild_id: int) -> None:
        await self._refresh_raid_calendar_for_guild(guild_id, force=True)

    async def _refresh_raid_calendars_for_all_guilds(self, *, force: bool) -> None:
        guild_ids: set[int] = set()

        list_debug_cache_fn = getattr(self.repo, "list_debug_cache", None)
        if callable(list_debug_cache_fn):
            rows_obj = list_debug_cache_fn(kind=RAID_CALENDAR_CONFIG_KIND)
            rows_iter: list[Any]
            if isinstance(rows_obj, list):
                rows_iter = rows_obj
            elif isinstance(rows_obj, tuple):
                rows_iter = list(rows_obj)
            else:
                rows_iter = []
            for row in rows_iter:
                guild_id = int(getattr(row, "guild_id", 0) or 0)
                if guild_id > 0:
                    guild_ids.add(guild_id)

        settings_by_guild = getattr(self.repo, "settings", {}) or {}
        if isinstance(settings_by_guild, dict):
            guild_ids.update(int(guild_id) for guild_id in settings_by_guild.keys())

        list_open_raids_fn = getattr(self.repo, "list_open_raids", None)
        if callable(list_open_raids_fn):
            raids_obj = list_open_raids_fn()
            raids_iter: list[Any]
            if isinstance(raids_obj, list):
                raids_iter = raids_obj
            elif isinstance(raids_obj, tuple):
                raids_iter = list(raids_obj)
            else:
                raids_iter = []
            for raid in raids_iter:
                guild_id = int(getattr(raid, "guild_id", 0) or 0)
                if guild_id > 0:
                    guild_ids.add(guild_id)

        for guild_id in sorted(guild_ids):
            await self._refresh_raid_calendar_for_guild(guild_id, force=force)

    def _restore_persistent_raid_calendar_views(self) -> None:
        # Raid Calendar Feature deaktiviert
        pass

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
