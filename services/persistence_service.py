from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence, TypeVar, cast

from sqlalchemy import and_, bindparam, delete, insert, select, tuple_, update

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


_ChunkItem = TypeVar("_ChunkItem")


@dataclass(frozen=True)
class _TableSpec:
    name: str
    model: type[Any]
    pk_columns: tuple[str, ...]


class RepositoryPersistence:
    _DELETE_CHUNK_SIZE = 500
    _INSERT_CHUNK_SIZE = 500
    _UPDATE_CHUNK_SIZE = 500
    _FULL_SCAN_EVERY_HINTED_FLUSHES = 25
    _TABLE_SPECS: dict[str, _TableSpec] = {
        "settings": _TableSpec("settings", GuildSettings, ("guild_id",)),
        "dungeons": _TableSpec("dungeons", Dungeon, ("id",)),
        "raids": _TableSpec("raids", Raid, ("id",)),
        "raid_options": _TableSpec("raid_options", RaidOption, ("id",)),
        "raid_votes": _TableSpec("raid_votes", RaidVote, ("id",)),
        "raid_posted_slots": _TableSpec("raid_posted_slots", RaidPostedSlot, ("id",)),
        "raid_templates": _TableSpec("raid_templates", RaidTemplate, ("id",)),
        "raid_attendance": _TableSpec("raid_attendance", RaidAttendance, ("id",)),
        "user_levels": _TableSpec("user_levels", UserLevel, ("guild_id", "user_id")),
        "debug_cache": _TableSpec("debug_cache", DebugMirrorCache, ("cache_key",)),
    }
    _INSERT_UPDATE_ORDER: tuple[str, ...] = (
        "settings",
        "dungeons",
        "raids",
        "raid_options",
        "raid_votes",
        "raid_posted_slots",
        "raid_templates",
        "raid_attendance",
        "user_levels",
        "debug_cache",
    )
    _DELETE_ORDER: tuple[str, ...] = (
        "raid_votes",
        "raid_options",
        "raid_posted_slots",
        "raid_templates",
        "raids",
        "raid_attendance",
        "user_levels",
        "debug_cache",
        "dungeons",
        "settings",
    )
    _TABLE_FIELDS: dict[str, tuple[str, ...]] = {
        "dungeons": ("id", "name", "short_code", "is_active", "sort_order"),
        "settings": (
            "guild_id",
            "guild_name",
            "participants_channel_id",
            "raidlist_channel_id",
            "raidlist_message_id",
            "planner_channel_id",
            "default_min_players",
            "templates_enabled",
            "template_manager_role_id",
        ),
        "raids": (
            "id",
            "display_id",
            "guild_id",
            "channel_id",
            "creator_id",
            "dungeon",
            "status",
            "created_at",
            "message_id",
            "min_players",
            "participants_posted",
            "temp_role_id",
            "temp_role_created",
        ),
        "raid_options": ("id", "raid_id", "kind", "label"),
        "raid_votes": ("id", "raid_id", "kind", "option_label", "user_id"),
        "raid_posted_slots": ("id", "raid_id", "day_label", "time_label", "channel_id", "message_id"),
        "raid_templates": ("id", "guild_id", "dungeon_id", "template_name", "template_data"),
        "raid_attendance": ("id", "guild_id", "raid_display_id", "dungeon", "user_id", "status", "marked_by_user_id"),
        "user_levels": ("guild_id", "user_id", "xp", "level", "username"),
        "debug_cache": ("cache_key", "kind", "guild_id", "raid_id", "message_id", "payload_hash"),
    }

    def __init__(self, config: BotConfig) -> None:
        self.session_manager = SessionManager(config)
        self._lock = asyncio.Lock()
        self._last_flush_rows: dict[str, dict[object, dict[str, object]]] | None = None
        self._hinted_flushes_since_full_scan = 0

    @staticmethod
    def _table_rows_map(repo: InMemoryRepository, table_name: str) -> Mapping[Any, Any]:
        if table_name == "dungeons":
            return repo.dungeons
        if table_name == "settings":
            return repo.settings
        if table_name == "raids":
            return repo.raids
        if table_name == "raid_options":
            return repo.raid_options
        if table_name == "raid_votes":
            return repo.raid_votes
        if table_name == "raid_posted_slots":
            return repo.raid_posted_slots
        if table_name == "raid_templates":
            return repo.raid_templates
        if table_name == "raid_attendance":
            return repo.raid_attendance
        if table_name == "user_levels":
            return repo.user_levels
        if table_name == "debug_cache":
            return repo.debug_cache
        raise KeyError(f"Unsupported table name: {table_name}")

    def _snapshot_rows_for_tables(
        self,
        repo: InMemoryRepository,
        table_names: set[str] | tuple[str, ...] | list[str],
    ) -> dict[str, dict[object, dict[str, object]]]:
        snapshot: dict[str, dict[object, dict[str, object]]] = {}
        for table_name in table_names:
            rows = self._table_rows_map(repo, table_name)
            fields = self._TABLE_FIELDS[table_name]
            snapshot[table_name] = {
                key: {field: getattr(row, field) for field in fields}
                for key, row in rows.items()
            }
        return snapshot

    def _snapshot_rows(self, repo: InMemoryRepository) -> dict[str, dict[object, dict[str, object]]]:
        return self._snapshot_rows_for_tables(repo, list(self._TABLE_SPECS.keys()))

    @classmethod
    def _normalize_dirty_table_hints(cls, dirty_tables: Iterable[str] | None) -> set[str]:
        if dirty_tables is None:
            return set()
        return {str(table_name) for table_name in dirty_tables if str(table_name) in cls._TABLE_SPECS}

    @staticmethod
    def _stable_sort_key(value: object) -> str:
        return repr(value)

    @staticmethod
    def _pk_clause(spec: _TableSpec, key: object):
        if len(spec.pk_columns) == 1:
            return getattr(spec.model, spec.pk_columns[0]) == key
        if not isinstance(key, tuple):
            raise ValueError(f"Composite key expected for table {spec.name}")
        if len(key) != len(spec.pk_columns):
            raise ValueError(f"Invalid key shape for table {spec.name}")
        return and_(*[getattr(spec.model, column) == key[index] for index, column in enumerate(spec.pk_columns)])

    @staticmethod
    def _pk_bind_params(spec: _TableSpec, key: object) -> dict[str, object]:
        if len(spec.pk_columns) == 1:
            return {f"pk_{spec.pk_columns[0]}": key}
        if not isinstance(key, tuple):
            raise ValueError(f"Composite key expected for table {spec.name}")
        if len(key) != len(spec.pk_columns):
            raise ValueError(f"Invalid key shape for table {spec.name}")
        return {f"pk_{column}": key[index] for index, column in enumerate(spec.pk_columns)}

    @staticmethod
    def _pk_bind_clause(spec: _TableSpec):
        clauses = [
            getattr(spec.model, column) == bindparam(f"pk_{column}")
            for column in spec.pk_columns
        ]
        if len(clauses) == 1:
            return clauses[0]
        return and_(*clauses)

    @staticmethod
    def _iter_chunks(values: Sequence[_ChunkItem], chunk_size: int):
        for index in range(0, len(values), chunk_size):
            yield values[index : index + chunk_size]

    async def _apply_table_deletes(
        self,
        session: Any,
        spec: _TableSpec,
        previous_rows: dict[object, dict[str, object]],
        current_rows: dict[object, dict[str, object]],
    ) -> None:
        removed_keys = sorted(set(previous_rows) - set(current_rows), key=self._stable_sort_key)
        if not removed_keys:
            return

        if len(spec.pk_columns) == 1:
            pk_column = getattr(spec.model, spec.pk_columns[0])
            for key_chunk in self._iter_chunks(removed_keys, self._DELETE_CHUNK_SIZE):
                await session.execute(delete(spec.model).where(pk_column.in_(key_chunk)))
            return

        pk_expr = tuple_(*[getattr(spec.model, column) for column in spec.pk_columns])
        for key_chunk in self._iter_chunks(removed_keys, self._DELETE_CHUNK_SIZE):
            await session.execute(delete(spec.model).where(pk_expr.in_(key_chunk)))

    async def _apply_table_upserts(
        self,
        session: Any,
        spec: _TableSpec,
        previous_rows: dict[object, dict[str, object]],
        current_rows: dict[object, dict[str, object]],
    ) -> None:
        previous_keys = set(previous_rows)
        current_keys = set(current_rows)
        changed_keys = sorted(
            [key for key in (current_keys & previous_keys) if current_rows[key] != previous_rows[key]],
            key=self._stable_sort_key,
        )
        updates_by_columns: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
        for key in changed_keys:
            previous_row = previous_rows[key]
            values = {
                column: value
                for column, value in current_rows[key].items()
                if column not in spec.pk_columns and previous_row.get(column) != value
            }
            if not values:
                continue
            change_group = tuple(sorted(values.keys()))
            update_payload = self._pk_bind_params(spec, key)
            update_payload.update(values)
            updates_by_columns[change_group].append(update_payload)

        for change_group in sorted(updates_by_columns):
            payload_rows = updates_by_columns[change_group]
            statement = update(spec.model).where(self._pk_bind_clause(spec)).values(
                **{column: bindparam(column) for column in change_group}
            )
            for payload_chunk in self._iter_chunks(payload_rows, self._UPDATE_CHUNK_SIZE):
                await session.execute(statement, payload_chunk)

        added_keys = sorted(current_keys - previous_keys, key=self._stable_sort_key)
        for key_chunk in self._iter_chunks(added_keys, self._INSERT_CHUNK_SIZE):
            await session.execute(insert(spec.model), [current_rows[key] for key in key_chunk])

    async def _fetch_table_rows(self, session: Any, table_name: str) -> list[dict[str, Any]]:
        spec = self._TABLE_SPECS[table_name]
        columns = [getattr(spec.model, column_name) for column_name in self._TABLE_FIELDS[table_name]]
        result = await session.execute(select(*columns))
        return cast(list[dict[str, Any]], result.mappings().all())

    async def load(self, repo: InMemoryRepository) -> None:
        async with self._lock:
            repo.reset()
            async with self.session_manager.session_scope() as session:
                dungeons = await self._fetch_table_rows(session, "dungeons")
                settings = await self._fetch_table_rows(session, "settings")
                raids = await self._fetch_table_rows(session, "raids")
                options = await self._fetch_table_rows(session, "raid_options")
                votes = await self._fetch_table_rows(session, "raid_votes")
                slots = await self._fetch_table_rows(session, "raid_posted_slots")
                templates = await self._fetch_table_rows(session, "raid_templates")
                attendance = await self._fetch_table_rows(session, "raid_attendance")
                levels = await self._fetch_table_rows(session, "user_levels")
                debug_rows = await self._fetch_table_rows(session, "debug_cache")

            for row in dungeons:
                repo.dungeons[int(row["id"])] = DungeonRecord(
                    id=int(row["id"]),
                    name=str(row["name"]),
                    short_code=str(row["short_code"]),
                    is_active=bool(row["is_active"]),
                    sort_order=int(row["sort_order"] or 0),
                )

            for row in settings:
                repo.settings[int(row["guild_id"])] = GuildSettingsRecord(
                    guild_id=int(row["guild_id"]),
                    guild_name=row["guild_name"],
                    participants_channel_id=int(row["participants_channel_id"]) if row["participants_channel_id"] else None,
                    raidlist_channel_id=int(row["raidlist_channel_id"]) if row["raidlist_channel_id"] else None,
                    raidlist_message_id=int(row["raidlist_message_id"]) if row["raidlist_message_id"] else None,
                    planner_channel_id=int(row["planner_channel_id"]) if row["planner_channel_id"] else None,
                    default_min_players=int(row["default_min_players"] or 0),
                    templates_enabled=bool(row["templates_enabled"]),
                    template_manager_role_id=int(row["template_manager_role_id"]) if row["template_manager_role_id"] else None,
                )

            for row in raids:
                repo.raids[int(row["id"])] = RaidRecord(
                    id=int(row["id"]),
                    display_id=int(row["display_id"] or 0),
                    guild_id=int(row["guild_id"]),
                    channel_id=int(row["channel_id"]),
                    creator_id=int(row["creator_id"]),
                    dungeon=str(row["dungeon"]),
                    status=str(row["status"]),
                    created_at=row["created_at"],
                    message_id=int(row["message_id"]) if row["message_id"] else None,
                    min_players=int(row["min_players"] or 0),
                    participants_posted=bool(row["participants_posted"]),
                    temp_role_id=int(row["temp_role_id"]) if row["temp_role_id"] else None,
                    temp_role_created=bool(row["temp_role_created"]),
                )

            for row in options:
                repo.raid_options[int(row["id"])] = RaidOptionRecord(
                    id=int(row["id"]),
                    raid_id=int(row["raid_id"]),
                    kind=str(row["kind"]),
                    label=str(row["label"]),
                )

            for row in votes:
                repo.raid_votes[int(row["id"])] = RaidVoteRecord(
                    id=int(row["id"]),
                    raid_id=int(row["raid_id"]),
                    kind=str(row["kind"]),
                    option_label=str(row["option_label"]),
                    user_id=int(row["user_id"]),
                )

            for row in slots:
                repo.raid_posted_slots[int(row["id"])] = RaidPostedSlotRecord(
                    id=int(row["id"]),
                    raid_id=int(row["raid_id"]),
                    day_label=str(row["day_label"]),
                    time_label=str(row["time_label"]),
                    channel_id=int(row["channel_id"]) if row["channel_id"] else None,
                    message_id=int(row["message_id"]) if row["message_id"] else None,
                )

            for row in templates:
                repo.raid_templates[int(row["id"])] = RaidTemplateRecord(
                    id=int(row["id"]),
                    guild_id=int(row["guild_id"]),
                    dungeon_id=int(row["dungeon_id"]),
                    template_name=str(row["template_name"]),
                    template_data=str(row["template_data"]),
                )

            for row in attendance:
                repo.raid_attendance[int(row["id"])] = RaidAttendanceRecord(
                    id=int(row["id"]),
                    guild_id=int(row["guild_id"]),
                    raid_display_id=int(row["raid_display_id"]),
                    dungeon=str(row["dungeon"]),
                    user_id=int(row["user_id"]),
                    status=str(row["status"]),
                    marked_by_user_id=int(row["marked_by_user_id"]) if row["marked_by_user_id"] else None,
                )

            for row in levels:
                repo.user_levels[(int(row["guild_id"]), int(row["user_id"]))] = UserLevelRecord(
                    guild_id=int(row["guild_id"]),
                    user_id=int(row["user_id"]),
                    xp=int(row["xp"] or 0),
                    level=int(row["level"] or 0),
                    username=row["username"],
                )

            for row in debug_rows:
                repo.debug_cache[str(row["cache_key"])] = DebugMirrorCacheRecord(
                    cache_key=str(row["cache_key"]),
                    kind=str(row["kind"]),
                    guild_id=int(row["guild_id"]),
                    raid_id=int(row["raid_id"]) if row["raid_id"] else None,
                    message_id=int(row["message_id"]),
                    payload_hash=str(row["payload_hash"]),
                )

            repo.recalculate_counters()
            snapshot = self._snapshot_rows(repo)
            self._last_flush_rows = snapshot
            self._hinted_flushes_since_full_scan = 0

    async def flush(self, repo: InMemoryRepository, *, dirty_tables: Iterable[str] | None = None) -> None:
        async with self._lock:
            if self._last_flush_rows is None:
                previous_snapshot = {table_name: {} for table_name in self._TABLE_SPECS}
                candidate_tables = set(self._TABLE_SPECS)
                self._hinted_flushes_since_full_scan = 0
            else:
                previous_snapshot = self._last_flush_rows
                hinted_tables = self._normalize_dirty_table_hints(dirty_tables)
                if not hinted_tables:
                    candidate_tables = set(self._TABLE_SPECS)
                    self._hinted_flushes_since_full_scan = 0
                else:
                    self._hinted_flushes_since_full_scan += 1
                    if self._hinted_flushes_since_full_scan >= self._FULL_SCAN_EVERY_HINTED_FLUSHES:
                        candidate_tables = set(self._TABLE_SPECS)
                        self._hinted_flushes_since_full_scan = 0
                    else:
                        candidate_tables = hinted_tables

            candidate_snapshot = self._snapshot_rows_for_tables(repo, candidate_tables)
            changed_tables = {
                table_name
                for table_name in candidate_tables
                if candidate_snapshot.get(table_name, {}) != previous_snapshot.get(table_name, {})
            }
            if not changed_tables:
                if self._last_flush_rows is None:
                    self._last_flush_rows = {
                        table_name: candidate_snapshot.get(table_name, {})
                        for table_name in self._TABLE_SPECS
                    }
                return
            snapshot = {
                table_name: previous_snapshot.get(table_name, {})
                for table_name in self._TABLE_SPECS
            }
            snapshot.update({table_name: candidate_snapshot[table_name] for table_name in changed_tables})

            async with self.session_manager.session_scope() as session:
                for table_name in self._DELETE_ORDER:
                    if table_name not in changed_tables:
                        continue
                    spec = self._TABLE_SPECS[table_name]
                    await self._apply_table_deletes(
                        session,
                        spec,
                        previous_snapshot.get(table_name, {}),
                        snapshot.get(table_name, {}),
                    )
                for table_name in self._INSERT_UPDATE_ORDER:
                    if table_name not in changed_tables:
                        continue
                    spec = self._TABLE_SPECS[table_name]
                    await self._apply_table_upserts(
                        session,
                        spec,
                        previous_snapshot.get(table_name, {}),
                        snapshot.get(table_name, {}),
                    )
            self._last_flush_rows = snapshot
