from __future__ import annotations

from services.raid_service import (
    create_raid_from_modal,
    restore_memberlists,
    restore_persistent_views,
    toggle_vote,
)


def test_restore_persistent_views_for_open_raids(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    raid = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="Mon, Tue",
        times_input="20:00, 21:00",
        min_players_input="1",
        message_id=5500,
    ).raid

    restored = restore_persistent_views(repo)
    assert len(restored) == 1
    assert restored[0].raid_id == raid.id
    assert restored[0].message_id == 5500


def test_restore_memberlists_for_open_raids(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    raid_id = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="Mon",
        times_input="20:00",
        min_players_input="1",
        message_id=5501,
    ).raid.id

    toggle_vote(repo, raid_id=raid_id, kind="day", option_label="Mon", user_id=123)
    toggle_vote(repo, raid_id=raid_id, kind="time", option_label="20:00", user_id=123)

    restored = restore_memberlists(repo)
    assert raid_id in restored
    assert restored[raid_id].created == 1
