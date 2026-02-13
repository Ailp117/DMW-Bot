from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from db.repository import InMemoryRepository, RaidRecord
from services.template_service import get_auto_template_defaults, upsert_auto_template
from utils.slots import compute_qualified_slot_users, memberlist_target_label, memberlist_threshold
from utils.text import normalize_list, short_list


@dataclass(slots=True)
class RaidPlanDefaults:
    dungeon_id: int
    days: list[str]
    times: list[str]
    min_players: int


@dataclass(slots=True)
class RaidCreateResult:
    raid: RaidRecord
    days: list[str]
    times: list[str]


@dataclass(slots=True)
class MemberlistSlotState:
    day: str
    time: str
    users: list[int]


@dataclass(slots=True)
class MemberlistSyncResult:
    created: int
    updated: int
    deleted: int
    active_slots: list[MemberlistSlotState]


@dataclass(slots=True)
class FinishRaidResult:
    success: bool
    reason: str | None
    attendance_rows: int


@dataclass(slots=True)
class PersistentViewState:
    raid_id: int
    message_id: int
    days: list[str]
    times: list[str]


@dataclass(slots=True)
class StaleCleanupResult:
    cleaned_count: int
    affected_guild_ids: list[int]


def build_raid_plan_defaults(
    repo: InMemoryRepository,
    *,
    guild_id: int,
    guild_name: str,
    dungeon_name: str,
) -> RaidPlanDefaults:
    dungeon = repo.get_active_dungeon_by_name(dungeon_name)
    if dungeon is None:
        raise ValueError("Dungeon not found or inactive")

    settings = repo.ensure_settings(guild_id, guild_name)
    if not settings.planner_channel_id or not settings.participants_channel_id:
        raise ValueError("Planner and participants channels must be configured")

    days, times, min_players = get_auto_template_defaults(
        repo,
        guild_id=guild_id,
        dungeon_id=dungeon.id,
        templates_enabled=settings.templates_enabled,
        default_min_players=settings.default_min_players,
    )
    return RaidPlanDefaults(dungeon_id=dungeon.id, days=days, times=times, min_players=min_players)


def create_raid_from_modal(
    repo: InMemoryRepository,
    *,
    guild_id: int,
    guild_name: str,
    planner_channel_id: int,
    creator_id: int,
    dungeon_name: str,
    days_input: str,
    times_input: str,
    min_players_input: str,
    message_id: int,
) -> RaidCreateResult:
    try:
        min_players = int(min_players_input.strip())
    except ValueError as exc:
        raise ValueError("Min players must be a number >= 0") from exc
    if min_players < 0:
        raise ValueError("Min players must be a number >= 0")

    days = normalize_list(days_input)
    times = normalize_list(times_input)
    if not days or not times:
        raise ValueError("At least one day and one time are required")

    settings = repo.ensure_settings(guild_id, guild_name)
    if not settings.planner_channel_id or not settings.participants_channel_id:
        raise ValueError("Planner and participants channels must be configured")

    raid = repo.create_raid(
        guild_id=guild_id,
        planner_channel_id=planner_channel_id,
        creator_id=creator_id,
        dungeon=dungeon_name,
        min_players=min_players,
    )
    repo.add_raid_options(raid.id, days=days, times=times)
    repo.set_raid_message_id(raid.id, message_id)

    if settings.templates_enabled:
        dungeon = repo.get_active_dungeon_by_name(dungeon_name)
        if dungeon is not None:
            upsert_auto_template(
                repo,
                guild_id=guild_id,
                dungeon_id=dungeon.id,
                days=days,
                times=times,
                min_players=min_players,
            )

    return RaidCreateResult(raid=raid, days=days, times=times)


def toggle_vote(repo: InMemoryRepository, *, raid_id: int, kind: str, option_label: str, user_id: int) -> None:
    if kind not in {"day", "time"}:
        raise ValueError("Unsupported vote kind")
    repo.toggle_vote(raid_id=raid_id, kind=kind, option_label=option_label, user_id=user_id)


def planner_counts(repo: InMemoryRepository, raid_id: int) -> dict[str, dict[str, int]]:
    return repo.vote_counts(raid_id)


def slot_text(raid: RaidRecord, day: str, time_label: str, users: list[int]) -> str:
    mentions = [f"<@{user_id}>" for user_id in users]
    return (
        f"✅ **Teilnehmerliste — {raid.dungeon}**\n"
        f"🆔 Raid: `{raid.display_id}`\n"
        f"📅 Tag: **{day}**\n"
        f"🕒 Zeit: **{time_label}**\n"
        f"👥 Teilnehmer: **{len(users)} / {memberlist_target_label(raid.min_players)}**\n"
        f"{short_list(mentions)}"
    )


