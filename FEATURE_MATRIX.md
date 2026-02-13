# FEATURE_MATRIX.md

## Phase 1 Inventory + Feature Matrix

This matrix is the Phase 1 authoritative behavioral inventory for the legacy bot implementation.
No files were moved during this phase.

## Inventory: Slash Commands

- `/settings`
- `/status`
- `/help`
- `/help2`
- `/restart`
- `/raidplan`
- `/raidlist`
- `/dungeonlist`
- `/cancel_all_raids`
- `/purge`
- `/purgebot`
- `/remote_guilds`
- `/remote_cancel_all_raids`
- `/remote_raidlist`
- `/template_config`
- `/attendance_list`
- `/attendance_mark`
- `/backup_db`

## Inventory: Background Tasks / Loops

- `stale_raid_worker`
- `voice_xp_worker`
- `self_test_worker`
- `backup_worker`
- `log_forwarder_worker`
- Debounced guild-specific raidlist updater (`RaidlistUpdater`)

## Inventory: Discord Views / Modals / Buttons

- `SettingsView`
  - Planner channel selector
  - Participants channel selector
  - Raidlist channel selector
  - Save button
- `RaidCreateModal`
- `RaidVoteView`
  - Day select
  - Time select
  - `FinishButton` (`Raid beenden`)

## Inventory: Config / Env Usage

- `DISCORD_TOKEN`
- `DATABASE_URL`
- `DB_ECHO`
- `ENABLE_MESSAGE_CONTENT_INTENT`
- `LOG_GUILD_ID`
- `LOG_CHANNEL_ID`
- `SELF_TEST_INTERVAL_SECONDS`
- `BACKUP_INTERVAL_SECONDS`
- `DISCORD_LOG_LEVEL`
- `RAIDLIST_DEBUG_CHANNEL_ID`
- `MEMBERLIST_DEBUG_CHANNEL_ID`
- Privileged user constant: `PRIVILEGED_USER_ID`

## Inventory: Interaction / Crash Risks (Including HTTP 40060)

- Double interaction acknowledgement risk (button/select/modal callbacks).
- Concurrent update races for same raidlist guild refresh.
- Concurrent vote toggles and memberlist synchronization.
- Editing/deleting stale or already-deleted Discord messages (`NotFound`).
- Permission-denied message/role operations (`Forbidden`).
- Restart with open raids and persistent views not re-registered.
- Duplicate loop start risk on reconnect.
- Multiple bot process instances handling same interactions (HTTP 40060 risk surface).

## Feature Matrix

