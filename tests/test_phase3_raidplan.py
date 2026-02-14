from __future__ import annotations

from datetime import date

import pytest

from services.raid_service import build_raid_plan_defaults
from utils.runtime_helpers import _upcoming_raid_date_labels


def test_raidplan_validates_inputs_and_uses_template_defaults(repo):
    repo.ensure_settings(1, "Guild")
    with pytest.raises(ValueError, match="Planner and participants"):
        build_raid_plan_defaults(repo, guild_id=1, guild_name="Guild", dungeon_name="Nanos")

    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )
    row = repo.upsert_template(
        guild_id=1,
        dungeon_id=1,
        template_name="_auto_dungeon_default",
        template_data='{"days": ["14.02.2026"], "times": ["20:00"], "min_players": 4}',
    )
    assert row is not None

    defaults = build_raid_plan_defaults(repo, guild_id=1, guild_name="Guild", dungeon_name="Nanos")
    assert defaults.days == ["14.02.2026"]
    assert defaults.times == ["20:00"]
    assert defaults.min_players == 4


def test_dungeon_autocomplete_filters_active_rows(repo):
    names = [row.name for row in repo.list_active_dungeons() if "na" in row.name.lower()]
    assert names == ["Nanos"]


def test_upcoming_raid_date_labels_use_dd_mm_yyyy_format():
    labels = _upcoming_raid_date_labels(start_date=date(2026, 2, 14), count=3)
    assert labels == ["14.02.2026", "15.02.2026", "16.02.2026"]
