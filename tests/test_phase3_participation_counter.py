from __future__ import annotations

from services.raid_service import create_raid_from_modal, finish_raid, toggle_vote


def _create_open_raid(repo, *, creator_id: int, message_id: int) -> int:
    raid = create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=creator_id,
        dungeon_name="Nanos",
        days_input="Mon, Tue",
        times_input="20:00, 21:00",
        min_players_input="1",
        message_id=message_id,
    ).raid
    return raid.id


def test_participation_counter_starts_at_zero_and_increments_per_finished_raid(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )

    assert repo.raid_participation_count(guild_id=1, user_id=200) == 0
    assert repo.raid_participation_count(guild_id=1, user_id=201) == 0

    raid_id_1 = _create_open_raid(repo, creator_id=100, message_id=7001)
    toggle_vote(repo, raid_id=raid_id_1, kind="day", option_label="Mon", user_id=200)
    toggle_vote(repo, raid_id=raid_id_1, kind="day", option_label="Tue", user_id=200)
    toggle_vote(repo, raid_id=raid_id_1, kind="time", option_label="20:00", user_id=200)
    toggle_vote(repo, raid_id=raid_id_1, kind="time", option_label="21:00", user_id=200)

    first_finish = finish_raid(repo, raid_id=raid_id_1, actor_user_id=100)
    assert first_finish.success is True

    assert repo.raid_participation_count(guild_id=1, user_id=200) == 1
    assert repo.raid_participation_count(guild_id=1, user_id=201) == 0

    raid_id_2 = _create_open_raid(repo, creator_id=101, message_id=7002)
    toggle_vote(repo, raid_id=raid_id_2, kind="day", option_label="Mon", user_id=200)
    toggle_vote(repo, raid_id=raid_id_2, kind="time", option_label="20:00", user_id=200)

    second_finish = finish_raid(repo, raid_id=raid_id_2, actor_user_id=101)
    assert second_finish.success is True

    assert repo.raid_participation_count(guild_id=1, user_id=200) == 2
    assert repo.raid_participation_count(guild_id=1, user_id=201) == 0
