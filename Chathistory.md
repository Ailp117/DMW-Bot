# Chathistory.md

## Scope
This file captures the full technical history and current state from the long rewrite chat, so a new chat can resume reliably.

Date of capture: 2026-02-13
Repository: DMW-Bot

## Initial constraints acknowledged
- `AGENTS.md` and `PLANS.md` are binding.
- No modification of DB schema.
- SQL backup file (`supabase_full_backup.sql`) must stay untouched.
- New bot must run from new code only, not legacy runtime.

## High-level outcome
- New runtime path is active and independent from legacy code.
- GitHub Actions runtime job starts `bot/runtime.py` through `bot/runner.py`.
- Legacy code is archived in `legacy_archive/` and not referenced by runtime.
- Core raid flow, persistence, restart restoration, and safety logic are implemented in new runtime.

## Major implementation timeline

### 1) Runtime and workflow path cleanup
- Runner default target changed to new runtime script.
- Workflow runtime command uses:
  - `python -m bot.runner --target-script bot/runtime.py`
- Removed runtime references to `legacy_archive`.

### 2) New runtime logic built in `bot/runtime.py`
Implemented new bot runtime with:
- Discord client startup and command sync.
- DB load/flush through `RepositoryPersistence`.
- Required table validation at startup.
- Singleton advisory lock acquisition.
- Safe interaction wrappers to reduce double-response issues.

### 3) Restart-safe restoration
Implemented restart restoration behavior:
- Persistent raid vote views are re-registered on startup.
- Existing raid planner messages are edited/reused if present.
- Existing participant slot messages are edited/reused if present.
- Raidlist message is edited/reused via stored message id.
- If a tracked message is missing, bot recreates and stores new id.

### 4) Raid flow parity pieces
Implemented or restored:
- Raid creation through `/raidplan` modal flow.
- Voting through message-based selects (`RaidVoteView`).
- Finish via button and `/raid_finish`.
- Attendance snapshot creation on finish.
- Memberlist sync and cleanup.
- Temp raid role creation/reuse/cleanup.

### 5) Background workers added to runtime
Singleton worker startup via task registry:
- stale raid worker
- voice xp worker
- self-test worker
- backup worker
- log forwarder worker

### 6) Debug mirror behavior
Implemented debug mirror updates with DB cache and payload hash for:
- raidlist debug channel
- memberlist debug channel

### 7) Command access changes requested during chat
Applied command permission and list changes:
- `/restart` restricted to privileged user only (`PRIVILEGED_USER_ID`).
- Removed attendance commands from runtime:
  - `/attendance_list`
  - `/attendance_mark`
- Removed vote slash command:
  - `/raid_vote`
- Removed options info command:
  - `/raid_options`
- Voting is now intended via raid message selects only.

### 8) Participation counter request
Requirement: store per-user raid participation count in DB (start at 0, +1 per raid participation).
Implemented as DB-derived counter:
- Attendance snapshot rows are stored as `status="present"` for participants on raid finish.
- Added repository method:
  - `raid_participation_count(guild_id, user_id)`
- Counter semantics:
  - 0 when no present rows
  - +1 per finished raid where user was captured present

### 9) Vote message display request
Requirement: show who voted in vote message without mentions.
Implemented and then refined:
- Added non-mention plain-name list in planner embed.
- Final requested state:
  - only show users who fully voted (day + time)
  - do not show partial list

## Current slash commands (after all requested removals)
From `bot/runtime.py` command registration:
- `/settings`
- `/status`
- `/help`
- `/help2`
- `/restart` (privileged only)
- `/dungeonlist`
- `/raidplan` (modal)
- `/raid_finish`
- `/raidlist`
- `/cancel_all_raids`
- `/template_config`
- `/purge`
- `/purgebot`
- `/remote_guilds` (privileged only)
- `/remote_cancel_all_raids` (privileged only)
- `/remote_raidlist` (privileged only)
- `/backup_db` (privileged only)

Removed during this chat:
- `/attendance_list`
- `/attendance_mark`
- `/raid_vote`
- `/raid_options`

## Test and validation snapshots recorded
Repeated checks executed successfully.
Most recent full test output:

```
........................................                                 [100%]
40 passed in 0.14s
```

