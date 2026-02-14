from __future__ import annotations

from services.admin_service import cancel_all_open_raids, resolve_remote_target
from services.raid_service import create_raid_from_modal


def test_cancel_all_raids_cleans_open_rows(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="14.02.2026",
        times_input="20:00",
        min_players_input="1",
        message_id=5600,
    )
    create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=101,
        dungeon_name="Skull",
        days_input="15.02.2026",
        times_input="21:00",
        min_players_input="1",
        message_id=5601,
    )

    count = cancel_all_open_raids(repo, guild_id=1)
    assert count == 2
    assert repo.list_open_raids(1) == []


def test_remote_target_resolution_rules(repo):
    repo.ensure_settings(1, "Alpha Guild")
    repo.ensure_settings(2, "Beta Guild")

    assert resolve_remote_target(repo, "1") == (1, None)
    assert resolve_remote_target(repo, "Alpha Guild") == (1, None)
    assert resolve_remote_target(repo, "Beta") == (2, None)

    no_target = resolve_remote_target(repo, "")
    assert no_target[0] is None
    assert "provide" in (no_target[1] or "").lower()
