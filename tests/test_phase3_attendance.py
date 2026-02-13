from __future__ import annotations

from services.attendance_service import mark_attendance


def test_mark_updates_status_and_marker(repo):
    created = repo.create_attendance_snapshot(
        guild_id=1,
        raid_display_id=7,
        dungeon="Nanos",
        user_ids={100, 101},
    )
    assert created == 2

    ok = mark_attendance(
        repo,
        guild_id=1,
        raid_display_id=7,
        user_id=100,
        status="present",
        marked_by_user_id=999,
    )
    assert ok is True

    rows = repo.list_attendance(guild_id=1, raid_display_id=7)
    target = [row for row in rows if row.user_id == 100][0]
    assert target.status == "present"
    assert target.marked_by_user_id == 999