Other checks that passed during chat:
- `python -m py_compile ...` for project modules
- `python -m bot.runner --help`
- `python -m bot.runtime` fails fast without env (expected):
  - `Config error: DATABASE_URL must be set`

## Files significantly changed during chat
- `.github/workflows/bot.yml`
- `bot/runner.py`
- `bot/runtime.py`
- `services/persistence_service.py`
- `db/repository.py`
- `services/startup_service.py`
- `README.md`
- `tests/test_phase3_participation_counter.py` (added)

## Operational notes for next chat
If a new chat should continue safely:
1. Read this file first.
2. Confirm current `bot/runtime.py` command list and worker behavior.
3. Run:
   - `pytest -q`
4. If changing commands, also update:
   - `services/startup_service.py` expected command set
   - README command section

## Important behavior decisions from user
- Bot should run only from new scripts.
- Legacy code should be ignored in runtime.
- Vote actions should happen via vote message UI, not via vote slash command.
- Attendance commands are not needed.
- Participation counter should be DB-only for now.
- Vote message should show only fully-voted users, without mentions.

## Incremental updates after initial capture (2026-02-13)

### Repository upload preparation changes
- Added root `.gitignore` with runtime/cache/venv exclusions.
- `legacy_archive/` is now excluded from upload.
- `supabase_full_backup.sql` is now excluded from upload (kept local as reference only).
- `.venv/` was removed from git tracking and is ignored.

### DB schema guard hardening
- Startup guard now validates both required tables and required columns.
- Added tests for:
  - missing tables
  - missing columns
  - full schema pass
- Later expanded to auto-repair behavior at startup:
  - create missing tables
  - add missing columns
  - ensure critical unique indexes
- Required table scope now derives from all mapped SQLAlchemy bot models:
  - `REQUIRED_BOOT_TABLES = mapped_public_table_names()`

### Runtime persistence reliability fix
- Fixed a persistence edge case in debounced raidlist refresh path.
- `DebouncedGuildUpdater` now calls a persisted wrapper:
  - refresh raidlist
  - flush repository state under lock
- Added tests to ensure:
  - debounced refresh triggers persist
  - force refresh uses direct path as intended

### Live database verification against production URL
- Connected read-only to provided DB and verified:
  - required tables present
  - required columns present
  - critical indexes present
- After auto-schema feature was enabled, re-check reported:
  - `SCHEMA_CHANGES []`
  - `VALIDATION OK`

### Current latest test snapshots
- `44 passed in 0.16s` after column-level schema guard addition.
- `46 passed in 0.17s` after auto-schema adaptation implementation.
- `47 passed in 0.18s` after dynamic mapped-table scope update.
- `49 passed, 1 warning in 0.55s` after persistence edge-case tests.
- Warning details:
  - `DeprecationWarning: 'audioop' is deprecated and slated for removal in Python 3.13`
  - source: `discord.py` dependency (`.venv/.../discord/player.py`), not bot application code.

### Security note logged
- Database credentials were shared in chat during troubleshooting.
- Recommendation recorded: rotate DB password after verification.

### New operational rule (2026-02-13)
- Requirement requested: update `Chathistory.md` every 10 minutes with current chat state.
- Technical constraint: no autonomous background timer exists between user turns in this environment.
- Enforced fallback rule: `Chathistory.md` is updated on every relevant user turn/change so history remains current during active collaboration.

### Full integration re-check and safe optimizations (2026-02-13)
- Full new-bot health check repeated:
  - `pytest -q` passed (`50 passed, 1 warning`).
  - `python3 -m py_compile bot/*.py db/*.py discord/*.py features/*.py services/*.py utils/*.py` passed.
  - `python3 -m bot.runner --help` passed.
- Safe optimization applied in `services/backup_service.py`:
  - Backup SQL now uses deterministic FK-safe table ordering for `DELETE` and `INSERT`.
  - Prevents restore-order FK issues (e.g., child rows before parent rows).
- New regression test added in `tests/test_phase3_backup.py`:
  - Validates FK-safe ordering in generated backup SQL.
