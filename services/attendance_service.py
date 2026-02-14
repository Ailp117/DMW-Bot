from __future__ import annotations

from db.repository import InMemoryRepository, RaidAttendanceRecord


STATUS_LABELS = {
    "present": "present",
    "absent": "absent",
    "pending": "pending",
}


def list_attendance(repo: InMemoryRepository, *, guild_id: int, raid_display_id: int) -> list[RaidAttendanceRecord]:
    return repo.list_attendance(guild_id=guild_id, raid_display_id=raid_display_id)


def mark_attendance(
    repo: InMemoryRepository,
    *,
    guild_id: int,
    raid_display_id: int,
    user_id: int,
    status: str,
    marked_by_user_id: int,
) -> bool:
    if status not in STATUS_LABELS:
        raise ValueError(f"Unsupported attendance status: {status}")
    return repo.mark_attendance(
        guild_id=guild_id,
        raid_display_id=raid_display_id,
        user_id=user_id,
        status=status,
        marked_by_user_id=marked_by_user_id,
    )
