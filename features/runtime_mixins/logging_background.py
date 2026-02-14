from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
import inspect
import logging
from pathlib import Path
import re
import time
from typing import Any, AsyncIterable, Awaitable, cast

from bot.discord_api import app_commands, discord
from db.repository import RaidPostedSlotRecord, RaidRecord, UserLevelRecord
from db.schema_guard import ensure_required_schema, validate_required_tables
from features.runtime_mixins._typing import RuntimeMixinBase
from services.admin_service import cancel_all_open_raids
from services.backup_service import export_rows_to_sql
from services.raid_service import finish_raid, planner_counts
from services.startup_service import EXPECTED_SLASH_COMMANDS
from utils.hashing import sha256_text
from utils.runtime_helpers import *  # noqa: F401,F403
from utils.slots import compute_qualified_slot_users, memberlist_target_label, memberlist_threshold
from utils.text import contains_approved_keyword, contains_nanomon_keyword


class RuntimeLoggingBackgroundMixin(RuntimeMixinBase):
    _IMPORTANT_INFO_PREFIXES = (
        "Rewrite bot ready as",
        "Command sync completed",
        "Applied DB schema changes",
        "Restored ",
        "Automatic backup completed",
        "Username sync updated rows=",
        "Command executed:",
    )
    _LOG_GUILD_ID_PATTERN = re.compile(r"\bguild_id=(?P<guild_id>\d+)\b")

    def _enqueue_log_forward_queue(self, message: str) -> None:
        if self.log_forward_queue.full():
            try:
                self.log_forward_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self.log_forward_queue.put_nowait(message)
        except asyncio.QueueFull:
            pass

    def _build_discord_log_handler(self) -> logging.Handler:
        bot = self

        class _DiscordQueueHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    if not bot._should_forward_log_record(record):
                        return
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

    @classmethod
    def _is_important_info_message(cls, text: str) -> bool:
        normalized = str(text or "").strip()
        return any(normalized.startswith(prefix) for prefix in cls._IMPORTANT_INFO_PREFIXES)

    def _should_forward_log_record(self, record: logging.LogRecord) -> bool:
        level = int(getattr(record, "levelno", logging.INFO))
        if level >= logging.WARNING:
            return True
        if level <= logging.DEBUG:
            return False

        source_name = str(getattr(record, "name", "") or "")
        if source_name.startswith("dmw.db"):
            return False

        try:
            message = record.getMessage()
        except Exception:
            message = str(getattr(record, "msg", ""))
        return self._is_important_info_message(message)

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
            self._enqueue_log_forward_queue(text)
            return
        self.pending_log_buffer.append(text)

    def _flush_pending_logs(self) -> None:
        while self.pending_log_buffer:
            self._enqueue_log_forward_queue(self.pending_log_buffer.popleft())

    @staticmethod
    def _log_level_presentation(level: str) -> tuple[str, Any]:
        normalized = (level or "").upper()
        if normalized == "DEBUG":
            return ("🛠️ DEBUG", discord.Color.light_grey())
        if normalized == "INFO":
            return ("ℹ️ INFO", discord.Color.blurple())
        if normalized in {"WARNING", "WARN"}:
            return ("⚠️ WARNING", discord.Color.gold())
        if normalized == "ERROR":
            return ("❌ ERROR", discord.Color.red())
        if normalized == "CRITICAL":
            return ("🛑 CRITICAL", discord.Color.dark_red())
        return (f"📌 {normalized or 'LOG'}", discord.Color.dark_grey())

    def _build_discord_log_embed(self, raw_message: str):
        text = str(raw_message or "").strip()
        if not text:
            return None

        match = _DISCORD_LOG_LINE_PATTERN.match(text)
        if match is None:
            timestamp = _berlin_now().strftime("%Y-%m-%d %H:%M:%S")
            level = "INFO"
            source = "dmw.runtime/unstructured"
            body = text
        else:
            timestamp = (match.group("timestamp") or "").strip()
            level = (match.group("level") or "").strip().upper()
            source = (match.group("source") or "").strip()
            body = (match.group("body") or "").strip() or "(leer)"

        title_label, color = self._log_level_presentation(level)
        compact_body = " ".join(body.split()) or "(leer)"
        guild_id: int | None = None
        guild_match = self._LOG_GUILD_ID_PATTERN.search(compact_body)
        if guild_match is not None:
            try:
                guild_id = int(guild_match.group("guild_id"))
            except (TypeError, ValueError):
                guild_id = None
        if guild_id is not None:
            compact_body = self._LOG_GUILD_ID_PATTERN.sub(
                f"guild={self._log_guild_label(guild_id)}",
                compact_body,
            )

        description = compact_body if len(compact_body) <= 700 else f"{compact_body[:697]}..."
        source_field = source if len(source) <= 1000 else f"{source[:997]}..."
        embed = discord.Embed(
            title=f"{title_label} • Systemlog",
            description=description,
            color=color,
            timestamp=_berlin_now(),
        )
        embed.add_field(name="Quelle", value=f"`{source_field}`", inline=False)
        embed.add_field(name="Zeit", value=f"`{timestamp}`", inline=True)
        if guild_id is not None:
            embed.add_field(name="Server", value=f"`{self._log_guild_label(guild_id)}`", inline=True)
        embed.set_footer(text="DMW • Wichtige Ereignisse")
        return embed

    def _log_guild_label(self, guild_id: int) -> str:
        resolver = getattr(self, "_guild_display_name", None)
        if callable(resolver):
            try:
                name = str(resolver(int(guild_id)) or "").strip()
                if name:
                    return f"{name} ({int(guild_id)})"
            except Exception:
                pass
        return f"Server {int(guild_id)}"

    def _build_user_id_card_embed(self, *, guild_id: int, guild_name: str, user: Any):
        user_id = int(getattr(user, "id", 0) or 0)
        display_name = _member_name(user) or f"User {user_id}"

        row = self.repo.user_levels.get((int(guild_id), int(user_id)))
        total_xp = max(0, int(getattr(row, "xp", 0) or 0))
        level = max(0, int(getattr(row, "level", 0) or 0))

        progress_xp, level_span, percent = _xp_progress_stats(total_xp, level)
        xp_bar = _render_xp_progress_bar(progress=progress_xp, total=level_span, width=18)

        avatar_url: str | None = None
        avatar = getattr(user, "display_avatar", None)
        if avatar is not None:
            avatar_raw = str(getattr(avatar, "url", "") or "").strip()
            if avatar_raw:
                avatar_url = avatar_raw

        embed = discord.Embed(
            title="🪪 DMW Spieler-Ausweis",
            description=f"Server: **{guild_name}**",
            color=discord.Color.blue(),
            timestamp=_berlin_now(),
        )
        if avatar_url:
            embed.set_author(name=display_name, icon_url=avatar_url)
            embed.set_thumbnail(url=avatar_url)
        else:
            embed.set_author(name=display_name)
        embed.add_field(name="Name", value=f"`{display_name}`", inline=True)
        embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)
        embed.add_field(name="Level", value=f"`{level}`", inline=True)
        embed.add_field(name="Gesamt XP", value=f"`{total_xp}`", inline=True)
        embed.add_field(name="Fortschritt", value=f"`{progress_xp}/{level_span}` (`{percent}%`)", inline=True)
        embed.add_field(name="XP bis Level-Up", value=f"`{max(0, level_span - progress_xp)}`", inline=True)
        embed.set_footer(text=f"XP {xp_bar} {percent}%")
        return embed

    async def _resolve_log_channel(self):
        if self.config.log_guild_id <= 0 or self.config.log_channel_id <= 0:
            return None
        guild = self.get_guild(self.config.log_guild_id)
        if guild is None:
            return None
        channel_id = int(self.config.log_channel_id)
        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            return channel
        try:
            fetched = await self.fetch_channel(channel_id)
        except Exception:
            return None
        if isinstance(fetched, discord.TextChannel) and int(getattr(getattr(fetched, "guild", None), "id", 0) or 0) == int(guild.id):
            return fetched
        return None

    async def _log_forwarder_worker(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            message = await self.log_forward_queue.get()
            channel = self.log_channel
            if channel is None:
                self.log_channel = await self._resolve_log_channel()
                channel = self.log_channel
            if channel is None:
                # Keep message buffered if log channel is temporarily unavailable.
                self._enqueue_log_forward_queue(message)
                await asyncio.sleep(1.0)
                continue
            try:
                embed = self._build_discord_log_embed(message)
                if embed is not None:
                    await self._send_channel_message(channel, embed=embed)
                else:
                    fallback = message if len(message) <= 1800 else f"{message[:1797]}..."
                    await self._send_channel_message(channel, content=f"```text\n{fallback}\n```")
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
        self.last_self_test_ok_at = _utc_now()
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

    @staticmethod
    def _slot_cache_suffix(day_label: str, time_label: str) -> str:
        payload = f"{(day_label or '').strip().lower()}|{(time_label or '').strip().lower()}"
        return sha256_text(payload)[:24]

    @classmethod
    def _slot_temp_role_cache_key(cls, raid_id: int, day_label: str, time_label: str) -> str:
        return f"{SLOT_TEMP_ROLE_CACHE_PREFIX}:{int(raid_id)}:{cls._slot_cache_suffix(day_label, time_label)}"

    @classmethod
    def _raid_reminder_cache_key(cls, raid_id: int, day_label: str, time_label: str) -> str:
        return f"{RAID_REMINDER_CACHE_PREFIX}:{int(raid_id)}:{cls._slot_cache_suffix(day_label, time_label)}"

    @staticmethod
    def _parse_slot_start_at_utc(
        day_label: str,
        time_label: str,
        *,
        timezone_name: str = DEFAULT_TIMEZONE_NAME,
    ) -> datetime | None:
        parsed_date = _parse_raid_date_from_label(day_label)
        parsed_time = _parse_raid_time_label(time_label)
        if parsed_date is None or parsed_time is None:
            return None
        timezone = _zoneinfo_for_name(timezone_name)
        try:
            local_start = datetime(
                parsed_date.year,
                parsed_date.month,
                parsed_date.day,
                parsed_time[0],
                parsed_time[1],
                tzinfo=timezone,
            )
            return local_start.astimezone(UTC)
        except ValueError:
            return None

    async def _run_raid_reminders_once(self, *, now_utc: datetime | None = None) -> int:
        current = now_utc or _utc_now()
        sent = 0
        participants_channel_by_id: dict[int, Any | None] = {}
        for raid in self.repo.list_open_raids():
            feature_settings = self._get_guild_feature_settings(raid.guild_id)
            if not feature_settings.raid_reminder_enabled:
                continue

            settings = self.repo.ensure_settings(raid.guild_id)
            participants_channel_id = int(settings.participants_channel_id or 0)
            if participants_channel_id <= 0:
                continue
            if participants_channel_id not in participants_channel_by_id:
                participants_channel_by_id[participants_channel_id] = await self._get_text_channel(
                    participants_channel_id
                )
            participants_channel = participants_channel_by_id[participants_channel_id]
            if participants_channel is None:
                continue

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
            for (day_label, time_label), users in qualified_slots.items():
                start_at = self._parse_slot_start_at_utc(
                    day_label,
                    time_label,
                    timezone_name=DEFAULT_TIMEZONE_NAME,
                )
                if start_at is None:
                    continue
                delta_seconds = (start_at - current).total_seconds()
                if delta_seconds < 0 or delta_seconds > RAID_REMINDER_ADVANCE_SECONDS:
                    continue

                reminder_cache_key = self._raid_reminder_cache_key(raid.id, day_label, time_label)
                if self.repo.get_debug_cache(reminder_cache_key) is not None:
                    continue

                role = await self._ensure_slot_temp_role(raid, day_label=day_label, time_label=time_label)
                if role is None:
                    continue
                await self._sync_slot_role_members(raid, role=role, user_ids=users)

                content = (
                    f"⏰ Raid-Erinnerung: **{raid.dungeon}** startet in ca. 10 Minuten.\n"
                    f"🆔 Raid `{raid.display_id}`\n"
                    f"📅 {day_label}\n"
                    f"🕒 {time_label} ({DEFAULT_TIMEZONE_NAME})\n"
                    f"{role.mention}"
                )
                posted = await self._send_channel_message(
                    participants_channel,
                    content=content,
                    allowed_mentions=discord.AllowedMentions(roles=True, users=True),
                )
                if posted is None:
                    continue
                self.repo.upsert_debug_cache(
                    cache_key=reminder_cache_key,
                    kind=RAID_REMINDER_KIND,
                    guild_id=raid.guild_id,
                    raid_id=raid.id,
                    message_id=posted.id,
                    payload_hash=sha256_text(content),
                )
                sent += 1
        return sent

    async def _raid_reminder_worker(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                async with self._state_lock:
                    sent = await self._run_raid_reminders_once()
                    if sent > 0:
                        await self._persist(dirty_tables={"debug_cache"})
            except Exception:
                log.exception("Raid reminder worker failed")
            await asyncio.sleep(RAID_REMINDER_WORKER_SLEEP_SECONDS)

    async def _run_integrity_cleanup_once(self) -> int:
        open_raids_by_id = {int(raid.id): raid for raid in self.repo.list_open_raids()}
        open_display_ids_by_guild: dict[int, set[int]] = {}
        for raid in open_raids_by_id.values():
            display_id = int(raid.display_id or 0)
            if display_id <= 0:
                continue
            open_display_ids_by_guild.setdefault(int(raid.guild_id), set()).add(display_id)
        removed_rows = 0

        # Legacy cleanup: remove previously used timezone cache rows.
        for row in list(self.repo.list_debug_cache(kind="user_timezone")):
            self.repo.delete_debug_cache(row.cache_key)
            removed_rows += 1
        for row in list(self.repo.list_debug_cache(kind="raid_timezone")):
            self.repo.delete_debug_cache(row.cache_key)
            removed_rows += 1

        for row in list(self.repo.list_debug_cache(kind=RAID_REMINDER_KIND)):
            raid_id = int(row.raid_id or 0)
            raid = open_raids_by_id.get(raid_id)
            if raid is not None and int(raid.guild_id) == int(row.guild_id):
                continue
            self.repo.delete_debug_cache(row.cache_key)
            removed_rows += 1

        for row in list(self.repo.list_debug_cache(kind=PLANNER_MESSAGE_KIND)):
            raid_id = int(row.raid_id or 0)
            raid = open_raids_by_id.get(raid_id)
            if raid is not None and int(raid.guild_id) == int(row.guild_id):
                continue
            self.repo.delete_debug_cache(row.cache_key)
            removed_rows += 1

        for row in list(self.repo.list_debug_cache(kind=SLOT_TEMP_ROLE_KIND)):
            raid_id = int(row.raid_id or 0)
            raid = open_raids_by_id.get(raid_id)
            if raid is not None and int(raid.guild_id) == int(row.guild_id):
                continue

            guild = self._safe_get_guild(int(row.guild_id))
            if guild is not None:
                role = await self._resolve_role_by_id(guild, int(row.message_id or 0))
                if role is not None:
                    await self._cleanup_role_members_and_delete(role, reason="DMW orphan cleanup")
            self.repo.delete_debug_cache(row.cache_key)
            removed_rows += 1

        for guild in list(getattr(self, "guilds", []) or []):
            open_display_ids = open_display_ids_by_guild.get(int(getattr(guild, "id", 0) or 0), set())
            for role in list(getattr(guild, "roles", []) or []):
                role_name = str(getattr(role, "name", "") or "")
                if not role_name.startswith("DMW Raid "):
                    continue
                match = _SLOT_ROLE_NAME_PATTERN.match(role_name)
                if match is None:
                    continue
                display_id = int(match.group("display_id"))
                if display_id in open_display_ids:
                    continue
                await self._cleanup_role_members_and_delete(role, reason="DMW orphan cleanup")

        return removed_rows

    async def _integrity_cleanup_worker(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                async with self._state_lock:
                    removed_rows = await self._run_integrity_cleanup_once()
                    if removed_rows > 0:
                        await self._persist(dirty_tables={"debug_cache"})
            except Exception:
                log.exception("Integrity cleanup worker failed")
            await asyncio.sleep(INTEGRITY_CLEANUP_SLEEP_SECONDS)

    async def _voice_xp_worker(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            changed = False
            now = _utc_now()
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

        persisted = await self._persist(dirty_tables={"user_levels"})
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
        now = _utc_now()

        stale_ids: list[int] = []
        for raid in self.repo.list_open_raids():
            created_at = raid.created_at
            if created_at.tzinfo is None:
                created_utc = created_at.replace(tzinfo=UTC)
            else:
                created_utc = created_at.astimezone(UTC)
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
            self._clear_planner_message_cache_for_raid(raid)
            for row in slot_rows:
                await self._delete_slot_message(row)
            self.repo.delete_raid_cascade(raid.id)
            await self._refresh_raidlist_for_guild(raid.guild_id, force=True)
            await self._refresh_raid_calendar_for_guild(raid.guild_id, force=True)
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