- Safety hardening in `bot/runtime.py`:
  - Added debug logging for unexpected exceptions inside safe Discord wrappers.
  - `_find_open_raid_by_display_id` now safely skips raids with `display_id=None` to avoid potential runtime cast errors.

### Log channel enhancements (2026-02-13)
- Discord log forwarding now includes both logger domains:
  - `dmw.runtime`
  - `dmw.db` (SQL query logs from DB session hooks)
- Each forwarded log message now contains explicit source metadata:
  - logger name
  - module
  - function
  - line number
- Validation after change:
  - `pytest -q` -> `50 passed, 1 warning`.

### Full code scan + DB request optimization pass (2026-02-13, latest)
- Performed full regression and safety scan on active runtime path.
- Validation status:
  - `pytest -q` => `76 passed, 1 warning`
  - `python -m compileall bot db services features utils tests` => passed
- Existing warning remains external-only (`discord.py` `audioop` deprecation), no runtime failure.

#### Level system hardening and command XP exclusion
- Confirmed/kept integer-safe XP thresholds in `utils/leveling.py`.
- Added runtime guard so registered bot commands do not grant message XP:
  - Slash-like command names are extracted and checked against registered command set.
  - If message content matches a registered command (e.g. `/status`), XP award path is skipped.
- Added tests in `tests/test_phase3_command_xp_filter.py` to verify:
  - command detection
  - no XP on command messages
  - XP still granted for normal messages

#### DB query/load reduction improvements
- Major persistence optimization in `services/persistence_service.py`:
  - Added deterministic repository snapshot fingerprinting.
  - `flush()` now short-circuits (no SQL delete/insert cycle) when state is unchanged.
  - `load()` now stores baseline fingerprint so first no-op flush can be skipped.
- Added test `tests/test_phase3_persistence_optimization.py`:
  - verifies unchanged state does not open a DB write cycle again.

#### Bot message index optimization (reduces DB churn)
- Improved bot-message tracking in `bot/runtime.py`:
  - Added per-channel cap for indexed bot messages (`BOT_MESSAGE_INDEX_MAX_PER_CHANNEL`).
  - Oldest index rows are pruned automatically.
- Purpose:
  - keeps `debug_mirror_cache` bounded
  - avoids unbounded growth and expensive full-table flush payloads
  - keeps `/purgebot` indexed path fast
- Added regression coverage in `tests/test_phase3_purgebot_index.py` for pruning behavior.

#### Additional minor safety fix
- Updated `bot/main.py` self-test timestamp to timezone-aware UTC (`datetime.now(UTC)`).

#### Latest verified test snapshot
- `76 passed, 1 warning in 0.48s`

### Message formatting + username sync + runtime trigger policy update (2026-02-13, newest)

#### Message formatting refresh (new runtime)
- Updated raid-facing message presentation to be closer to legacy readability while keeping new architecture:
  - `services/raidlist_service.py`
    - Raidlist now uses structured bullet lines with icons and clickable Discord message links.
    - Empty state text changed to localized format (`Keine offenen Raids.`).
  - `services/raid_service.py`
    - Participant slot posts now use a structured block:
      - dungeon header
      - raid id
      - day/time
      - participant counter
      - user mention list
  - `bot/runtime.py` planner embed
    - Better section headers and vote formatting (`• **Label** — \`count\``)
    - clearer title/description style
    - improved footer text

#### Username sync implementation (server-wide)
- Added robust username capture and persistence into existing DB model (`user_levels.username`) without schema changes.
- Implemented in `bot/runtime.py`:
  - immediate sync on guild join (`force=True`)
  - periodic background sync worker (`username_sync_worker`)
  - realtime updates on `on_member_join` and `on_member_update`
  - DB fallback for planner voter-name rendering when member object is not cached
- Added throttling controls:
  - `USERNAME_SYNC_WORKER_SLEEP_SECONDS = 10 * 60`
  - `USERNAME_SYNC_RESCAN_SECONDS = 12 * 60 * 60`
- Username writes are batched through existing dirty/persist flow (no forced per-event flush), reducing DB write pressure.

#### Tests added/updated for this phase
- Added: `tests/test_phase3_username_sync.py`
  - verifies insert of usernames during guild scan
  - verifies update on renamed members
  - verifies planner name fallback from DB username