| Feature | Legacy Files | DB Tables / Columns | Expected Behavior | Acceptance Criteria | Planned Test Coverage |
|---|---|---|---|---|---|
| Command registration and sync | `main.py`, `commands_*.py` | `guild_settings.guild_id` | Register exact slash command set and sync per known guild with global fallback. | Missing guild access does not crash sync; expected command names are present. | `tests/test_phase3_startup_commands.py::test_expected_command_set_registered`, `tests/test_phase3_startup_commands.py::test_sync_uses_guild_targets_then_global` |
| Settings UI and persistence | `main.py`, `views_settings.py`, `helpers.py` | `guild_settings.guild_id`, `planner_channel_id`, `participants_channel_id`, `raidlist_channel_id`, `raidlist_message_id`, `guild_name` | Admin opens settings view and saves channel configuration. | Save persists channels; raidlist message id resets on raidlist channel change; confirmation is sent. | `tests/test_phase3_settings.py::test_settings_save_persists_and_resets_raidlist_message_id` |
| Raid planning command and autocomplete | `commands_raid.py`, `helpers.py` | `dungeons.name`, `dungeons.is_active`, `dungeons.sort_order`, `guild_settings.*`, `raid_templates.*` | `/raidplan` validates active dungeon + required channels and opens modal with defaults; autocomplete filters active dungeons. | Invalid dungeon/settings return ephemeral error; valid command opens modal with deterministic defaults. | `tests/test_phase3_raidplan.py::test_raidplan_validates_inputs_and_uses_template_defaults`, `tests/test_phase3_raidplan.py::test_dungeon_autocomplete_filters_active_rows` |
| Raid creation modal flow | `views_raid.py`, `helpers.py` | `raids.id`, `raids.display_id`, `raids.guild_id`, `raids.channel_id`, `raids.creator_id`, `raids.dungeon`, `raids.status`, `raids.message_id`, `raids.min_players`; `raid_options.raid_id`, `kind`, `label`; `raid_templates.*` | Modal submission defers fast, validates input, creates raid + options, posts planner message, stores message id, schedules raidlist refresh, and updates auto template when enabled. | Created raid has per-guild display id and posted planner message; invalid inputs return user-safe errors. | `tests/test_phase3_raid_creation.py::test_create_raid_persists_display_id_and_options`, `tests/test_phase3_raid_creation.py::test_modal_validation_rejects_bad_min_players` |
| Voting logic and idempotent toggle | `views_raid.py`, `helpers.py` | `raid_votes.raid_id`, `kind`, `option_label`, `user_id`; `raids.id`; `raid_options.*` | Day/time selections toggle votes (insert/remove), refresh planner embed, and keep consistent counts. | Repeated selection toggles without duplicate vote rows and without exceptions. | `tests/test_phase3_voting.py::test_toggle_vote_insert_then_remove`, `tests/test_phase3_voting.py::test_vote_counts_reflect_rows` |
| Min participant trigger and memberlist slot sync | `views_raid.py`, `helpers.py`, `roles.py` | `raids.min_players`, `raids.temp_role_id`, `raids.temp_role_created`; `raid_votes.*`; `raid_posted_slots.raid_id`, `day_label`, `time_label`, `channel_id`, `message_id`; `guild_settings.participants_channel_id` | Compute day/time intersections; threshold is `1` when min players is `0`; post/edit/delete participant slot messages idempotently; optional temp role mention. | `min_players=0` still triggers at one participant; stale slot messages are removed cleanly. | `tests/test_phase3_memberlist.py::test_min_zero_maps_to_threshold_one`, `tests/test_phase3_memberlist.py::test_sync_creates_updates_and_deletes_slot_rows` |
| Raid finish cleanup (creator only) and attendance snapshot | `views_raid.py`, `helpers.py`, `roles.py` | `raids.creator_id`, `raids.id`, `raids.display_id`, `raids.guild_id`, `raids.dungeon`, `raids.min_players`; `raid_attendance.guild_id`, `raid_display_id`, `dungeon`, `user_id`, `status`; `raid_posted_slots.*`; cascade via `raids` FK | Only creator can finish raid; cleanup slot messages and temp role; delete open raid; persist attendance snapshot rows before deletion. | Non-creator denied; creator finish removes open raid state and keeps attendance rows. | `tests/test_phase3_cleanup.py::test_finish_requires_creator`, `tests/test_phase3_cleanup.py::test_finish_deletes_raid_and_keeps_attendance_snapshot` |
| Persistent view and memberlist restoration on restart | `main.py`, `views_raid.py` | `raids.status`, `raids.message_id`, `raids.id`; `raid_options.raid_id`, `kind`, `label`; `raid_posted_slots.*` | On startup, restore persistent vote views and rebuild memberlist posts for open raids. | Restart simulation retains interactive raid posts and memberlist sync behavior. | `tests/test_phase3_restart_persistence.py::test_restore_persistent_views_for_open_raids`, `tests/test_phase3_restart_persistence.py::test_restore_memberlists_for_open_raids` |
| Raidlist refresh and debounced updater | `raidlist.py`, `raidlist_updater.py` | `guild_settings.raidlist_channel_id`, `raidlist_message_id`; `raids.guild_id`, `status`, `display_id`, `dungeon`, `min_players`, `channel_id`, `message_id`, `created_at` | Build raidlist embed from open raids; edit existing message or create new one; debounce/cooldown refresh storms. | Burst refresh requests converge to consistent result with bounded update calls. | `tests/test_phase3_raidlist.py::test_raidlist_updater_debounces_and_forces`, `tests/test_phase3_raidlist.py::test_raidlist_render_contains_open_raids` |
| Debug mirror cache for raidlist/memberlist | `raidlist.py`, `views_raid.py` | `debug_mirror_cache.cache_key`, `kind`, `guild_id`, `raid_id`, `message_id`, `payload_hash` | Mirror debug payloads, skip unchanged payload reposts, update existing message, recreate missing message. | Unchanged payload does not duplicate messages; deleted mirrored message is recreated. | `tests/test_phase3_debug_mirror.py::test_payload_hash_skips_duplicate_updates` |
| Admin and remote maintenance commands | `commands_admin.py`, `commands_remote.py`, `helpers.py`, `roles.py`, `raidlist.py` | `raids.guild_id`, `raids.status`, `raids.id`; `guild_settings.guild_id`, `guild_settings.guild_name`; `dungeons.is_active`; `raid_posted_slots.*` | Admin commands list dungeons and cancel all open raids locally. Privileged remote commands resolve guild target and cancel/refresh remotely. | Permission gates enforced; cancel operations clean raid state and schedule raidlist refresh. | `tests/test_phase3_admin_remote.py::test_cancel_all_raids_cleans_open_rows`, `tests/test_phase3_admin_remote.py::test_remote_target_resolution_rules` |
| Attendance commands | `commands_attendance.py` | `raid_attendance.guild_id`, `raid_display_id`, `user_id`, `status`, `marked_by_user_id`, `dungeon` | Admin lists attendance rows and marks status for existing attendance row. | Missing row returns error; successful mark updates `status` and `marked_by_user_id`. | `tests/test_phase3_attendance.py::test_mark_updates_status_and_marker` |
| Template toggle and auto-template sync | `commands_templates.py`, `commands_raid.py`, `views_raid.py`, `helpers.py` | `guild_settings.templates_enabled`; `raid_templates.guild_id`, `dungeon_id`, `template_name`, `template_data` | `/template_config` toggles auto templates; raid planning reads/writes auto dungeon defaults. | Flag persists and controls whether defaults are loaded/synced. | `tests/test_phase3_templates.py::test_template_toggle_and_auto_template_upsert` |
| Manual and scheduled SQL backup | `commands_backup.py`, `backup_sql.py`, `main.py` | Full existing schema via ORM metadata scan (read-only export) | Privileged manual backup and periodic auto-backup export SQL snapshot with lock + atomic write. | Concurrent backups are serialized; failure returns safe error message. | `tests/test_phase3_backup.py::test_backup_export_lock_and_atomic_replace`, `tests/test_phase3_backup.py::test_backup_command_failure_path` |
| Startup safety and singleton loop enforcement | `main.py`, `db.py` | Advisory lock query `pg_try_advisory_lock`; smoke-check tables: `guild_settings`, `raids`, `raid_votes`, `raid_attendance`, `dungeons`, `user_levels`, `raid_templates` | Startup enforces singleton instance lock, runs boot smoke checks, starts each background loop once, and keeps health status from self-tests. | Lock conflict exits safely; smoke-check failure is explicit; duplicate loop creation is prevented. | `tests/test_phase3_startup_safety.py::test_singleton_lock_gate`, `tests/test_phase3_startup_safety.py::test_boot_smoke_check_required_tables`, `tests/test_phase3_startup_safety.py::test_background_loops_singleton` |
| Stale raid cleanup loop | `main.py`, `views_raid.py`, `roles.py`, `helpers.py` | `raids.status`, `raids.created_at`, `raids.guild_id`, `raids.id`; cascade tables; role fields in `raids` | Periodically remove stale open raids, cleanup participant posts and temp roles, and refresh raidlist for affected guilds. | Only stale open raids are removed and no unhandled exceptions on missing Discord entities. | `tests/test_phase3_stale_cleanup.py::test_cleanup_stale_raids_only` |
| XP/level progression and message triggers | `main.py`, `leveling.py`, `models.py` | `user_levels.guild_id`, `user_id`, `username`, `xp`, `level`, `updated_at` | Voice and message XP update user level rows; level-up message emitted; keyword replies for `nanomon` and `approved` are case-insensitive word-boundary matches. | XP and level thresholds are deterministic and trigger helpers are boundary-safe. | `tests/test_phase3_leveling.py::test_level_threshold_math`, `tests/test_phase3_leveling.py::test_keyword_helpers_word_boundary` |
| Guild lifecycle hygiene and live log forwarding | `main.py`, `helpers.py` | `guild_settings.guild_id`, `guild_name`; `raids.guild_id`; `user_levels.guild_id` | On guild removal/startup cleanup, purge orphan guild data; on guild join, bootstrap settings and sync commands; queue/forward logs to configured log channel safely. | Guild lifecycle handlers are exception-safe and leave consistent in-memory/DB state. | `tests/test_phase3_guild_lifecycle_logging.py::test_on_guild_remove_purges_data_and_timers`, `tests/test_phase3_guild_lifecycle_logging.py::test_log_queue_buffers_before_ready` |
