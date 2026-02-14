# AGENTS.md — ENTERPRISE EXECUTION CONTRACT (NON-NEGOTIABLE)

This document is the binding execution contract for Codex.

Failure to follow ANY rule in this document invalidates completion.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
0. ABSOLUTE AUTHORITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This file overrides:
- Any previous repository conventions
- Any prior AGENTS.md versions
- Any informal assumptions
- Any undocumented behaviors

No exceptions.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. FULL REWRITE MANDATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This repository MUST undergo:

- Complete behavioral inventory
- Complete legacy archival
- Complete modular rebuild
- Complete test enforcement
- Complete CI enforcement

This is NOT:
- A refactor
- A cleanup
- A patch cycle
- A hybrid migration

This IS a clean rebuild from zero with full behavioral parity.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. PHASE LOCK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Execution MUST follow:

Phase 1   — Inventory + Feature Matrix (analysis only)
Phase 1B  — Legacy Archival
Phase 2   — Modular Rebuild
Phase 3   — Test Enforcement Loop
Phase 4   — CI Enforcement
Final     — Feature Matrix Validation

No skipping.
No reordering.
No early termination.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. LEGACY ANALYSIS REQUIREMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Before moving ANY file:

- Entire repository must be analyzed.
- All commands must be extracted.
- All background tasks must be extracted.
- All Discord views/modals/buttons must be mapped.
- All DB interactions must be mapped.
- All config usage must be mapped.
- All message/role/channel side effects must be mapped.
- All interaction edge cases must be mapped.

Only AFTER FEATURE_MATRIX.md is complete may legacy files be moved.

Legacy files must be moved into:

    legacy_archive/

Deletion is forbidden.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. DATABASE IMMUTABILITY (ABSOLUTE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The database schema is LOCKED.

Forbidden:
- Table renaming
- Column renaming
- Adding columns
- Removing columns
- Changing constraints
- Adding indexes
- Running migrations
- Modifying schema SQL files

Any schema modification = HARD FAILURE.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. FEATURE PARITY ENFORCEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Every feature MUST be preserved:

- Slash commands
- Voting logic
- Raid creation
- Minimum participant trigger
- Cleanup on raid end (creator only)
- Persistent view restoration
- Raidlist refresh
- Background loops
- DB semantics

FEATURE_MATRIX.md is the authoritative checklist.

Any missing feature = NOT COMPLETE.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6. REQUIRED ARCHITECTURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Mandatory structure:

bot/
  main.py
  config.py
  logging.py
db/
discord/
features/
services/
utils/

Strict separation:
- No DB logic in Discord layer
- No Discord API in db/
- Business logic in services/
- Pure helpers in utils/

Violation = HARD FAILURE.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
7. DISCORD SAFETY REQUIREMENTS (BOMBENSICHER)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Mandatory protections:

- Interaction safety wrappers
- HTTP 40060 prevention
- Idempotent responses
- Idempotent message updates
- Safe edit wrappers (NotFound/Forbidden safe)
- Singleton background loops
- Async cancellation safety
- Restart-safe persistent views
- Defensive config validation

System must tolerate:
- Double button presses
- Restart with active raids
- Deleted messages
- Race conditions
- Discord reconnects

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
8. TEST ENFORCEMENT LOOP (MANDATORY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

pytest + pytest-asyncio REQUIRED.

Coverage MUST include:

- Raid creation
- Voting logic
- Min participant trigger
- Cleanup logic
- Raidlist refresh
- Interaction safety
- DB persistence after restart
- Background singleton enforcement
- Startup smoke test

Execution loop:

1. Run `pytest -q`
2. If ANY failure → fix
3. Re-run `pytest -q`
4. Repeat until ALL pass
5. Print COMPLETE output (no truncation)

Skipping this loop = HARD FAILURE.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
9. CI ENFORCEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

.github/workflows/bot.yml MUST:

- Install dependencies
- Install pytest
- Run pytest -q
- Fail on failure
- Cache pip
- Include scheduled cron watchdog

CI must enforce correctness on every push.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
10. QUESTION POLICY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If Codex encounters uncertainty:

- It MAY ask clarifying questions.
- After receiving answers, it MUST immediately continue execution.
- It may NOT stop permanently after asking.
- Questions do NOT justify phase skipping.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
11. HARD FAILURE CONDITIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Task is NOT complete if:

- Legacy moved before analysis
- FEATURE_MATRIX incomplete
- No Refactoring
- Tests not written
- pytest not executed
- pytest output missing
- Any failing test
- CI not running pytest
- Architecture incorrect
- Feature parity incomplete
- Early termination

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
12. FINAL VALIDATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

At end of execution:

Re-open FEATURE_MATRIX.md.

For EACH feature confirm:

- Implementation file(s)
- DB usage
- Test coverage

If ANY feature is not VERIFIED:

Return to implementation.
Repeat Phase 3.
Re-run validation.

Completion only allowed after full verification.