- Updated: `tests/test_phase3_raidlist.py`
  - verifies new formatted raidlist content and Discord jump URL output

#### Verification snapshot after these changes
- `pytest -q` => `79 passed, 1 warning in 0.47s`
- `python -m compileall bot db services features utils tests` => passed

#### Workflow runtime trigger policy (manual-first + watchdog)
- Updated `.github/workflows/bot.yml` so runtime behavior matches requested operation:
  - Push/PR do NOT auto-start runtime hosting job.
  - Runtime starts manually via `workflow_dispatch`.
  - 6h schedule remains present, but runs runtime only when watchdog flag is enabled.
  - Manual dispatch toggles repo variable `BOT_RUNTIME_WATCHDOG`:
    - `start_runtime=true` => enable watchdog + start runtime now
    - `start_runtime=false` => disable watchdog (no runtime start)
- Monthly dependency refresh schedule remains unchanged.

#### Relevant commits recorded in this period
- `a3865f3` — message formatting + username sync implementation/tests
- pending commit in this step — chathistory update + workflow trigger policy update

### Delta persistence update (2026-02-13, newest)
- Refined `services/persistence_service.py` flush strategy:
  - removed full-table `DELETE` + full `INSERT` rewrite cycle for normal runtime persistence.
  - flush now computes per-table snapshots and applies only row-level deltas:
    - `INSERT` for newly added rows
    - `UPDATE` for changed rows (same primary key)
    - `DELETE` for removed rows
  - unchanged repository state still short-circuits with fingerprint check (no DB write cycle).
- Added/updated tests:
  - `tests/test_phase3_persistence_optimization.py`
    - verifies unchanged state does not open another write cycle
    - verifies changed existing row uses `UPDATE` (not delete/reinsert).
- Verification snapshot:
  - `.venv/bin/pytest -q` => `83 passed, 1 warning in 0.62s`

### Delta flush optimization pass 2 (2026-02-13, newest)
- Further optimized runtime delta flush in `services/persistence_service.py`:
  - added per-table fingerprint tracking to detect changed tables precisely.
  - flush now skips completely unchanged tables when applying SQL deltas.
  - delete operations are now batched (`IN (...)` chunked) instead of single-row delete statements.
- Added regression coverage in `tests/test_phase3_persistence_optimization.py`:
  - verifies delete path only affects changed target table rows and does not issue unrelated table deletes.
- Verification snapshot:
  - `.venv/bin/pytest -q tests/test_phase3_persistence_optimization.py` => `3 passed in 0.08s`
  - `.venv/bin/pytest -q` => `84 passed, 1 warning in 0.48s`

### Delta flush optimization pass 3 + code health scan (2026-02-13, newest)
- Additional runtime persistence optimizations in `services/persistence_service.py`:
  - fingerprint calculation switched to streaming table/global hashes (reduced temporary JSON payload work).
  - row updates now write only changed non-PK columns (cell-level update semantics within changed rows).
  - insert batches are chunked (`_INSERT_CHUNK_SIZE`) to avoid large one-shot ORM add lists.
- Test hardening in `tests/test_phase3_persistence_optimization.py`:
  - asserts guild_settings update writes only the changed column (`guild_name`).
- Global reliability tweak in `bot/runtime.py`:
  - shutdown no longer silently swallows failures for task cancellation / log-handler detach; now logs exceptions.
- Full verification:
  - `.venv/bin/pytest -q` => `84 passed, 1 warning in 0.46s`
  - `python3 -m compileall bot db discord features services utils tests` => passed

### Delta flush optimization pass 4 (2026-02-13, newest)
- Further reduced flush overhead in `services/persistence_service.py`:
  - flush now computes table fingerprints directly from repository rows first.
  - row snapshots are materialized only for tables that actually changed (instead of building full snapshot each flush).
  - unchanged-table snapshots are reused from last successful flush state.
- Safety and behavior:
  - SQL write semantics remain delta-based (`DELETE` removed rows, `UPDATE` changed fields, `INSERT` new rows).
  - no schema changes were introduced.
- Verification:
  - `.venv/bin/pytest -q tests/test_phase3_persistence_optimization.py` => `3 passed in 0.08s`
  - `.venv/bin/pytest -q` => `84 passed, 1 warning in 0.46s`
  - `python3 -m compileall bot db discord features services utils tests` => passed

