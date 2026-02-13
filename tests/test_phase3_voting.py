from __future__ import annotations

from services.raid_service import create_raid_from_modal, planner_counts, toggle_vote


def _raid(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    result = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="Mon",
        times_input="20:00",
        min_players_input="1",
        message_id=5100,
    )
    return result.raid.id


def test_toggle_vote_insert_then_remove(repo):
    raid_id = _raid(repo)

    toggle_vote(repo, raid_id=raid_id, kind="day", option_label="Mon", user_id=200)
    assert len(repo.raid_votes) == 1

    toggle_vote(repo, raid_id=raid_id, kind="day", option_label="Mon", user_id=200)
    assert len(repo.raid_votes) == 0


def test_vote_counts_reflect_rows(repo):
    raid_id = _raid(repo)

    toggle_vote(repo, raid_id=raid_id, kind="day", option_label="Mon", user_id=200)
    toggle_vote(repo, raid_id=raid_id, kind="time", option_label="20:00", user_id=200)
    toggle_vote(repo, raid_id=raid_id, kind="time", option_label="20:00", user_id=201)

    counts = planner_counts(repo, raid_id)
    assert counts["day"]["Mon"] == 1
    assert counts["time"]["20:00"] == 2
