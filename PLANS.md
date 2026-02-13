# PLANS.md — Long Execution Plan for Discord Bot Rewrite

######################################################################
# PHASE 1 — INVENTORY
######################################################################

- Enumerate all slash commands
- Enumerate views, buttons, selects, modals
- Enumerate DB tables and relationships
- Analyze .github/workflows/bot.yml
- Extract ENV variables
- Build Feature Matrix:

Feature → current files → DB tables → expected behavior → tests → edge cases

Append matrix to DELIVERY_REPORT.md.

Do not continue until Feature Matrix is complete.

######################################################################
# PHASE 2 — REWRITE
######################################################################

Rebuild modular architecture:

main.py
config.py
db/
models/
repositories/
services/
commands/
views/
utils/
tests/

Rules:

- Business logic separated from Discord API layer
- No schema changes
- No race conditions
- Persistent views after restart
- Rate-limit safe embed updates
- Role creation + cleanup preserved
- Raid cleanup only via creator button
- Voting logic identical

######################################################################
# PHASE 3 — TESTING
######################################################################

Implement:

UNIT TESTS (pytest)
- Raid creation
- Vote toggle
- Minimum player trigger
- Cleanup logic
- Repository CRUD

ASYNC TESTS (pytest-asyncio)
- Slash command handlers
- View callbacks
- Permission checks
- Error paths

DB TESTS
- CRUD with test database
- Schema compatibility

STARTUP SMOKE TEST
- DB connection
- Tables exist
- Persistent views restored
- Boot log OK

Run:

pip install -r requirements.txt
pytest -q

If tests fail:
- Fix
- Rerun
- Repeat until green

######################################################################
# PHASE 4 — CI
######################################################################

Update .github/workflows/bot.yml:

- Install dependencies
- Run pytest
- Fail on error
- Use secrets correctly
- Implement crash restart strategy
- Optional scheduled restart
- Document limitations in README

######################################################################
# HARD STOP CONDITION
######################################################################

The task is NOT complete if:

- Only documentation changed
- Tests were not executed
- pytest output is missing
- Application source files were not modified

Completion requires:

- Code modifications in core logic
- Passing tests
- CI workflow aligned
