from __future__ import annotations

from services.raid_service import create_raid_from_modal, toggle_vote


def _create_raid(repo, *, guild_id: int, planner_channel_id: int, participants_channel_id: int, raidlist_channel_id: int, message_id: int):
    repo.configure_channels(
        guild_id,
        planner_channel_id=planner_channel_id,
        participants_channel_id=participants_channel_id,
        raidlist_channel_id=raidlist_channel_id,
    )
    result = create_raid_from_modal(
        repo,
        guild_id=guild_id,
        guild_name=f"Guild-{guild_id}",
        planner_channel_id=planner_channel_id,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="14.02.2026, 15.02.2026",
        times_input="20:00, 21:00",
        min_players_input="1",
        message_id=message_id,
    )
    return result.raid.id


def test_cancel_open_raids_bulk_cascade_keeps_other_guild_data(repo):
    raid_g1_a = _create_raid(
        repo,
        guild_id=1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
        message_id=6101,
    )
    raid_g1_b = _create_raid(
        repo,
        guild_id=1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
        message_id=6102,
    )
    raid_g2 = _create_raid(
        repo,
        guild_id=2,
        planner_channel_id=111,
        participants_channel_id=222,
        raidlist_channel_id=333,
        message_id=6201,
    )

    toggle_vote(repo, raid_id=raid_g1_a, kind="day", option_label="14.02.2026", user_id=200)
    toggle_vote(repo, raid_id=raid_g1_a, kind="time", option_label="20:00", user_id=200)
    toggle_vote(repo, raid_id=raid_g1_b, kind="day", option_label="15.02.2026", user_id=201)
    toggle_vote(repo, raid_id=raid_g1_b, kind="time", option_label="21:00", user_id=201)
    toggle_vote(repo, raid_id=raid_g2, kind="day", option_label="14.02.2026", user_id=300)
    toggle_vote(repo, raid_id=raid_g2, kind="time", option_label="20:00", user_id=300)

    repo.upsert_posted_slot(
        raid_id=raid_g1_a,
        day_label="14.02.2026",
        time_label="20:00",
        channel_id=22,
        message_id=9101,
    )
    repo.upsert_posted_slot(
        raid_id=raid_g2,
        day_label="14.02.2026",
        time_label="20:00",
        channel_id=222,
        message_id=9201,
    )

    removed = repo.cancel_open_raids_for_guild(1)
    assert removed == 2
    assert repo.get_raid(raid_g1_a) is None
    assert repo.get_raid(raid_g1_b) is None
    assert repo.get_raid(raid_g2) is not None

    remaining_raid_ids = set(repo.raids.keys())
    assert remaining_raid_ids == {raid_g2}
    assert all(row.raid_id in remaining_raid_ids for row in repo.raid_options.values())
    assert all(row.raid_id in remaining_raid_ids for row in repo.raid_votes.values())
    assert all(row.raid_id in remaining_raid_ids for row in repo.raid_posted_slots.values())

    # Vote index must remain consistent after bulk cascade.
    toggle_vote(repo, raid_id=raid_g2, kind="day", option_label="14.02.2026", user_id=300)
    assert all(row.user_id != 300 or row.option_label != "14.02.2026" for row in repo.raid_votes.values())
    toggle_vote(repo, raid_id=raid_g2, kind="day", option_label="14.02.2026", user_id=300)
    assert any(row.user_id == 300 and row.option_label == "14.02.2026" for row in repo.raid_votes.values())


def test_purge_guild_data_bulk_cascade_keeps_other_guild_votes_working(repo):
    raid_g1 = _create_raid(
        repo,
        guild_id=1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
        message_id=6301,
    )
    raid_g2 = _create_raid(
        repo,
        guild_id=2,
        planner_channel_id=111,
        participants_channel_id=222,
        raidlist_channel_id=333,
        message_id=6302,
    )

    toggle_vote(repo, raid_id=raid_g1, kind="day", option_label="14.02.2026", user_id=200)
    toggle_vote(repo, raid_id=raid_g1, kind="time", option_label="20:00", user_id=200)
    toggle_vote(repo, raid_id=raid_g2, kind="day", option_label="15.02.2026", user_id=300)
    toggle_vote(repo, raid_id=raid_g2, kind="time", option_label="21:00", user_id=300)

    repo.get_or_create_user_level(1, 5001, "Alpha")
    repo.get_or_create_user_level(2, 5002, "Bravo")

    result = repo.purge_guild_data(1)
    assert result["raids"] == 1
    assert result["guild_settings"] == 1
    assert 1 not in repo.settings
    assert all(row.guild_id != 1 for row in repo.user_levels.values())
    assert repo.get_raid(raid_g1) is None
    assert repo.get_raid(raid_g2) is not None

    toggle_vote(repo, raid_id=raid_g2, kind="day", option_label="15.02.2026", user_id=300)
    assert all(not (row.raid_id == raid_g2 and row.kind == "day" and row.option_label == "15.02.2026" and row.user_id == 300) for row in repo.raid_votes.values())
    toggle_vote(repo, raid_id=raid_g2, kind="day", option_label="15.02.2026", user_id=300)
    assert any(row.raid_id == raid_g2 and row.kind == "day" and row.option_label == "15.02.2026" and row.user_id == 300 for row in repo.raid_votes.values())
