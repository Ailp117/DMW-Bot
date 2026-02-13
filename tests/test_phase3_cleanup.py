from __future__ import annotations

from services.raid_service import create_raid_from_modal, finish_raid, toggle_vote


def _raid(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    return create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="Mon",
        times_input="20:00",
        min_players_input="1",
        message_id=5300,
    ).raid.id


def test_finish_requires_creator(repo):
    raid_id = _raid(repo)
    result = finish_raid(repo, raid_id=raid_id, actor_user_id=999)

    assert result.success is False
    assert result.reason == "only_creator"
    assert repo.get_raid(raid_id) is not None


def test_finish_deletes_raid_and_keeps_attendance_snapshot(repo):
    raid_id = _raid(repo)
    raid = repo.get_raid(raid_id)

    toggle_vote(repo, raid_id=raid_id, kind="day", option_label="Mon", user_id=200)
    toggle_vote(repo, raid_id=raid_id, kind="time", option_label="20:00", user_id=200)

    result = finish_raid(repo, raid_id=raid_id, actor_user_id=100)

    assert result.success is True
    assert result.attendance_rows == 1
    assert repo.get_raid(raid_id) is None

    rows = repo.list_attendance(guild_id=raid.guild_id, raid_display_id=raid.display_id)
    assert len(rows) == 1
    assert rows[0].user_id == 200
