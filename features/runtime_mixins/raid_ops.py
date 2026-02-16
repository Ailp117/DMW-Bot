from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
import inspect
import logging
from pathlib import Path
import re
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
from utils.localization import get_string
from utils.runtime_helpers import *  # noqa: F401,F403
from utils.slots import compute_qualified_slot_users, memberlist_target_label, memberlist_threshold
from utils.text import contains_approved_keyword, contains_nanomon_keyword

if TYPE_CHECKING:
    from bot.runtime import RewriteDiscordBot


def _runtime_mod():
    import bot.runtime as runtime_mod

    return runtime_mod


class RuntimeRaidOpsMixin(RuntimeMixinBase):
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

    def _safe_get_guild(self, guild_id: int):
        try:
            return self.get_guild(int(guild_id))
        except Exception:
            return None

    @staticmethod
    async def _await_if_needed(result: Any) -> Any:
        if inspect.isawaitable(result):
            return await cast(Awaitable[Any], result)
        return result

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
            members_iter = fetch_members(limit=None)
            if not hasattr(members_iter, "__aiter__"):
                return users
            async for member in cast(AsyncIterable[Any], members_iter):
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
        if len(indexed_rows) <= _runtime_mod().BOT_MESSAGE_INDEX_MAX_PER_CHANNEL:
            return
        oldest_first = sorted(indexed_rows, key=lambda row: int(row.message_id))
        for stale_row in oldest_first[: max(0, len(oldest_first) - _runtime_mod().BOT_MESSAGE_INDEX_MAX_PER_CHANNEL)]:
            self.repo.delete_debug_cache(stale_row.cache_key)

    async def _send_channel_message(self, channel: Any, **kwargs: Any) -> Any | None:
        posted = await _runtime_mod()._safe_send_channel_message(channel, **kwargs)
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

    def _remote_guild_autocomplete_choices(self, query: str) -> list[Any]:
        search = (query or "").strip().casefold()
        guilds = sorted(self.guilds, key=lambda guild: ((guild.name or "").casefold(), int(guild.id)))
        name_counts: dict[str, int] = {}
        for guild in guilds:
            key = ((guild.name or "").strip() or str(guild.id)).casefold()
            name_counts[key] = name_counts.get(key, 0) + 1

        choices: list[Any] = []
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

    def _guild_display_name(self, guild_id: int) -> str:
        guild = self._safe_get_guild(guild_id)
        if guild is not None:
            runtime_name = (getattr(guild, "name", "") or "").strip()
            if runtime_name:
                return runtime_name
        settings = self.repo.settings.get(int(guild_id))
        stored_name = ((settings.guild_name if settings is not None else None) or "").strip()
        if stored_name:
            return stored_name
        return f"Server {int(guild_id)}"

    def _format_debug_report(
        self,
        *,
        topic: str,
        guild_id: int,
        summary: list[str],
        lines: list[str] | None = None,
        empty_text: str = "- Keine Eintraege.",
    ) -> str:
        guild_name = self._guild_display_name(guild_id)
        header = [
            f"[{topic}]",
            f"Guild: {guild_name}",
        ]
        body = [item for item in summary if item]
        details = [item for item in (lines or []) if item]
        if not details:
            details = [empty_text]
        return "\n".join([*header, "", *body, "", "Details:", *details])

    def _build_debug_embed(
        self,
        *,
        topic: str,
        guild_id: int,
        summary: list[str],
        lines: list[str] | None = None,
        empty_text: str = "- Keine Eintraege.",
    ) -> Any:
        guild_name = self._guild_display_name(guild_id)
        embed = discord.Embed(
            title=f"🐛 {topic}",
            color=discord.Color.orange(),
            timestamp=datetime.now(UTC),
        )
        embed.add_field(name="Server", value=f"**{guild_name}**", inline=False)
        for item in summary:
            if item:
                if ":" in item:
                    key, _, value = item.partition(":")
                    embed.add_field(name=key.strip(), value=value.strip(), inline=True)
        details = [item for item in (lines or []) if item]
        if not details:
            details = [empty_text]
        details_text = "\n".join(details)
        if len(details_text) > 1000:
            details_text = details_text[:997] + "..."
        embed.add_field(name="Details", value=f"```\n{details_text}\n```", inline=False)
        return embed

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

        payload_hash = sha256_text(content)
        cached = self.repo.get_debug_cache(cache_key)

        if cached is not None and cached.payload_hash == payload_hash and cached.message_id:
            existing = await _runtime_mod()._safe_fetch_message(channel, cached.message_id)
            if existing is not None:
                return

        topic = "Debug"
        if "raidlist" in cache_key:
            topic = "Raidlist Debug"
        elif "memberlist" in cache_key:
            topic = "Memberlist Debug"

        embed = self._build_debug_embed(
            topic=topic,
            guild_id=guild_id,
            summary=[],
            lines=content.split("\n"),
        )

        if cached is not None and cached.message_id:
            existing = await _runtime_mod()._safe_fetch_message(channel, cached.message_id)
            if existing is not None:
                edited = await _runtime_mod()._safe_edit_message(existing, embed=embed)
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

        posted = await self._send_channel_message(channel, embed=embed)
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

        guild = self._safe_get_guild(guild_id)
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

    def _memberlist_slot_embed(self, raid: RaidRecord, *, day_label: str, time_label: str, users: list[int]):
        total_users = len(users)
        required_label = memberlist_target_label(raid.min_players)
        user_lines = self._plain_user_list_for_embed(raid.guild_id, set(users), limit=40)
        guild_name = self._guild_display_name(raid.guild_id)

        embed = discord.Embed(
            title=f"✅ Teilnehmerliste: {raid.dungeon}",
            description=(
                f"Server: **{guild_name}**\n"
                f"Raid: `{raid.display_id}`"
            ),
            color=discord.Color.teal(),
        )
        embed.add_field(name="📅 Datum", value=f"`{day_label}`", inline=True)
        embed.add_field(name="🕒 Uhrzeit", value=f"`{time_label}`", inline=True)
        embed.add_field(name="👥 Teilnehmer", value=f"`{total_users} / {required_label}`", inline=True)
        embed.add_field(name="Spielerliste", value=user_lines, inline=False)
        embed.set_footer(text="Automatisch aktualisiert durch DMW Bot")
        return embed

    async def _refresh_planner_message(self, raid_id: int):
        from views.raid_views import RaidVoteView

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
        view = RaidVoteView(cast("RewriteDiscordBot", self), raid.id, days, times)

        if raid.message_id:
            existing = await _runtime_mod()._safe_fetch_message(channel, raid.message_id)
            if existing is not None:
                edited = await _runtime_mod()._safe_edit_message(existing, embed=embed, view=view, content=None)
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
        message = await _runtime_mod()._safe_fetch_message(channel, message_id)
        if message is None:
            return

        title = f"Raid geschlossen: {reason}"
        description = f"Guild `{self._guild_display_name(guild_id)}`"
        if attendance_rows is not None:
            description += f"\nAttendance Rows: `{attendance_rows}`"
        embed = discord.Embed(title=title, description=description, color=discord.Color.red())
        await _runtime_mod()._safe_edit_message(message, embed=embed, view=None, content=None)

    async def _delete_slot_message(self, row: RaidPostedSlotRecord) -> bool:
        if row.channel_id is None or row.message_id is None:
            return False
        channel = await self._get_text_channel(row.channel_id)
        if channel is None:
            return False
        message = await _runtime_mod()._safe_fetch_message(channel, row.message_id)
        if message is None:
            return False
        return await _runtime_mod()._safe_delete_message(message)

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
        for row in list(self.repo.list_debug_cache(kind=BOT_MESSAGE_KIND, guild_id=guild_id, raid_id=channel_id)):
            if int(row.message_id or 0) != int(message_id):
                continue
            self.repo.delete_debug_cache(row.cache_key)

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
                message = await _runtime_mod()._safe_fetch_message(channel, int(message_id))
                if message is None:
                    self._clear_bot_message_index_for_id(guild_id=guild_id, channel_id=channel_id, message_id=message_id)
                    self._clear_known_message_refs_for_id(guild_id=guild_id, channel_id=channel_id, message_id=message_id)
                    continue

                author_id = int(getattr(getattr(message, "author", None), "id", 0) or 0)
                if author_id > 0 and author_id != bot_user_id:
                    self._clear_bot_message_index_for_id(guild_id=guild_id, channel_id=channel_id, message_id=message_id)
                    continue

                if await _runtime_mod()._safe_delete_message(message):
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
                if await _runtime_mod()._safe_delete_message(message):
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
            await self._cleanup_slot_temp_roles_for_raid(raid)
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
        # Legacy single-role support for already existing raids.
        if raid.min_players <= 0:
            return None
        guild = self._safe_get_guild(raid.guild_id)
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

    @staticmethod
    def _slot_temp_role_name(raid: RaidRecord, *, day_label: str, time_label: str) -> str:
        base = f"DMW Raid {raid.display_id} {day_label} {time_label}"
        return base[:95]

    async def _ensure_slot_temp_role(self, raid: RaidRecord, *, day_label: str, time_label: str):
        guild = self._safe_get_guild(raid.guild_id)
        if guild is None:
            return None

        cache_key = self._slot_temp_role_cache_key(raid.id, day_label, time_label)
        cached = self.repo.get_debug_cache(cache_key)
        if cached is not None and cached.kind == SLOT_TEMP_ROLE_KIND and cached.message_id:
            role = guild.get_role(int(cached.message_id))
            if role is not None:
                return role

        role_name = self._slot_temp_role_name(raid, day_label=day_label, time_label=time_label)
        role = discord.utils.get(guild.roles, name=role_name)
        if role is None:
            try:
                role = await guild.create_role(name=role_name, mentionable=True, reason="DMW Raid slot role")
            except Exception:
                return None

        self.repo.upsert_debug_cache(
            cache_key=cache_key,
            kind=SLOT_TEMP_ROLE_KIND,
            guild_id=raid.guild_id,
            raid_id=raid.id,
            message_id=int(role.id),
            payload_hash=sha256_text(role_name),
        )
        return role

    async def _sync_slot_role_members(self, raid: RaidRecord, *, role: Any, user_ids: list[int]) -> None:
        guild = self._safe_get_guild(raid.guild_id)
        if guild is None or role is None:
            return
        desired_ids = {int(user_id) for user_id in user_ids if int(user_id) > 0}
        current_ids = {int(getattr(member, "id", 0) or 0) for member in list(getattr(role, "members", []) or [])}
        current_ids.discard(0)

        add_ids = sorted(desired_ids - current_ids)
        remove_ids = sorted(current_ids - desired_ids)

        for member_id in add_ids:
            member = guild.get_member(member_id)
            if member is None or getattr(member, "bot", False):
                continue
            try:
                await member.add_roles(role, reason="DMW Raid slot vote")
            except Exception:
                continue

        for member_id in remove_ids:
            member = guild.get_member(member_id)
            if member is None:
                continue
            try:
                await member.remove_roles(role, reason="DMW Raid slot vote removed")
            except Exception:
                continue

    async def _resolve_role_by_id(self, guild: Any, role_id: int | None):
        normalized_id = int(role_id or 0)
        if normalized_id <= 0:
            return None
        role = guild.get_role(normalized_id)
        if role is not None:
            return role
        fetch_roles = getattr(guild, "fetch_roles", None)
        if not callable(fetch_roles):
            return None
        try:
            rows_result = fetch_roles()
            rows = await self._await_if_needed(rows_result)
        except Exception:
            return None
        try:
            iterator = list(rows or [])
        except TypeError:
            return None
        for candidate in iterator:
            if int(getattr(candidate, "id", 0) or 0) == normalized_id:
                return candidate
        return None

    async def _cleanup_role_members_and_delete(self, role: Any, *, reason: str) -> None:
        for member in list(getattr(role, "members", []) or []):
            try:
                remove_roles = getattr(member, "remove_roles", None)
                if callable(remove_roles):
                    await self._await_if_needed(remove_roles(role, reason=reason))
            except Exception:
                continue
        try:
            delete_role = getattr(role, "delete", None)
            if callable(delete_role):
                await self._await_if_needed(delete_role(reason=reason))
        except Exception:
            pass

    async def _cleanup_slot_temp_role(self, raid: RaidRecord, *, day_label: str, time_label: str) -> None:
        cache_key = self._slot_temp_role_cache_key(raid.id, day_label, time_label)
        reminder_key = self._raid_reminder_cache_key(raid.id, day_label, time_label)
        row = self.repo.get_debug_cache(cache_key)
        self.repo.delete_debug_cache(reminder_key)
        if row is None or row.kind != SLOT_TEMP_ROLE_KIND:
            return
        guild = self._safe_get_guild(raid.guild_id)
        if guild is None:
            self.repo.delete_debug_cache(cache_key)
            return
        role = await self._resolve_role_by_id(guild, int(row.message_id or 0))
        if role is not None:
            await self._cleanup_role_members_and_delete(role, reason="DMW Raid slot closed")
        self.repo.delete_debug_cache(cache_key)

    async def _cleanup_slot_temp_roles_for_raid(self, raid: RaidRecord) -> None:
        rows = list(self.repo.list_debug_cache(kind=SLOT_TEMP_ROLE_KIND, guild_id=raid.guild_id, raid_id=raid.id))
        guild = self._safe_get_guild(raid.guild_id)
        if guild is None:
            for row in rows:
                self.repo.delete_debug_cache(row.cache_key)
            return
        known_role_ids: set[int] = set()
        for row in rows:
            role_id = int(row.message_id or 0)
            if role_id > 0:
                known_role_ids.add(role_id)
            role = await self._resolve_role_by_id(guild, role_id)
            if role is not None:
                await self._cleanup_role_members_and_delete(role, reason="DMW Raid finished")
            self.repo.delete_debug_cache(row.cache_key)

        # Fallback: if cache rows are missing, still remove slot roles that match this raid's role prefix.
        if not rows and raid.display_id is not None:
            prefix = f"DMW Raid {raid.display_id} "
            for role in list(getattr(guild, "roles", []) or []):
                role_id = int(getattr(role, "id", 0) or 0)
                role_name = str(getattr(role, "name", "") or "")
                if role_id <= 0 or role_id in known_role_ids:
                    continue
                if not role_name.startswith(prefix):
                    continue
                await self._cleanup_role_members_and_delete(role, reason="DMW Raid finished")

    def _clear_raid_reminder_cache(self, raid: RaidRecord) -> None:
        rows = list(self.repo.list_debug_cache(kind=RAID_REMINDER_KIND, guild_id=raid.guild_id, raid_id=raid.id))
        for row in rows:
            self.repo.delete_debug_cache(row.cache_key)

    async def _cleanup_temp_role(self, raid: RaidRecord) -> None:
        await self._cleanup_slot_temp_roles_for_raid(raid)
        self._clear_raid_reminder_cache(raid)
        if not raid.temp_role_id:
            return
        guild = self._safe_get_guild(raid.guild_id)
        if guild is None:
            return
        role = await self._resolve_role_by_id(guild, int(raid.temp_role_id))
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
        # If the configured participants channel is not accessible or missing, try a fallback
        target_channel = participants_channel
        if target_channel is None:
            # Fallback to planner channel if we cannot post to the participants channel
            planner_id = getattr(settings, "planner_channel_id", None)
            if not planner_id:
                return (0, 0, 0)
            target_channel = await self._get_text_channel(planner_id)
            if target_channel is None:
                return (0, 0, 0)
            log.warning(
                "Participants channel not accessible for raid_id=%s guild_id=%s; falling back to planner channel (id=%s)",
                raid.id,
                raid.guild_id,
                planner_id,
            )

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
        # Debug: log when no qualified slots exist to help diagnose missing participant lists
        if not qualified_slots:
            log.info(
                "No qualified memberlist slots for raid_id=%s guild_id=%s days=%s times=%s day_votes=%s time_votes=%s threshold=%s",
                raid.id,
                raid.guild_id,
                days,
                times,
                {d: len(v) for d, v in day_users.items()},
                {t: len(v) for t, v in time_users.items()},
                threshold,
            )
        

        existing_rows = self.repo.list_posted_slots(raid.id)
        active_keys: set[tuple[str, str]] = set()
        created = 0
        updated = 0
        deleted = 0
        debug_lines: list[str] = []
        roles_enabled = True

        for (day_label, time_label), users in qualified_slots.items():
            active_keys.add((day_label, time_label))
            embed = self._memberlist_slot_embed(
                raid,
                day_label=day_label,
                time_label=time_label,
                users=users,
            )
            content = None
            slot_role = None
            if roles_enabled:
                slot_role = await self._ensure_slot_temp_role(raid, day_label=day_label, time_label=time_label)
                if slot_role is not None:
                    await self._sync_slot_role_members(raid, role=slot_role, user_ids=users)
                    # Role wird nicht mehr bei der Memberliste gepingt, sondern nur beim Raid Reminder
            debug_lines.append(f"- {day_label} {time_label}: {', '.join(f'<@{u}>' for u in users)}")
            row = existing_rows.get((day_label, time_label))
            old_msg_for_recreate = None

            edited = False
            if row is not None and row.message_id is not None and not recreate_existing:
                existing_channel = await self._get_text_channel(row.channel_id or target_channel.id)
                if existing_channel is not None:
                    old_msg = await _runtime_mod()._safe_fetch_message(existing_channel, row.message_id)
                    if old_msg is not None:
                        edited = await _runtime_mod()._safe_edit_message(
                            old_msg,
                            content=content,
                            embed=embed,
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
                    old_msg_for_recreate = await _runtime_mod()._safe_fetch_message(existing_channel, row.message_id)

            if edited:
                continue

            new_msg = await self._send_channel_message(
                target_channel,
                content=content,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            )
            if new_msg is None:
                continue
            self.repo.upsert_posted_slot(
                raid_id=raid.id,
                day_label=day_label,
                time_label=time_label,
                channel_id=target_channel.id,
                message_id=new_msg.id,
            )
            if row is None:
                created += 1
            else:
                updated += 1

            if old_msg_for_recreate is not None and getattr(old_msg_for_recreate, "id", None) != getattr(new_msg, "id", None):
                await _runtime_mod()._safe_delete_message(old_msg_for_recreate)

        for key, row in list(existing_rows.items()):
            if key in active_keys:
                continue
            await self._cleanup_slot_temp_role(raid, day_label=key[0], time_label=key[1])
            await self._delete_slot_message(row)
            self.repo.delete_posted_slot(row.id)
            deleted += 1

        debug_body = self._format_debug_report(
            topic="Memberlist Debug",
            guild_id=raid.guild_id,
            summary=[
                f"Raid: {raid.display_id}",
                f"Dungeon: {raid.dungeon}",
                f"Qualified Slots: {len(debug_lines)}",
            ],
            lines=debug_lines,
            empty_text="- Keine qualifizierten Slots.",
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

    @staticmethod
    def _raid_jump_url(guild_id: int, channel_id: int, message_id: int | None) -> str:
        if not message_id:
            return "`(noch kein Link)`"
        return f"https://discord.com/channels/{int(guild_id)}/{int(channel_id)}/{int(message_id)}"

    def _build_raidlist_embed(
        self,
        *,
        guild_id: int,
        guild_name: str,
        raids: list[RaidRecord],
        language: str = "de",
    ) -> tuple[Any, str, list[str]]:
        lang = "de" if language == "de" else "en"
        now_utc = datetime.now(UTC)
        embed = discord.Embed(
            title=get_string(lang, "raidlist_title"),
            color=discord.Color.gold(),
            timestamp=now_utc,
        )
        debug_lines: list[str] = []
        payload_parts = [f"guild={guild_id}", f"name={guild_name}"]

        if not raids:
            embed.description = get_string(lang, "raidlist_no_raids", server=guild_name)
            embed.set_footer(text=get_string(lang, "footer_auto_updated"))
            payload = "\n".join(payload_parts + ["empty=1"])
            return embed, sha256_text(payload), ["- " + get_string(lang, "raidlist_no_raids_short")]

        total_qualified_slots = 0
        global_next_start: datetime | None = None
        global_next_label: str = "—"

        # Summary Section
        summary_content = get_string(lang, "raidlist_server", server=guild_name)
        embed.add_field(
            name=get_string(lang, "raidlist_overview"),
            value=summary_content,
            inline=False,
        )

        for raid in raids[:25]:
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
            complete_voters = len(set().union(*day_users.values()).intersection(set().union(*time_users.values())))

            timezone_name = DEFAULT_TIMEZONE_NAME

            slot_starts: list[tuple[datetime, str, str]] = []
            for day_label, time_label in qualified_slots:
                start_at = self._parse_slot_start_at_utc(
                    day_label,
                    time_label,
                    timezone_name=timezone_name,
                )
                if start_at is None:
                    continue
                slot_starts.append((start_at, day_label, time_label))
            slot_starts.sort(key=lambda item: item[0])

            next_slot_text = "—"
            next_slot_start: datetime | None = None
            if slot_starts:
                upcoming = [entry for entry in slot_starts if entry[0] >= now_utc]
                chosen = upcoming[0] if upcoming else slot_starts[0]
                next_slot_start, next_day, next_time = chosen
                unix_ts = int(next_slot_start.timestamp())
                next_slot_text = f"\n**{next_day} {next_time}** • <t:{unix_ts}:f> (<t:{unix_ts}:R>)"

                if global_next_start is None or (
                    next_slot_start >= now_utc
                    and (global_next_start < now_utc or next_slot_start < global_next_start)
                ):
                    global_next_start = next_slot_start
                    global_next_label = get_string(lang, "raidlist_next_raid", display_id=raid.display_id, day=next_day, time=next_time)

            total_qualified_slots += len(qualified_slots)
            jump_url = self._raid_jump_url(guild_id, raid.channel_id, raid.message_id)
            required_label = memberlist_target_label(raid.min_players)
            
            field_name = get_string(lang, "raidlist_raid_field", display_id=raid.display_id, dungeon=raid.dungeon)
            field_value = (
                get_string(lang, "raidlist_minimum", players=required_label) + "\n"
                + get_string(lang, "raidlist_qualified_slots", count=len(qualified_slots)) + "\n"
                + get_string(lang, "raidlist_votes", count=complete_voters) + "\n"
                + get_string(lang, "raidlist_timezone", tz=timezone_name) + "\n"
                + get_string(lang, "raidlist_next_slot") + f": {next_slot_text}\n"
                + f"[{get_string(lang, 'raidlist_view_raid')}]({jump_url})"
            )
            
            if len(field_name) > 256:
                field_name = f"{field_name[:253]}..."
            if len(field_value) > 1024:
                field_value = f"{field_value[:1021]}..."
            embed.add_field(name=field_name, value=field_value, inline=False)

            debug_lines.append(
                f"- Raid {raid.display_id} ({raid.dungeon}) tz={timezone_name} slots={len(qualified_slots)} next={next_slot_text}"
            )
            payload_parts.append(
                "|".join(
                    [
                        f"raid={raid.id}",
                        f"display={raid.display_id}",
                        f"dungeon={raid.dungeon}",
                        f"creator={raid.creator_id}",
                        f"min={raid.min_players}",
                        f"tz={timezone_name}",
                        f"days={','.join(sorted(days))}",
                        f"times={','.join(sorted(times))}",
                        f"qualified={','.join(sorted(f'{d}@{t}' for d, t in qualified_slots))}",
                        f"msg={int(raid.message_id or 0)}",
                    ]
                )
            )

        # Statistics Section
        summary_parts = [
            get_string(lang, "raidlist_stats_raids", count=len(raids)),
            get_string(lang, "raidlist_stats_slots", count=total_qualified_slots),
            get_string(lang, "raidlist_stats_zone", tz=DEFAULT_TIMEZONE_NAME),
        ]
        if global_next_start is not None:
            summary_parts.append(f"🕐 {get_string(lang, 'raidlist_next_start')}: {global_next_label}")
        
        embed.add_field(
            name=get_string(lang, "raidlist_statistics"),
            value=" | ".join(summary_parts),
            inline=False,
        )
        
        embed.set_footer(text=get_string(lang, "footer_auto_updated"))

        payload_hash = sha256_text("\n".join(payload_parts))
        return embed, payload_hash, debug_lines

    async def _refresh_raidlist_for_guild(self, guild_id: int, *, force: bool = False) -> bool:
        settings = self.repo.ensure_settings(guild_id)
        if not settings.raidlist_channel_id:
            return False

        guild = self.get_guild(guild_id)
        guild_name = guild.name if guild is not None else (settings.guild_name or self._guild_display_name(guild_id))
        raids = self.repo.list_open_raids(guild_id)
        language = settings.language if hasattr(settings, 'language') else "de"
        embed, payload_hash, debug_lines = self._build_raidlist_embed(
            guild_id=guild_id,
            guild_name=guild_name,
            raids=raids,
            language=language,
        )
        debug_payload = self._format_debug_report(
            topic="Raidlist Debug",
            guild_id=guild_id,
            summary=[
                f"Title: Raidliste {guild_name}",
                f"Open Raids: {len(raids)}",
                f"Payload Hash: {payload_hash[:16]}",
            ],
            lines=debug_lines,
            empty_text="- Keine Raidlist-Daten.",
        )

        if not force and self._raidlist_hash_by_guild.get(guild_id) == payload_hash:
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

        if settings.raidlist_message_id:
            message = await _runtime_mod()._safe_fetch_message(channel, settings.raidlist_message_id)
            if message is not None:
                if await _runtime_mod()._safe_edit_message(message, content=None, embed=embed):
                    self._raidlist_hash_by_guild[guild_id] = payload_hash
                    await self._mirror_debug_payload(
                        debug_channel_id=int(self.config.raidlist_debug_channel_id),
                        cache_key=f"raidlist:{guild_id}:0",
                        kind="raidlist",
                        guild_id=guild_id,
                        raid_id=None,
                        content=debug_payload,
                    )
                    return True

        posted = await self._send_channel_message(channel, embed=embed)
        if posted is None:
            return False
        settings.raidlist_message_id = posted.id
        self._raidlist_hash_by_guild[guild_id] = payload_hash
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
            persisted = await self._persist(dirty_tables={"settings", "debug_cache"})
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

            if int(interaction.user.id) != int(raid.creator_id):
                msg = "Nur der Raid-Ersteller darf den Raid beenden."
                if deferred:
                    await _safe_followup(interaction, msg, ephemeral=True)
                else:
                    await self._reply(interaction, msg, ephemeral=True)
                return

            # Ensure temp roles are cleaned even if raid rows are removed right after.
            await self._cleanup_temp_role(raid)
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
