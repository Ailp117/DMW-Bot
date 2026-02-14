from __future__ import annotations


def test_expected_command_set_registered(app):
    registered = set(app.registered_commands)
    assert registered == app.expected_commands


def test_sync_uses_guild_targets_then_global(app, repo):
    repo.ensure_settings(44, "Guild44")
    synced, global_synced = app.sync_commands_for_known_guilds([11, 22])

    assert synced == [11, 22, 44]
    assert global_synced is True
