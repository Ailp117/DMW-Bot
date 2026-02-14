from __future__ import annotations

import pytest

from services.raid_service import create_raid_from_modal


@pytest.mark.asyncio
async def test_on_guild_remove_purges_data_and_timers(app, repo):
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
        days_input="Mon",
        times_input="20:00",
        min_players_input="1",
        message_id=5800,
    )

    result = await app.on_guild_remove(1)
    assert result["raids"] == 1
    assert repo.list_open_raids(1) == []


def test_log_queue_buffers_before_ready(app):
    app.enqueue_discord_log("one")
    app.enqueue_discord_log("two")

    assert app.pending_log_buffer == ["one", "two"]
    assert app.log_forward_queue.empty()

    app.log_forwarder_active = True
    app.flush_pending_logs()

    queued = []
    while not app.log_forward_queue.empty():
        queued.append(app.log_forward_queue.get_nowait())

    assert queued == ["one", "two"]
    assert app.pending_log_buffer == []
