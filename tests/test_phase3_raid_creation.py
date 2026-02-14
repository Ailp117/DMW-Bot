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
        days_input="14.02.2026, 15.02.2026",
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
        days_input="16.02.2026",
        times_input="22:00",
        min_players_input="2",
        message_id=5002,
    )

    assert first.raid.display_id == 1
    assert second.raid.display_id == 2
    assert first.raid.message_id == 5001

    days, times = repo.list_raid_options(first.raid.id)
    assert days == ["14.02.2026", "15.02.2026"]
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
            days_input="14.02.2026",
            times_input="20:00",
            min_players_input="-1",
            message_id=5003,
        )


def test_create_raid_normalizes_time_labels_for_db(repo):
    _prepare_settings(repo)

    result = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="14.02.2026",
        times_input="7:05, 19.30, 07:05",
        min_players_input="1",
        message_id=5004,
    )

    _days, times = repo.list_raid_options(result.raid.id)
    assert times == ["07:05", "19:30"]


def test_modal_validation_rejects_bad_time_values(repo):
    _prepare_settings(repo)

    with pytest.raises(ValueError, match="Time values must use HH:MM"):
        create_raid_from_modal(
            repo,
            guild_id=1,
            guild_name="Guild",
            planner_channel_id=11,
            creator_id=100,
            dungeon_name="Nanos",
            days_input="14.02.2026",
            times_input="abends",
            min_players_input="1",
            message_id=5005,
        )


def test_modal_validation_rejects_weekday_day_values(repo):
    _prepare_settings(repo)

    with pytest.raises(ValueError, match="Day values must use TT.MM.JJJJ"):
        create_raid_from_modal(
            repo,
            guild_id=1,
            guild_name="Guild",
            planner_channel_id=11,
            creator_id=100,
            dungeon_name="Nanos",
            days_input="Mo, Di",
            times_input="20:00",
            min_players_input="1",
            message_id=5006,
        )