### Repository/runtime optimization pass 5 (2026-02-13, newest)
- Optimized debug-cache lookup performance in `db/repository.py`:
  - added in-memory secondary indexes for `debug_cache` by:
    - kind
    - (kind, guild)
    - (kind, guild, raid)
  - `list_debug_cache` now uses index fast-paths for common query shapes used by runtime.
  - upsert/delete/reset/recalculate now maintain/rebuild index consistency.
- Hardened bot-message index cleanup in `bot/runtime.py`:
  - `_clear_bot_message_index_for_id` now removes matching cache rows by `(kind, guild, channel, message_id)` scan of indexed rows.
  - avoids dependence on current bot user id in cache key composition.
- Added regression coverage:
  - `tests/test_phase3_debug_mirror.py`
    - verifies indexed kind/guild/raid filter behavior
    - verifies reindexing on upsert scope changes
- Verification:
  - `.venv/bin/pytest -q tests/test_phase3_debug_mirror.py tests/test_phase3_purgebot_index.py tests/test_phase3_persistence_optimization.py` => `10 passed, 1 warning in 0.36s`
  - `.venv/bin/pytest -q` => `86 passed, 1 warning in 0.52s`
  - `python3 -m compileall db/repository.py bot/runtime.py tests/test_phase3_debug_mirror.py` => passed

### Repository optimization pass 6 (2026-02-13, newest)
- Implemented O(1)-style vote toggle lookup in `db/repository.py`:
  - added in-memory vote key index: `(raid_id, kind, option_label, user_id) -> vote_id`
  - `toggle_vote` now checks/removes/adds via index instead of full `raid_votes` scan.
  - index is rebuilt on `recalculate_counters()` to stay consistent after DB load.
- Implemented bulk raid cascade deletion in `db/repository.py`:
  - added `_delete_raids_cascade(raid_ids)` to remove raids/options/votes/posted-slots in one pass.
  - `cancel_open_raids_for_guild` and `purge_guild_data` now use bulk cascade path.
- Voting behavior safety (important):
  - multi-select semantics are preserved (users can still vote for multiple day options and multiple time options).
  - only exact same `(raid_id, kind, option_label, user_id)` vote is toggled.
- Added/updated tests:
  - `tests/test_phase3_voting.py`
    - verifies same user can keep multiple day/time selections.
  - `tests/test_phase3_repository_cascade.py`
    - verifies bulk cascade removes only target guild raid data and keeps remaining guild voting functional.
- Verification:
  - `.venv/bin/pytest -q tests/test_phase3_voting.py tests/test_phase3_repository_cascade.py tests/test_phase3_cleanup.py tests/test_phase3_participation_counter.py` => `8 passed in 0.05s`
  - `.venv/bin/pytest -q` => `89 passed, 1 warning in 0.60s`
  - `python3 -m compileall db/repository.py tests/test_phase3_voting.py tests/test_phase3_repository_cascade.py` => passed

### Runtime feature expansion + harmonization check (2026-02-13, newest)
- Implemented user timezone management and raid-timezone aware planning/reminders in `bot/runtime.py`.
  - Added `/timezone` command with autocomplete for IANA timezone names.
  - Raid creation now uses creator timezone context for date selection and stores raid-specific timezone metadata.
  - Reminder scheduling now parses slot date/time in raid timezone and converts to UTC safely.
- Added periodic integrity cleanup worker to remove orphaned runtime artifacts:
  - stale `raid_timezone`, `raid_reminder`, `slot_temp_role`, and disconnected `user_timezone` cache rows.
  - orphan temporary slot roles are cleaned when no open raid mapping exists.
- Reworked raidlist output from plain text to rich embed format:
  - per-raid structured fields (creator, min players, qualified slots, fully-voted count, timezone, next slot, planner jump link).
  - embed payload hash remains delta-aware to avoid redundant edits.
- Extended command registry expectations:
  - `services/startup_service.py` now includes `/timezone` in `EXPECTED_SLASH_COMMANDS`.

