from __future__ import annotations

from services.raid_service import build_raid_plan_defaults, create_raid_from_modal
from services.settings_service import set_templates_enabled


def test_template_toggle_and_auto_template_upsert(repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    repo.ensure_settings(1, "Guild")

    set_templates_enabled(repo, 1, "Guild", True)

    create_raid_from_modal(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        creator_id=100,
        dungeon_name="Nanos",
        days_input="Mon, Tue",
        times_input="20:00",
        min_players_input="3",
        message_id=5700,
    )

    defaults = build_raid_plan_defaults(
        repo,
        guild_id=1,
        guild_name="Guild",
        dungeon_name="Nanos",
    )

    assert defaults.days == ["Mon", "Tue"]
    assert defaults.times == ["20:00"]
    assert defaults.min_players == 3
