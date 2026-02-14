from __future__ import annotations

from services.settings_service import save_channel_settings


def test_settings_save_persists_and_resets_raidlist_message_id(repo):
    row = repo.ensure_settings(1, "Guild")
    row.raidlist_channel_id = 33
    row.raidlist_message_id = 999

    updated = save_channel_settings(
        repo,
        guild_id=1,
        guild_name="Guild",
        planner_channel_id=11,
        participants_channel_id=22,
        raidlist_channel_id=44,
    )

    assert updated.planner_channel_id == 11
    assert updated.participants_channel_id == 22
    assert updated.raidlist_channel_id == 44
    assert updated.raidlist_message_id is None
