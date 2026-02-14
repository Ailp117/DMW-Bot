from __future__ import annotations

import pytest

from services.raid_service import create_raid_from_modal


def _prepare_settings(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )


def test_create_raid_persists_display_id_and_options(repo):
    _prepare_settings(repo)

    first = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="Mon, Tue",
        times_input="20:00, 21:00",
        min_players_input="0",
        message_id=5001,
    )
    second = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=101,
        dungeon_name="Nanos",
        days_input="Wed",
        times_input="22:00",
        min_players_input="2",
        message_id=5002,
    )

    assert first.raid.display_id == 1
    assert second.raid.display_id == 2
    assert first.raid.message_id == 5001

    days, times = repo.list_raid_options(first.raid.id)
    assert days == ["Mon", "Tue"]
    assert times == ["20:00", "21:00"]


def test_modal_validation_rejects_bad_min_players(repo):
    _prepare_settings(repo)

    with pytest.raises(ValueError, match="Min players"):
        create_raid_from_modal(
            repo,
            guild_id=1,
            guild_name="Guild",
            planner_channel_id=11,
            creator_id=100,
            dungeon_name="Nanos",
            days_input="Mon",
            times_input="20:00",
            min_players_input="-1",
            message_id=5003,
        )
