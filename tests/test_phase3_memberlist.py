from __future__ import annotations

from services.raid_service import create_raid_from_modal, sync_memberlist_slots, toggle_vote
from utils.slots import memberlist_threshold


def _create(repo, min_players: str):
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
        days_input="14.02.2026",
        times_input="20:00",
        min_players_input=min_players,
        message_id=5200,
    ).raid.id


def test_min_zero_maps_to_threshold_one():
    assert memberlist_threshold(0) == 1
    assert memberlist_threshold(3) == 3


def test_sync_creates_updates_and_deletes_slot_rows(repo):
    raid_id = _create(repo, "0")

    toggle_vote(repo, raid_id=raid_id, kind="day", option_label="14.02.2026", user_id=200)
    toggle_vote(repo, raid_id=raid_id, kind="time", option_label="20:00", user_id=200)

    first = sync_memberlist_slots(repo, raid_id=raid_id, participants_channel_id=22)
    assert first.created == 1
    assert first.deleted == 0
    assert len(repo.raid_posted_slots) == 1

    second = sync_memberlist_slots(repo, raid_id=raid_id, participants_channel_id=22)
    assert second.created == 0
    assert second.updated == 1

    toggle_vote(repo, raid_id=raid_id, kind="time", option_label="20:00", user_id=200)
    third = sync_memberlist_slots(repo, raid_id=raid_id, participants_channel_id=22)
    assert third.deleted == 1
    assert len(repo.raid_posted_slots) == 0
