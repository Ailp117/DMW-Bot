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
from utils.slots import compute_qualified_slot_users, memberlist_target_label, memberlist_threshold
from utils.text import contains_approved_keyword, contains_nanomon_keyword

if TYPE_CHECKING:
    from bot.runtime import RewriteDiscordBot


class RuntimeEventsMixin(RuntimeMixinBase):
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
        if not self.persistence.session_manager.is_disabled:
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
        if not self.persistence.session_manager.is_disabled:
            await self.persistence.flush(self.repo)

    def _restore_persistent_vote_views(self) -> None:
        from views.raid_views import RaidVoteView

        restored = 0
        for raid in self.repo.list_open_raids():
            if not raid.message_id:
                continue
            days, times = self.repo.list_raid_options(raid.id)
            if not days or not times:
                continue
            self.add_view(
                RaidVoteView(cast("RewriteDiscordBot", self), raid.id, days, times),
                message_id=raid.message_id,
            )
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
                await self._persist(dirty_tables={"settings"})

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
        self.task_registry.start_once("raid_reminder_worker", self._raid_reminder_worker)
        self.task_registry.start_once("integrity_cleanup_worker", self._integrity_cleanup_worker)
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
            await self._persist(dirty_tables={"settings", "debug_cache"})

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

        if getattr(message.content, "upper", lambda: "")() == "TOL" and message.content == "TOL":
            file_path = Path(__file__).parent.parent.parent / "Pics" / "tree.png"
            if file_path.exists():
                await message.channel.send(file=discord.File(file_path))
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
                                f"(XP: {_round_xp_for_display(result.xp)})"
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
        command_parts = raw.lstrip("/").strip().split()
        if not command_parts:
            return False
        command = command_parts[0].lower()
        if command != "restart":
            return False
        try:
            await self._send_channel_message(message.channel, content="♻️ Neustart wird eingeleitet ...")
        except Exception:
            pass
        await self.close()
        return True
