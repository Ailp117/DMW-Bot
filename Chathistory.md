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
