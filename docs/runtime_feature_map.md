# Runtime Refactor Map

## Schritt 1: Feature-Landkarte (Ist-Zustand)

### Slash-Commands
- `/settings`
- `/status`
- `/help`
- `/help2`
- `/id`
- `/restart`
- `/dungeonlist`
- `/raidplan`
- `/raid_finish`
- `/raidlist`
- `/raidcalendar_rebuild`
- `/cancel_all_raids`
- `/template_config`
- `/purge`
- `/purgebot`
- `/remote_guilds`
- `/remote_cancel_all_raids`
- `/remote_raidlist`
- `/remote_rebuild_memberlists`
- `/backup_db`

### Discord UI (Views/Modals/Buttons)
- `RaidCreateModal`
- `RaidDateSelectionView`
- `RaidVoteView`
- `FinishButton`
- `SettingsView`
- `SettingsToggleButton`
- `SettingsIntervalsModal`
- `SettingsSaveButton`
- `RaidCalendarView`
- `RaidCalendarShiftButton`
- `RaidCalendarTodayButton`

### Kern-Featureblöcke
- Raid-Planung (Erstellung, Optionen, Votes)
- Teilnehmerlisten-Synchronisierung
- Temporäre Rollen + Slot-Rollen
- Raid-Erinnerungen (10 Minuten)
- Raidlist-Rendering/Refresh
- Raid-Kalender-Rendering/Refresh + Monatswechsel
- Persistenz (Delta-Flush + Retry)
- Restore nach Neustart (Views/Messages)
- Levelsystem + Keyword-Replies
- Backup/Self-Test/Integritäts- und Stale-Cleanup-Worker
- Debug/Log-Mirroring

## Schritt 2: Ziel-Mapping (Soll-Struktur)

| Feature | Neues Modul |
|---|---|
| Slash-Command-Registrierung | `commands/runtime_commands.py` (`register_runtime_commands`) |
| Raid/Settings/Kalender UI | `views/raid_views.py` |
| Runtime-Shared Helper/Konstanten | `utils/runtime_helpers.py` |
| Runtime-Lifecycle/Events | `features/runtime_mixins/events.py` (`RuntimeEventsMixin`) |
| Runtime-Logging + Worker | `features/runtime_mixins/logging_background.py` (`RuntimeLoggingBackgroundMixin`) |
| Runtime-State + Kalender | `features/runtime_mixins/state_calendar.py` (`RuntimeStateCalendarMixin`) |
| Runtime-RaidOps | `features/runtime_mixins/raid_ops.py` (`RuntimeRaidOpsMixin`) |
| Raid-Business-Logik | `services/raid_service.py` |
| Settings-Business-Logik | `services/settings_service.py` |
| Persistenz | `services/persistence_service.py` |
| Raidlist-Rendering | `services/raidlist_service.py` |
| Leveling | `services/leveling_service.py` |
| DB Zugriff/Rows | `db/repository.py`, `db/models.py`, `db/session.py` |
| Runtime-Bootstrap | `bot/runtime.py` |

## Schritt 3: Umgesetzter Stand

- Views aus `bot/runtime.py` ausgelagert nach `views/raid_views.py`.
- Slash-Command-Registrierung aus `bot/runtime.py` ausgelagert nach `commands/runtime_commands.py`.
- Runtime-Konstanten + Safe-/Zeit-/Embed-Helper ausgelagert nach `utils/runtime_helpers.py`.
- Runtime-Methoden in Feature-Mixins aufgeteilt (`features/runtime_mixins/*`).
- `bot/runtime.py` delegiert Command-Setup über `register_runtime_commands(self)`.
- Persistente View-Wiederherstellung nutzt die ausgelagerten View-Klassen über lokale Imports.

## Aktuelle Entry-Points (nach Refactor)

### Slash-Commands (`commands/runtime_commands.py`)
- `/settings`
- `/status`
- `/id`
- `/help`
- `/help2`
- `/restart`
- `/dungeonlist`
- `/raidplan`
- `/raid_finish`
- `/raidlist`
- `/raidcalendar_rebuild`
- `/cancel_all_raids`
- `/template_config`
- `/purge`
- `/purgebot`
- `/remote_guilds`
- `/remote_cancel_all_raids`
- `/remote_raidlist`
- `/remote_rebuild_memberlists`
- `/backup_db`

### Discord UI (`views/raid_views.py`)
- `RaidCreateModal`
- `RaidDateSelectionView`
- `RaidVoteView`
- `FinishButton`
- `SettingsView`
- `SettingsToggleButton`
- `SettingsIntervalsModal`
- `SettingsSaveButton`
- `RaidCalendarView`
- `RaidCalendarShiftButton`
- `RaidCalendarTodayButton`

### Listener (`features/runtime_mixins/events.py`)
- `on_ready`
- `on_guild_join`
- `on_guild_remove`
- `on_member_join`
- `on_member_update`
- `on_message`
- `on_voice_state_update`

### Scheduler/Worker (`features/runtime_mixins/events.py`)
- `stale_raid_worker`
- `raid_reminder_worker`
- `integrity_cleanup_worker`
- `voice_xp_worker`
- `level_persist_worker`
- `username_sync_worker`
- `self_test_worker`
- `backup_worker`
- `log_forwarder_worker`

## Nächste optionale Auslagerungen

- Kalender-/Raidlist-spezifische Runtime-Methoden in eigene Feature-Module (z. B. `features/calendar_runtime.py`, `features/raidlist_runtime.py`) per Mixins/Delegation.
- Debug-/Log-Forwarding als separates Runtime-Feature-Modul.
