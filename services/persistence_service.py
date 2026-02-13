from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import date, datetime, time
import hashlib
import json

from sqlalchemy import delete, select

from bot.config import BotConfig
from db.models import (
    DebugMirrorCache,
    Dungeon,
    GuildSettings,
    Raid,
    RaidAttendance,
    RaidOption,
    RaidPostedSlot,
    RaidTemplate,
    RaidVote,
    UserLevel,
)
from db.repository import (
    DebugMirrorCacheRecord,
    DungeonRecord,
    GuildSettingsRecord,
    InMemoryRepository,
    RaidAttendanceRecord,
    RaidOptionRecord,
    RaidPostedSlotRecord,
    RaidRecord,
    RaidTemplateRecord,
    RaidVoteRecord,
    UserLevelRecord,
)
from db.session import SessionManager


class RepositoryPersistence:
    def __init__(self, config: BotConfig) -> None:
        self.session_manager = SessionManager(config)
        self._lock = asyncio.Lock()
        self._last_flush_fingerprint: str | None = None

    @staticmethod
    def _normalize_fingerprint_value(value: object) -> object:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, time):
            return value.isoformat()
        return value

    def _snapshot_fingerprint(self, repo: InMemoryRepository) -> str:
        def _rows_signature(rows: list[object]) -> list[dict[str, object]]:
            normalized_rows: list[dict[str, object]] = []
            for row in rows:
                data = asdict(row)
                normalized_rows.append(
                    {
                        key: self._normalize_fingerprint_value(value)
                        for key, value in sorted(data.items(), key=lambda item: item[0])
                    }
                )
            normalized_rows.sort(
                key=lambda payload: json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            )
            return normalized_rows

        payload = {
            "dungeons": _rows_signature(list(repo.dungeons.values())),
            "settings": _rows_signature(list(repo.settings.values())),
            "raids": _rows_signature(list(repo.raids.values())),
            "raid_options": _rows_signature(list(repo.raid_options.values())),
            "raid_votes": _rows_signature(list(repo.raid_votes.values())),
            "raid_posted_slots": _rows_signature(list(repo.raid_posted_slots.values())),
            "raid_templates": _rows_signature(list(repo.raid_templates.values())),
            "raid_attendance": _rows_signature(list(repo.raid_attendance.values())),
            "user_levels": _rows_signature(list(repo.user_levels.values())),
            "debug_cache": _rows_signature(list(repo.debug_cache.values())),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    async def load(self, repo: InMemoryRepository) -> None:
        async with self._lock:
            repo.reset()
            async with self.session_manager.session_scope() as session:
                dungeons = (await session.execute(select(Dungeon))).scalars().all()
                settings = (await session.execute(select(GuildSettings))).scalars().all()
                raids = (await session.execute(select(Raid))).scalars().all()
                options = (await session.execute(select(RaidOption))).scalars().all()
                votes = (await session.execute(select(RaidVote))).scalars().all()
                slots = (await session.execute(select(RaidPostedSlot))).scalars().all()
                templates = (await session.execute(select(RaidTemplate))).scalars().all()
                attendance = (await session.execute(select(RaidAttendance))).scalars().all()
                levels = (await session.execute(select(UserLevel))).scalars().all()
                debug_rows = (await session.execute(select(DebugMirrorCache))).scalars().all()

            for row in dungeons:
                repo.dungeons[int(row.id)] = DungeonRecord(
                    id=int(row.id),
                    name=row.name,
                    short_code=row.short_code,
                    is_active=bool(row.is_active),
                    sort_order=int(row.sort_order or 0),
                )

            for row in settings:
                repo.settings[int(row.guild_id)] = GuildSettingsRecord(
                    guild_id=int(row.guild_id),
                    guild_name=row.guild_name,
                    participants_channel_id=int(row.participants_channel_id) if row.participants_channel_id else None,
                    raidlist_channel_id=int(row.raidlist_channel_id) if row.raidlist_channel_id else None,
                    raidlist_message_id=int(row.raidlist_message_id) if row.raidlist_message_id else None,
                    planner_channel_id=int(row.planner_channel_id) if row.planner_channel_id else None,
                    default_min_players=int(row.default_min_players or 0),
                    templates_enabled=bool(row.templates_enabled),
                    template_manager_role_id=int(row.template_manager_role_id) if row.template_manager_role_id else None,
                )

            for row in raids:
                repo.raids[int(row.id)] = RaidRecord(
                    id=int(row.id),
                    display_id=int(row.display_id or 0),
                    guild_id=int(row.guild_id),
                    channel_id=int(row.channel_id),
                    creator_id=int(row.creator_id),
                    dungeon=row.dungeon,
                    status=row.status,
                    created_at=row.created_at,
                    message_id=int(row.message_id) if row.message_id else None,
                    min_players=int(row.min_players or 0),
                    participants_posted=bool(row.participants_posted),
                    temp_role_id=int(row.temp_role_id) if row.temp_role_id else None,
                    temp_role_created=bool(row.temp_role_created),
                )

            for row in options:
                repo.raid_options[int(row.id)] = RaidOptionRecord(
                    id=int(row.id),
                    raid_id=int(row.raid_id),
                    kind=row.kind,
                    label=row.label,
                )

            for row in votes:
                repo.raid_votes[int(row.id)] = RaidVoteRecord(
                    id=int(row.id),
                    raid_id=int(row.raid_id),
                    kind=row.kind,
                    option_label=row.option_label,
                    user_id=int(row.user_id),
                )

            for row in slots:
                repo.raid_posted_slots[int(row.id)] = RaidPostedSlotRecord(
                    id=int(row.id),
                    raid_id=int(row.raid_id),
                    day_label=row.day_label,
                    time_label=row.time_label,
                    channel_id=int(row.channel_id) if row.channel_id else None,
                    message_id=int(row.message_id) if row.message_id else None,
                )

            for row in templates:
                repo.raid_templates[int(row.id)] = RaidTemplateRecord(
                    id=int(row.id),
                    guild_id=int(row.guild_id),
                    dungeon_id=int(row.dungeon_id),
                    template_name=row.template_name,
                    template_data=row.template_data,
                )

            for row in attendance:
                repo.raid_attendance[int(row.id)] = RaidAttendanceRecord(
                    id=int(row.id),
                    guild_id=int(row.guild_id),
                    raid_display_id=int(row.raid_display_id),
                    dungeon=row.dungeon,
                    user_id=int(row.user_id),
                    status=row.status,
                    marked_by_user_id=int(row.marked_by_user_id) if row.marked_by_user_id else None,
                )

            for row in levels:
                repo.user_levels[(int(row.guild_id), int(row.user_id))] = UserLevelRecord(
                    guild_id=int(row.guild_id),
                    user_id=int(row.user_id),
                    xp=int(row.xp or 0),
                    level=int(row.level or 0),
                    username=row.username,
                )

            for row in debug_rows:
                repo.debug_cache[row.cache_key] = DebugMirrorCacheRecord(
                    cache_key=row.cache_key,
                    kind=row.kind,
                    guild_id=int(row.guild_id),
                    raid_id=int(row.raid_id) if row.raid_id else None,
                    message_id=int(row.message_id),
                    payload_hash=row.payload_hash,
                )

            repo.recalculate_counters()
            self._last_flush_fingerprint = self._snapshot_fingerprint(repo)

    async def flush(self, repo: InMemoryRepository) -> None:
        async with self._lock:
            fingerprint = self._snapshot_fingerprint(repo)
            if fingerprint == self._last_flush_fingerprint:
                return

            async with self.session_manager.session_scope() as session:
                # Delete dependent rows first.
                await session.execute(delete(RaidVote))
                await session.execute(delete(RaidOption))
                await session.execute(delete(RaidPostedSlot))
                await session.execute(delete(RaidAttendance))
                await session.execute(delete(RaidTemplate))
                await session.execute(delete(Raid))
                await session.execute(delete(UserLevel))
                await session.execute(delete(DebugMirrorCache))
                await session.execute(delete(Dungeon))
                await session.execute(delete(GuildSettings))

                session.add_all(
                    [
                        GuildSettings(
                            guild_id=row.guild_id,
                            guild_name=row.guild_name,
                            participants_channel_id=row.participants_channel_id,
                            raidlist_channel_id=row.raidlist_channel_id,
                            raidlist_message_id=row.raidlist_message_id,
                            planner_channel_id=row.planner_channel_id,
                            default_min_players=row.default_min_players,
                            templates_enabled=row.templates_enabled,
                            template_manager_role_id=row.template_manager_role_id,
                        )
                        for row in repo.settings.values()
                    ]
                )

                session.add_all(
                    [
                        Dungeon(
                            id=row.id,
                            name=row.name,
                            short_code=row.short_code,
                            is_active=row.is_active,
                            sort_order=row.sort_order,
                        )
                        for row in repo.dungeons.values()
                    ]
                )

                session.add_all(
                    [
                        Raid(
                            id=row.id,
                            display_id=row.display_id,
                            guild_id=row.guild_id,
                            channel_id=row.channel_id,
                            creator_id=row.creator_id,
                            dungeon=row.dungeon,
                            status=row.status,
                            created_at=row.created_at,
                            message_id=row.message_id,
                            min_players=row.min_players,
                            participants_posted=row.participants_posted,
                            temp_role_id=row.temp_role_id,
                            temp_role_created=row.temp_role_created,
                        )
                        for row in repo.raids.values()
                    ]
                )

                session.add_all(
                    [
                        RaidOption(
                            id=row.id,
                            raid_id=row.raid_id,
                            kind=row.kind,
                            label=row.label,
                        )
                        for row in repo.raid_options.values()
                    ]
                )

                session.add_all(
                    [
                        RaidVote(
                            id=row.id,
                            raid_id=row.raid_id,
                            kind=row.kind,
                            option_label=row.option_label,
                            user_id=row.user_id,
                        )
                        for row in repo.raid_votes.values()
                    ]
                )

                session.add_all(
                    [
                        RaidPostedSlot(
                            id=row.id,
                            raid_id=row.raid_id,
                            day_label=row.day_label,
                            time_label=row.time_label,
                            channel_id=row.channel_id,
                            message_id=row.message_id,
                        )
                        for row in repo.raid_posted_slots.values()
                    ]
                )

                session.add_all(
                    [
                        RaidTemplate(
                            id=row.id,
                            guild_id=row.guild_id,
                            dungeon_id=row.dungeon_id,
                            template_name=row.template_name,
                            template_data=row.template_data,
                        )
                        for row in repo.raid_templates.values()
                    ]
                )

                session.add_all(
                    [
                        RaidAttendance(
                            id=row.id,
                            guild_id=row.guild_id,
                            raid_display_id=row.raid_display_id,
                            dungeon=row.dungeon,
                            user_id=row.user_id,
                            status=row.status,
                            marked_by_user_id=row.marked_by_user_id,
                        )
                        for row in repo.raid_attendance.values()
                    ]
                )

                session.add_all(
                    [
                        UserLevel(
                            guild_id=row.guild_id,
                            user_id=row.user_id,
                            xp=row.xp,
                            level=row.level,
                            username=row.username,
                        )
                        for row in repo.user_levels.values()
                    ]
                )

                session.add_all(
                    [
                        DebugMirrorCache(
                            cache_key=row.cache_key,
                            kind=row.kind,
                            guild_id=row.guild_id,
                            raid_id=row.raid_id,
                            message_id=row.message_id,
                            payload_hash=row.payload_hash,
                        )
                        for row in repo.debug_cache.values()
                    ]
                )
            self._last_flush_fingerprint = fingerprint
