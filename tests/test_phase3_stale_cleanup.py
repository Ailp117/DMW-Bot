from __future__ import annotations

from datetime import datetime

import pytest


@pytest.mark.asyncio
async def test_cleanup_stale_raids_only(app, repo):
    repo.configure_channels(
        1,
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=33,
    )

    old_raid = repo.create_raid(
        guild_id=1,
        planner_channel_id=11,
        creator_id=10,
        dungeon="Nanos",
        min_players=1,
    )
    old_raid.created_at = datetime(2020, 1, 1)

    new_raid = repo.create_raid(
        guild_id=1,
        planner_channel_id=11,
        creator_id=11,
        dungeon="Skull",
        min_players=1,
    )

    cleaned, _ = await app.cleanup_stale_raids_once(now=datetime(2026, 2, 13))
    assert cleaned == 1
    assert repo.get_raid(old_raid.id) is None
    assert repo.get_raid(new_raid.id) is not None
