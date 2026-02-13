# Feature-Matrix (Current Rewrite Progress)

Diese Matrix dokumentiert die aktuell im Code vorhandenen Kernfeatures und die Zuordnung zu Code + DB + Tests.

| Feature | Hauptdateien | Relevante DB-Tabellen | Tests |
|---|---|---|---|
| Slash Commands (`/raidplan`, `/raidlist`, `/settings`, `/status`, etc.) | `main.py`, `commands_raid.py`, `commands_admin.py`, `commands_templates.py`, `commands_attendance.py`, `commands_backup.py`, `commands_purge.py`, `commands_remote.py` | `raids`, `guild_settings`, `dungeons`, `raid_templates`, `raid_attendance`, `user_levels` | `tests/test_command_sync_resilience.py`, `tests/test_command_coverage_and_db_logging.py` |
| Dungeon-Handling (inkl. aktive Dungeons) | `commands_raid.py`, `main.py` | `dungeons` | `tests/test_command_sync_resilience.py` |
| Persistente Raid Views nach Neustart | `main.py`, `views_raid.py` | `raids`, `raid_votes` | `tests/test_persistent_views_restore.py`, `tests/test_views_raid_regressions.py` |
| Voting/Toggle Logik | `views_raid.py`, `helpers.py` | `raid_votes` | `tests/test_views_raid_regressions.py` |
| Live Embed + Raidlist Refresh | `raidlist.py`, `raidlist_updater.py`, `views_raid.py` | `raids`, `guild_settings` | `tests/test_command_sync_resilience.py` |
| Teilnehmerlisten/Mentions Sync | `views_raid.py`, `main.py` | `raids`, `guild_settings` | `tests/test_memberlist_restore_source.py`, `tests/test_memberlist_min_zero_source.py` |
| Temporäre Rollen + Cleanup | `roles.py`, `helpers.py`, `main.py` | `raids` | `tests/test_views_raid_regressions.py` |
| Backup (auto + manuell) | `backup_sql.py`, `commands_backup.py`, `main.py` | gesamtes DB-Schema | `tests/test_backup_hardening_source.py` |
| Startup Smoke Checks (DB, Tabellen, offene Raids) | `main.py` | `guild_settings`, `raids`, `raid_votes`, `raid_attendance`, `dungeons`, `user_levels`, `raid_templates` | `tests/test_command_sync_resilience.py` |
| Logging/DB SQL Tracing | `main.py`, `db.py` | indirekt alle | `tests/test_db_sql_logging_source.py`, `tests/test_command_coverage_and_db_logging.py` |

## Hinweis

Diese Matrix bildet den **derzeitigen Stand im Repository** ab und ist Grundlage für die weitere 1:1-Absicherung gegen Altverhalten.