### Additional stabilization/tests in same pass (2026-02-13)
- Added tests for timezone and reminder behavior:
  - `tests/test_phase3_raid_reminder_and_roles.py`
    - timezone-aware UTC parsing
    - reminder send path with raid timezone
- Added orphan-cleanup coverage:
  - `tests/test_phase3_integrity_cleanup.py`
- Added new raidlist-embed coverage:
  - `tests/test_phase3_raidlist_embed.py`

### Latest verification snapshot (current)
- Type check:
  - `.venv/bin/pyright bot/runtime.py` => `0 errors, 0 warnings`
- Runtime compile validation:
  - `.venv/bin/python -m py_compile bot/runtime.py services/startup_service.py ...` => passed
- Full test suite:
  - `.venv/bin/python -m pytest -q` => `102 passed, 1 warning in 0.54s`
- Remaining warning source is external dependency only:
  - `discord.py` deprecation warning for Python `audioop` removal path.

### Timezone simplification (2026-02-13, latest)
- User request: remove per-user timezone complexity and pin bot scheduling timezone to Berlin.
- Applied in `bot/runtime.py`:
  - fixed default timezone to `Europe/Berlin`.
  - removed `/timezone` command and related autocomplete/config paths.
  - removed per-user/per-raid timezone cache logic from runtime flow.
  - raid planning and reminders now run with single global bot timezone (`Europe/Berlin`).
  - integrity cleanup now purges legacy `user_timezone` / `raid_timezone` cache rows from debug cache.
- Command registry alignment:
  - removed `timezone` from `services/startup_service.py` expected command set.
- Tests adjusted and revalidated:
  - `tests/test_phase3_raid_reminder_and_roles.py`
  - `tests/test_phase3_raidlist_embed.py`
  - `tests/test_phase3_integrity_cleanup.py`
- Verification:
  - `.venv/bin/python -m pytest -q` => `102 passed, 1 warning in 0.55s`
  - `.venv/bin/pyright bot/runtime.py` => `0 errors, 0 warnings`

### Full bot audit + active-code hardening (2026-02-13, latest)
- Performed full validation sweep:
  - `python3 -m compileall bot db discord features services utils tests` => passed
  - `.venv/bin/python -m pytest -q` => `102 passed, 1 warning`
- Ran broad static analysis and separated noise from relevant issues:
  - full-project `pyright` showed many legacy/test-only diagnostics.
  - active runtime modules were checked explicitly: `.venv/bin/pyright bot db discord features services utils`.

#### Fixes applied to active code (type-safety + robustness)
- `db/schema_guard.py`
  - tightened table/column helper typing (`Table`, `Any`) to remove unsafe `object`-typed paths.
  - typed `create_tables` as `list[Table]` for `Base.metadata.create_all(...)` compatibility.
- `discord/task_registry.py`
  - made task factory explicitly coroutine-based (`TaskFactory`), and typed task storage as `asyncio.Task[None]`.
  - removes awaitable/coroutine mismatch risk around `asyncio.create_task`.
- `db/models.py`
  - corrected SQLAlchemy mapped datetime annotations from `Mapped[DateTime]` to `Mapped[datetime]`.
  - this fixes wrong static assumptions in persistence load paths.
- `services/persistence_service.py`
  - normalized table-row map typing to `Mapping[Any, Any]` for mixed-key repositories.
- `services/raid_service.py`
  - hardened `upsert_posted_slot` update path when `row.message_id` is `None` by generating deterministic fallback id.

### Verification after hardening
- Active modules type-check:
  - `.venv/bin/pyright bot db discord features services utils` => `0 errors, 0 warnings`
- Full tests still green:
  - `.venv/bin/python -m pytest -q` => `102 passed, 1 warning in 0.51s`

### Full active-code audit + optimization pass (2026-02-13, latest)
- Scope audited (legacy excluded): `bot/`, `db/`, `discord/`, `features/`, `services/`, `utils/` + root requirements files.
- Requirements validation:
  - `requirements.in` and `requirements.txt` are consistent with resolver output.
  - `pip check` reported no broken dependencies.
- Runtime/performance refinements in `bot/runtime.py`:
  - added cached timezone resolver (`_zoneinfo_for_name`) to avoid repeated `ZoneInfo(...)` construction in hot paths.
  - reminder worker now caches participant channel lookups per channel id per pass (fewer repeated fetches).
