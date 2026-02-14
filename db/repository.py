from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(slots=True)
class DungeonRecord:
    id: int
    name: str
    short_code: str
    is_active: bool = True
    sort_order: int = 0


@dataclass(slots=True)
class GuildSettingsRecord:
    guild_id: int
    guild_name: str | None = None
    participants_channel_id: int | None = None
    raidlist_channel_id: int | None = None
    raidlist_message_id: int | None = None
    planner_channel_id: int | None = None
    default_min_players: int = 0
    templates_enabled: bool = True
    template_manager_role_id: int | None = None


@dataclass(slots=True)
class RaidRecord:
    id: int
    display_id: int
    guild_id: int
    channel_id: int
    creator_id: int
    dungeon: str
    status: str = "open"
    created_at: datetime = field(default_factory=datetime.now)
    message_id: int | None = None
    min_players: int = 0
    participants_posted: bool = False
    temp_role_id: int | None = None
    temp_role_created: bool = False


@dataclass(slots=True)
class RaidOptionRecord:
    id: int
    raid_id: int
    kind: str
    label: str


@dataclass(slots=True)
class RaidVoteRecord:
    id: int
    raid_id: int
    kind: str
    option_label: str
    user_id: int


@dataclass(slots=True)
class RaidPostedSlotRecord:
    id: int
    raid_id: int
    day_label: str
    time_label: str
    channel_id: int | None
    message_id: int | None


@dataclass(slots=True)
class RaidTemplateRecord:
    id: int
    guild_id: int
    dungeon_id: int
    template_name: str
    template_data: str


@dataclass(slots=True)
class RaidAttendanceRecord:
    id: int
    guild_id: int
    raid_display_id: int
    dungeon: str
    user_id: int
    status: str = "pending"
    marked_by_user_id: int | None = None


@dataclass(slots=True)
class UserLevelRecord:
    guild_id: int
    user_id: int
    xp: int = 0
    level: int = 0
    username: str | None = None


@dataclass(slots=True)
class DebugMirrorCacheRecord:
    cache_key: str
    kind: str
    guild_id: int
    raid_id: int | None
    message_id: int
    payload_hash: str