def sync_memberlist_slots(
    repo: InMemoryRepository,
    *,
    raid_id: int,
    participants_channel_id: int,
) -> MemberlistSyncResult:
    raid = repo.get_raid(raid_id)
    if raid is None or raid.status != "open":
        return MemberlistSyncResult(created=0, updated=0, deleted=0, active_slots=[])

    days, times = repo.list_raid_options(raid_id)
    day_users, time_users = repo.vote_user_sets(raid_id)
    threshold = memberlist_threshold(raid.min_players)
    qualified_slots, _ = compute_qualified_slot_users(
        days=days,
        times=times,
        day_users=day_users,
        time_users=time_users,
        threshold=threshold,
    )

    existing = repo.list_posted_slots(raid_id)
    active_keys = set()
    created = 0
    updated = 0
    deleted = 0
    active_slots: list[MemberlistSlotState] = []

    for (day, time_label), users in qualified_slots.items():
        active_keys.add((day, time_label))
        active_slots.append(MemberlistSlotState(day=day, time=time_label, users=users))
        row = existing.get((day, time_label))
        if row is None:
            generated_message_id = (raid_id * 100000) + len(active_slots)
            repo.upsert_posted_slot(
                raid_id=raid_id,
                day_label=day,
                time_label=time_label,
                channel_id=participants_channel_id,
                message_id=generated_message_id,
            )
            created += 1
            continue

        repo.upsert_posted_slot(
            raid_id=raid_id,
            day_label=day,
            time_label=time_label,
            channel_id=participants_channel_id,
            message_id=row.message_id,
        )
        updated += 1

    for key, row in list(existing.items()):
        if key in active_keys:
            continue
        repo.delete_posted_slot(row.id)
        deleted += 1

    return MemberlistSyncResult(created=created, updated=updated, deleted=deleted, active_slots=active_slots)


def finish_raid(repo: InMemoryRepository, *, raid_id: int, actor_user_id: int) -> FinishRaidResult:
    raid = repo.get_raid(raid_id)
    if raid is None:
        return FinishRaidResult(success=False, reason="raid_not_found", attendance_rows=0)
    if actor_user_id != raid.creator_id:
        return FinishRaidResult(success=False, reason="only_creator", attendance_rows=0)

    days, times = repo.list_raid_options(raid_id)
    day_users, time_users = repo.vote_user_sets(raid_id)
    threshold = memberlist_threshold(raid.min_players)
    _, users = compute_qualified_slot_users(
        days=days,
        times=times,
        day_users=day_users,
        time_users=time_users,
        threshold=threshold,
    )

    attendance_rows = repo.create_attendance_snapshot(
        guild_id=raid.guild_id,
        raid_display_id=raid.display_id,
        dungeon=raid.dungeon,
        user_ids=users,
    )
    repo.delete_raid_cascade(raid_id)
    return FinishRaidResult(success=True, reason=None, attendance_rows=attendance_rows)


def restore_persistent_views(repo: InMemoryRepository) -> list[PersistentViewState]:
    restored: list[PersistentViewState] = []
    for raid in repo.list_open_raids():
        if raid.message_id is None:
            continue
        days, times = repo.list_raid_options(raid.id)
        if not days or not times:
            continue
        restored.append(PersistentViewState(raid_id=raid.id, message_id=raid.message_id, days=days, times=times))
    return restored


def restore_memberlists(repo: InMemoryRepository) -> dict[int, MemberlistSyncResult]:
    out: dict[int, MemberlistSyncResult] = {}
    for raid in repo.list_open_raids():
        settings = repo.ensure_settings(raid.guild_id)
        if not settings.participants_channel_id:
            continue
        out[raid.id] = sync_memberlist_slots(
            repo,
            raid_id=raid.id,
            participants_channel_id=settings.participants_channel_id,
        )
    return out


def cleanup_stale_raids(repo: InMemoryRepository, *, now: datetime, stale_hours: int) -> StaleCleanupResult:
    cutoff = now - timedelta(hours=stale_hours)
    affected: set[int] = set()
    cleaned = 0

    for raid in list(repo.list_open_raids()):
        if raid.created_at > cutoff:
            continue
        repo.delete_raid_cascade(raid.id)
        cleaned += 1
        affected.add(raid.guild_id)

    return StaleCleanupResult(cleaned_count=cleaned, affected_guild_ids=sorted(affected))