- Type-safety/runtime hardening in active modules:
  - `db/schema_guard.py`: stricter table/column typing for `create_all` and DDL helper paths.
  - `discord/task_registry.py`: coroutine/task typing tightened (`TaskFactory`, `asyncio.Task[None]`).
  - `db/models.py`: corrected ORM annotations from `Mapped[DateTime]` to `Mapped[datetime]`.
  - `services/persistence_service.py`: stabilized row-map typing for mixed key spaces.
  - `services/raid_service.py`: guarded `message_id=None` path during slot upsert updates.
- Requirements resolver script robustness:
  - `scripts/resolve_second_latest_requirements.py` now prefers public `packaging` imports with runtime fallback and type-check-safe structure.
- Added `pyrightconfig.json` to lock static analysis scope to active code and exclude `legacy_archive`/tests noise.

### Verification snapshot after audit pass
- Static typing (active scope):
  - `.venv/bin/pyright` => `0 errors, 0 warnings`
- Compile checks:
  - `python3 -m compileall bot db discord features services utils tests` => passed
  - `python3 -m py_compile ...` on changed modules => passed
- Test suite:
  - `.venv/bin/python -m pytest -q` => `102 passed, 1 warning in 0.52s`

### Runtime/Persistence hardening + logging safety (2026-02-13, newest)
- Persist reliability and state safety:
  - `bot/runtime.py` `_persist(...)` now uses retry + exponential backoff (`PERSIST_FLUSH_MAX_ATTEMPTS=3`) instead of single-shot failure.
  - No automatic in-memory reload on flush failure anymore (prevents transient DB errors from discarding live runtime state).
  - `_persist` now accepts dirty-table hints and forwards them to persistence flush.
- Delta flush optimization:
  - `services/persistence_service.py` switched from full-table global fingerprint scan on every flush to hint-driven delta snapshots.
  - New `dirty_tables` path limits snapshot scope to likely-changed tables.
  - Periodic full-scan safety fallback remains (`_FULL_SCAN_EVERY_HINTED_FLUSHES=25`) to self-heal missed hints.
- Log volume + data exposure reduction:
  - `bot/config.py` default `DISCORD_LOG_LEVEL` changed from `DEBUG` to `INFO`.
  - Added strict `DISCORD_LOG_LEVEL` value validation.
  - `db/session.py` now redacts SQL parameters before logging (`<redacted>`, `<int>`, `<datetime>`, etc.) to avoid sensitive payload leakage.
- Additional runtime safety already integrated in same pass:
  - bounded log-forward queue with drop-oldest strategy under pressure.
  - console command parsing hardened so malformed slash-only input does not error.

### Tests added/updated for this pass
- `tests/test_phase3_runtime_persist_behavior.py`
  - verifies flush retry/backoff behavior.
  - verifies dirty-table hints are forwarded.
  - verifies no forced reload on flush failure.
- `tests/test_phase3_db_session_redaction.py`
  - validates SQL parameter redaction for scalar and nested payloads.
- `tests/test_phase3_config.py`
  - validates `DISCORD_LOG_LEVEL=INFO` default and invalid-level rejection.
- `tests/test_phase3_persistence_optimization.py`
  - verifies hint-scoped snapshot behavior for delta flush.
- Updated compatibility tests:
  - `tests/test_phase3_raidlist.py`
  - `tests/test_phase3_memberlist_restore_recreate.py`

### Latest verification snapshot
- Targeted tests:
  - `.venv/bin/python -m pytest -q tests/test_phase3_runtime_persist_behavior.py tests/test_phase3_db_session_redaction.py tests/test_phase3_config.py tests/test_phase3_persistence_optimization.py` => `13 passed, 1 warning`
- Full suite:
  - `.venv/bin/python -m pytest -q` => `127 passed, 1 warning in 0.72s`
- Static typing:
  - `.venv/bin/pyright` => `0 errors, 0 warnings`
- Compile/deps:
  - `.venv/bin/python -m compileall -q bot db discord features services utils tests` => passed
  - `.venv/bin/python -m pip check` => `No broken requirements found.`