class InMemoryRepository:
    def __init__(self) -> None:
        self.dungeons: Dict[int, DungeonRecord] = {}
        self.settings: Dict[int, GuildSettingsRecord] = {}
        self.raids: Dict[int, RaidRecord] = {}
        self.raid_options: Dict[int, RaidOptionRecord] = {}
        self.raid_votes: Dict[int, RaidVoteRecord] = {}
        self.raid_posted_slots: Dict[int, RaidPostedSlotRecord] = {}
        self.raid_templates: Dict[int, RaidTemplateRecord] = {}
        self.raid_attendance: Dict[int, RaidAttendanceRecord] = {}
        self.user_levels: Dict[Tuple[int, int], UserLevelRecord] = {}
        self.debug_cache: Dict[str, DebugMirrorCacheRecord] = {}
        self._vote_id_by_key: Dict[Tuple[int, str, str, int], int] = {}
        self._debug_cache_keys_by_kind: Dict[str, set[str]] = {}
        self._debug_cache_keys_by_kind_guild: Dict[Tuple[str, int], set[str]] = {}
        self._debug_cache_keys_by_kind_guild_raid: Dict[Tuple[str, int, int | None], set[str]] = {}

        self._raid_id = 1
        self._option_id = 1
        self._vote_id = 1
        self._slot_id = 1
        self._template_id = 1
        self._attendance_id = 1
        self._display_id_by_guild: Dict[int, int] = {}

    def reset(self) -> None:
        self.dungeons.clear()
        self.settings.clear()
        self.raids.clear()
        self.raid_options.clear()
        self.raid_votes.clear()
        self.raid_posted_slots.clear()
        self.raid_templates.clear()
        self.raid_attendance.clear()
        self.user_levels.clear()
        self.debug_cache.clear()
        self._vote_id_by_key.clear()
        self._debug_cache_keys_by_kind.clear()
        self._debug_cache_keys_by_kind_guild.clear()
        self._debug_cache_keys_by_kind_guild_raid.clear()

        self._raid_id = 1
        self._option_id = 1
        self._vote_id = 1
        self._slot_id = 1
        self._template_id = 1
        self._attendance_id = 1
        self._display_id_by_guild = {}

    def recalculate_counters(self) -> None:
        self._raid_id = (max(self.raids.keys()) + 1) if self.raids else 1
        self._option_id = (max(self.raid_options.keys()) + 1) if self.raid_options else 1
        self._vote_id = (max(self.raid_votes.keys()) + 1) if self.raid_votes else 1
        self._slot_id = (max(self.raid_posted_slots.keys()) + 1) if self.raid_posted_slots else 1
        self._template_id = (max(self.raid_templates.keys()) + 1) if self.raid_templates else 1
        self._attendance_id = (max(self.raid_attendance.keys()) + 1) if self.raid_attendance else 1

        self._display_id_by_guild = {}
        for raid in self.raids.values():
            self._display_id_by_guild[raid.guild_id] = max(
                self._display_id_by_guild.get(raid.guild_id, 0),
                int(raid.display_id),
            )
        self._rebuild_vote_index()
        self._rebuild_debug_cache_indices()

    @staticmethod
    def _vote_key(*, raid_id: int, kind: str, option_label: str, user_id: int) -> Tuple[int, str, str, int]:
        return (int(raid_id), str(kind), str(option_label), int(user_id))

    def _rebuild_vote_index(self) -> None:
        self._vote_id_by_key.clear()
        for vote_id, row in self.raid_votes.items():
            self._vote_id_by_key[self._vote_key(
                raid_id=row.raid_id,
                kind=row.kind,
                option_label=row.option_label,
                user_id=row.user_id,
            )] = vote_id

    @staticmethod
    def _normalized_raid_id(raid_id: int | None) -> int | None:
        if raid_id is None:
            return None
        return int(raid_id)

    def _debug_cache_index_add(self, row: DebugMirrorCacheRecord) -> None:
        kind_key = row.kind
        guild_id = int(row.guild_id)
        raid_id = self._normalized_raid_id(row.raid_id)
        self._debug_cache_keys_by_kind.setdefault(kind_key, set()).add(row.cache_key)
        self._debug_cache_keys_by_kind_guild.setdefault((kind_key, guild_id), set()).add(row.cache_key)
        self._debug_cache_keys_by_kind_guild_raid.setdefault((kind_key, guild_id, raid_id), set()).add(row.cache_key)

    def _debug_cache_index_remove(self, row: DebugMirrorCacheRecord) -> None:
        kind_key = row.kind
        guild_id = int(row.guild_id)
        raid_id = self._normalized_raid_id(row.raid_id)
        keys_kind = self._debug_cache_keys_by_kind.get(kind_key)
        if keys_kind is not None:
            keys_kind.discard(row.cache_key)
            if not keys_kind:
                self._debug_cache_keys_by_kind.pop(kind_key, None)

        keys_kind_guild = self._debug_cache_keys_by_kind_guild.get((kind_key, guild_id))
        if keys_kind_guild is not None:
            keys_kind_guild.discard(row.cache_key)
            if not keys_kind_guild:
                self._debug_cache_keys_by_kind_guild.pop((kind_key, guild_id), None)

        keys_kind_guild_raid = self._debug_cache_keys_by_kind_guild_raid.get((kind_key, guild_id, raid_id))
        if keys_kind_guild_raid is not None:
            keys_kind_guild_raid.discard(row.cache_key)
            if not keys_kind_guild_raid:
                self._debug_cache_keys_by_kind_guild_raid.pop((kind_key, guild_id, raid_id), None)

    def _rebuild_debug_cache_indices(self) -> None:
        self._debug_cache_keys_by_kind.clear()
        self._debug_cache_keys_by_kind_guild.clear()
        self._debug_cache_keys_by_kind_guild_raid.clear()
        for row in self.debug_cache.values():
            self._debug_cache_index_add(row)

    def add_dungeon(self, *, name: str, short_code: str, is_active: bool = True, sort_order: int = 0) -> DungeonRecord:
        dungeon_id = len(self.dungeons) + 1
        row = DungeonRecord(id=dungeon_id, name=name, short_code=short_code, is_active=is_active, sort_order=sort_order)
        self.dungeons[dungeon_id] = row
        return row

    def list_active_dungeons(self) -> List[DungeonRecord]:
        rows = [row for row in self.dungeons.values() if row.is_active]
        rows.sort(key=lambda row: (row.sort_order, row.name.lower()))
        return rows

    def get_active_dungeon_by_name(self, dungeon_name: str) -> DungeonRecord | None:
        name = dungeon_name.strip().lower()
        for row in self.dungeons.values():
            if row.is_active and row.name.lower() == name:
                return row
        return None

    def ensure_settings(self, guild_id: int, guild_name: str | None = None) -> GuildSettingsRecord:
        row = self.settings.get(guild_id)
        if row is None:
            row = GuildSettingsRecord(guild_id=guild_id, guild_name=guild_name)
            self.settings[guild_id] = row
            return row
        if guild_name and row.guild_name != guild_name:
            row.guild_name = guild_name
        return row

    def configure_channels(
        self,
        guild_id: int,
        *,
        planner_channel_id: int | None,
        participants_channel_id: int | None,
        raidlist_channel_id: int | None,
    ) -> GuildSettingsRecord:
        row = self.ensure_settings(guild_id)
        row.planner_channel_id = planner_channel_id
        row.participants_channel_id = participants_channel_id
        if row.raidlist_channel_id != raidlist_channel_id:
            row.raidlist_channel_id = raidlist_channel_id
            row.raidlist_message_id = None
        return row

    def set_templates_enabled(self, guild_id: int, guild_name: str | None, enabled: bool) -> GuildSettingsRecord:
        row = self.ensure_settings(guild_id, guild_name)
        row.templates_enabled = enabled
        return row

    def create_raid(
        self,
        *,
        guild_id: int,
        planner_channel_id: int,
        creator_id: int,
        dungeon: str,
        min_players: int,
    ) -> RaidRecord:
        next_display = self._display_id_by_guild.get(guild_id, 0) + 1
        self._display_id_by_guild[guild_id] = next_display
        row = RaidRecord(
            id=self._raid_id,
            display_id=next_display,
            guild_id=guild_id,
            channel_id=planner_channel_id,
            creator_id=creator_id,
            dungeon=dungeon,
            min_players=min_players,
        )
        self.raids[row.id] = row
        self._raid_id += 1
        return row

    def set_raid_message_id(self, raid_id: int, message_id: int) -> None:
        raid = self.raids[raid_id]
        raid.message_id = message_id

    def get_raid(self, raid_id: int) -> RaidRecord | None:
        return self.raids.get(raid_id)

    def list_open_raids(self, guild_id: int | None = None) -> List[RaidRecord]:
        rows = [raid for raid in self.raids.values() if raid.status == "open"]
        if guild_id is not None:
            rows = [raid for raid in rows if raid.guild_id == guild_id]
        rows.sort(key=lambda raid: raid.created_at)
        return rows

    def add_raid_options(self, raid_id: int, *, days: Iterable[str], times: Iterable[str]) -> None:
        for day in days:
            self.raid_options[self._option_id] = RaidOptionRecord(id=self._option_id, raid_id=raid_id, kind="day", label=day)
            self._option_id += 1
        for time_label in times:
            self.raid_options[self._option_id] = RaidOptionRecord(id=self._option_id, raid_id=raid_id, kind="time", label=time_label)
            self._option_id += 1

    def list_raid_options(self, raid_id: int) -> tuple[List[str], List[str]]:
        days = [row.label for row in self.raid_options.values() if row.raid_id == raid_id and row.kind == "day"]
        times = [row.label for row in self.raid_options.values() if row.raid_id == raid_id and row.kind == "time"]
        return days, times

    def toggle_vote(self, *, raid_id: int, kind: str, option_label: str, user_id: int) -> None:
        vote_key = self._vote_key(raid_id=raid_id, kind=kind, option_label=option_label, user_id=user_id)
        existing_id = self._vote_id_by_key.get(vote_key)
        if existing_id is not None:
            self.raid_votes.pop(existing_id, None)
            self._vote_id_by_key.pop(vote_key, None)
            return
        self.raid_votes[self._vote_id] = RaidVoteRecord(
            id=self._vote_id,
            raid_id=raid_id,
            kind=kind,
            option_label=option_label,
            user_id=user_id,
        )
        self._vote_id_by_key[vote_key] = self._vote_id
        self._vote_id += 1

    def vote_counts(self, raid_id: int) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {"day": {}, "time": {}}
        for row in self.raid_votes.values():
            if row.raid_id != raid_id:
                continue
            bucket = counts[row.kind]
            bucket[row.option_label] = bucket.get(row.option_label, 0) + 1
        return counts

    def vote_user_sets(self, raid_id: int) -> tuple[dict[str, set[int]], dict[str, set[int]]]:
        day_users: dict[str, set[int]] = {}
        time_users: dict[str, set[int]] = {}
        for row in self.raid_votes.values():
            if row.raid_id != raid_id:
                continue
            target = day_users if row.kind == "day" else time_users
            users = target.setdefault(row.option_label, set())
            users.add(row.user_id)
        return day_users, time_users

    def list_posted_slots(self, raid_id: int) -> Dict[Tuple[str, str], RaidPostedSlotRecord]:
        out: Dict[Tuple[str, str], RaidPostedSlotRecord] = {}
        for row in self.raid_posted_slots.values():
            if row.raid_id == raid_id:
                out[(row.day_label, row.time_label)] = row
        return out

    def upsert_posted_slot(
        self,
        *,
        raid_id: int,
        day_label: str,
        time_label: str,
        channel_id: int,
        message_id: int,
    ) -> RaidPostedSlotRecord:
        for row in self.raid_posted_slots.values():
            if row.raid_id == raid_id and row.day_label == day_label and row.time_label == time_label:
                row.channel_id = channel_id
                row.message_id = message_id
                return row

        row = RaidPostedSlotRecord(
            id=self._slot_id,
            raid_id=raid_id,
            day_label=day_label,
            time_label=time_label,
            channel_id=channel_id,
            message_id=message_id,
        )
        self.raid_posted_slots[row.id] = row
        self._slot_id += 1
        return row

    def delete_posted_slot(self, slot_id: int) -> None:
        self.raid_posted_slots.pop(slot_id, None)

    def upsert_template(self, *, guild_id: int, dungeon_id: int, template_name: str, template_data: str) -> RaidTemplateRecord:
        for row in self.raid_templates.values():
            if row.guild_id == guild_id and row.dungeon_id == dungeon_id and row.template_name == template_name:
                row.template_data = template_data
                return row
        row = RaidTemplateRecord(
            id=self._template_id,
            guild_id=guild_id,
            dungeon_id=dungeon_id,
            template_name=template_name,
            template_data=template_data,
        )
        self.raid_templates[row.id] = row
        self._template_id += 1
        return row

    def get_template(self, *, guild_id: int, dungeon_id: int, template_name: str) -> RaidTemplateRecord | None:
        for row in self.raid_templates.values():
            if row.guild_id == guild_id and row.dungeon_id == dungeon_id and row.template_name == template_name:
                return row
        return None

    def create_attendance_snapshot(
        self,
        *,
        guild_id: int,
        raid_display_id: int,
        dungeon: str,
        user_ids: set[int],
    ) -> int:
        existing = {
            row.user_id
            for row in self.raid_attendance.values()
            if row.guild_id == guild_id and row.raid_display_id == raid_display_id
        }
        new_ids = sorted(set(user_ids) - existing)
        for user_id in new_ids:
            row = RaidAttendanceRecord(
                id=self._attendance_id,
                guild_id=guild_id,
                raid_display_id=raid_display_id,
                dungeon=dungeon,
                user_id=user_id,
                status="present",
            )
            self.raid_attendance[self._attendance_id] = row
            self._attendance_id += 1
        return len(new_ids)

    def list_attendance(self, *, guild_id: int, raid_display_id: int) -> List[RaidAttendanceRecord]:
        rows = [
            row
            for row in self.raid_attendance.values()
            if row.guild_id == guild_id and row.raid_display_id == raid_display_id
        ]
        rows.sort(key=lambda row: (row.status, row.user_id))
        return rows

    def raid_participation_count(self, *, guild_id: int, user_id: int) -> int:
        return sum(
            1
            for row in self.raid_attendance.values()
            if row.guild_id == guild_id and row.user_id == user_id and row.status == "present"
        )

    def mark_attendance(
        self,
        *,
        guild_id: int,
        raid_display_id: int,
        user_id: int,
        status: str,
        marked_by_user_id: int,
    ) -> bool:
        for row in self.raid_attendance.values():
            if row.guild_id == guild_id and row.raid_display_id == raid_display_id and row.user_id == user_id:
                row.status = status
                row.marked_by_user_id = marked_by_user_id
                return True
        return False

    def _delete_raids_cascade(self, raid_ids: set[int]) -> None:
        if not raid_ids:
            return

        for raid_id in raid_ids:
            self.raids.pop(raid_id, None)

        if self.raid_options:
            self.raid_options = {k: v for k, v in self.raid_options.items() if v.raid_id not in raid_ids}

        if self.raid_votes:
            for vote_id, row in list(self.raid_votes.items()):
                if row.raid_id not in raid_ids:
                    continue
                self.raid_votes.pop(vote_id, None)
                vote_key = self._vote_key(
                    raid_id=row.raid_id,
                    kind=row.kind,
                    option_label=row.option_label,
                    user_id=row.user_id,
                )
                self._vote_id_by_key.pop(vote_key, None)

        if self.raid_posted_slots:
            self.raid_posted_slots = {k: v for k, v in self.raid_posted_slots.items() if v.raid_id not in raid_ids}

    def delete_raid_cascade(self, raid_id: int) -> None:
        self._delete_raids_cascade({int(raid_id)})

    def cancel_open_raids_for_guild(self, guild_id: int) -> int:
        raid_ids = [raid.id for raid in self.list_open_raids(guild_id)]
        self._delete_raids_cascade(set(raid_ids))
        return len(raid_ids)

    def list_open_raid_ids_by_guild(self, guild_id: int) -> List[int]:
        return [raid.id for raid in self.list_open_raids(guild_id)]

    def purge_guild_data(self, guild_id: int) -> dict[str, int]:
        raids_before = len([row for row in self.raids.values() if row.guild_id == guild_id])
        levels_before = len([row for row in self.user_levels.values() if row.guild_id == guild_id])
        settings_before = 1 if guild_id in self.settings else 0

        raid_ids = {row.id for row in self.raids.values() if row.guild_id == guild_id}
        self._delete_raids_cascade(raid_ids)

        self.user_levels = {key: row for key, row in self.user_levels.items() if row.guild_id != guild_id}
        self.settings.pop(guild_id, None)

        return {
            "raids": raids_before,
            "user_levels": levels_before,
            "guild_settings": settings_before,
        }

    def resolve_remote_target(self, raw_value: str) -> tuple[int | None, str | None]:
        value = (raw_value or "").strip()
        if not value:
            return None, "missing"
        if value.isdigit():
            return int(value), None

        exact = [row.guild_id for row in self.settings.values() if (row.guild_name or "").lower() == value.lower()]
        if len(exact) == 1:
            return exact[0], None
        if len(exact) > 1:
            return None, "ambiguous"

        partial = [
            row.guild_id
            for row in self.settings.values()
            if value.lower() in (row.guild_name or "").lower()
        ]
        if len(partial) == 1:
            return partial[0], None
        if len(partial) > 1:
            return None, "ambiguous"
        return None, "not_found"

    def upsert_debug_cache(
        self,
        *,
        cache_key: str,
        kind: str,
        guild_id: int,
        raid_id: int | None,
        message_id: int,
        payload_hash: str,
    ) -> DebugMirrorCacheRecord:
        row = self.debug_cache.get(cache_key)
        if row is None:
            row = DebugMirrorCacheRecord(
                cache_key=cache_key,
                kind=kind,
                guild_id=guild_id,
                raid_id=raid_id,
                message_id=message_id,
                payload_hash=payload_hash,
            )
            self.debug_cache[cache_key] = row
            self._debug_cache_index_add(row)
            return row
        if row.kind != kind or int(row.guild_id) != int(guild_id) or self._normalized_raid_id(row.raid_id) != self._normalized_raid_id(raid_id):
            self._debug_cache_index_remove(row)
            row.kind = kind
            row.guild_id = int(guild_id)
            row.raid_id = self._normalized_raid_id(raid_id)
            self._debug_cache_index_add(row)
        row.message_id = message_id
        row.payload_hash = payload_hash
        return row

    def get_debug_cache(self, cache_key: str) -> DebugMirrorCacheRecord | None:
        return self.debug_cache.get(cache_key)

    def list_debug_cache(
        self,
        *,
        kind: str | None = None,
        guild_id: int | None = None,
        raid_id: int | None = None,
    ) -> List[DebugMirrorCacheRecord]:
        def _rows_from_keys(keys: set[str]) -> List[DebugMirrorCacheRecord]:
            # Keep deterministic order for stable debug output and tests.
            return [self.debug_cache[key] for key in sorted(keys) if key in self.debug_cache]

        if kind is not None and guild_id is not None:
            normalized_guild = int(guild_id)
            if raid_id is not None:
                normalized_raid = int(raid_id)
                keys = self._debug_cache_keys_by_kind_guild_raid.get((kind, normalized_guild, normalized_raid), set())
                return _rows_from_keys(keys)
            keys = self._debug_cache_keys_by_kind_guild.get((kind, normalized_guild), set())
            return _rows_from_keys(keys)

        if kind is not None and guild_id is None and raid_id is None:
            keys = self._debug_cache_keys_by_kind.get(kind, set())
            return _rows_from_keys(keys)

        rows = list(self.debug_cache.values())
        if kind is not None:
            rows = [row for row in rows if row.kind == kind]
        if guild_id is not None:
            rows = [row for row in rows if int(row.guild_id) == int(guild_id)]
        if raid_id is not None:
            rows = [row for row in rows if row.raid_id is not None and int(row.raid_id) == int(raid_id)]
        return rows

    def delete_debug_cache(self, cache_key: str) -> None:
        row = self.debug_cache.pop(cache_key, None)
        if row is not None:
            self._debug_cache_index_remove(row)

    def get_or_create_user_level(self, guild_id: int, user_id: int, username: str | None) -> UserLevelRecord:
        key = (guild_id, user_id)
        row = self.user_levels.get(key)
        if row is None:
            row = UserLevelRecord(guild_id=guild_id, user_id=user_id, username=username)
            self.user_levels[key] = row
        return row
