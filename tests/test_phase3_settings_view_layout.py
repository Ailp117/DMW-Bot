from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace

import pytest

from utils.runtime_helpers import GuildFeatureSettings
from views.raid_views import SettingsView


def _feature_settings() -> GuildFeatureSettings:
    return GuildFeatureSettings(
        leveling_enabled=True,
        levelup_messages_enabled=True,
        nanomon_reply_enabled=True,
        approved_reply_enabled=True,
        raid_reminder_enabled=False,
        message_xp_interval_seconds=15,
        levelup_message_cooldown_seconds=20,
    )


@pytest.mark.asyncio
async def test_settings_view_layout_respects_discord_row_width_limit(repo):
    repo.ensure_settings(1, "Guild")
    bot = SimpleNamespace(
        repo=repo,
        _get_guild_feature_settings=lambda _guild_id: _feature_settings(),
        _get_raid_calendar_channel_id=lambda _guild_id: None,
    )

    view = SettingsView(bot, guild_id=1)

    row_totals: dict[int, int] = defaultdict(int)
    for item in view.children:
        row = int(item.row or 0)
        row_totals[row] += int(getattr(item, "width", 1))

    assert row_totals
    assert all(total <= 5 for total in row_totals.values())
    assert any(getattr(item, "custom_id", "") == "settings:1:calendar_modal" for item in view.children)
