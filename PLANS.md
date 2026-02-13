# PLANS.md — ENTERPRISE PHASE EXECUTION BLUEPRINT

This file defines the irreversible execution order.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 1 — INVENTORY + FEATURE MATRIX
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Goal:
Extract 100% behavior from legacy system.

Actions:
- Analyze entire repository.
- Extract commands.
- Extract tasks.
- Extract views/modals.
- Extract DB interactions.
- Extract channel/role side effects.
- Extract config/env usage.
- Identify crash risks.

Generate FEATURE_MATRIX.md:

Columns:
Feature
Legacy Files
DB Tables / Columns
Expected Behavior
Acceptance Criteria
Planned Test Coverage

Hard Stop:
- Missing feature
- Missing DB mapping
- Missing acceptance criteria

NO FILE MOVEMENT ALLOWED IN PHASE 1.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 1B — LEGACY ARCHIVAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Goal:
Prepare clean root for rebuild.

Actions:
- Create legacy_archive/
- Move all legacy implementation files
- Preserve structure
- Do NOT delete anything

Keep only:
- .gitignore
- LICENSE
- README.md
- .github/workflows/
- DB schema files

Hard Stop:
- Files deleted
- Files moved before Phase 1 completion

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 2 — COMPLETE MODULAR REBUILD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Goal:
Rebuild from scratch.

Requirements:
- Required folder structure enforced
- Full feature parity
- Discord safety wrappers
- Idempotent updates
- Singleton loops
- Async cancellation safety
- No DB schema modification

Hard Stop:
- Mixed layers
- Schema change
- Missing feature parity

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 3 — TEST ENFORCEMENT LOOP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Goal:
Achieve fully green test suite.

Actions:
- Implement pytest + pytest-asyncio
- Cover ALL features
- Run pytest -q
- Fix failures
- Repeat until green
- Print COMPLETE pytest output

Hard Stop:
- Any failing test
- Missing output
- Untested feature

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 4 — CI ENFORCEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Goal:
Automated enforcement.

Actions:
- Update workflow
- Install dependencies
- Install pytest
- Run pytest -q
- Enable pip cache
- Add cron watchdog
- Document health strategy

Hard Stop:
- CI does not execute pytest
- CI passes with failing tests

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FINAL VALIDATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Re-open FEATURE_MATRIX.md.

For EACH feature:
- Confirm implementation
- Confirm DB usage
- Confirm test coverage

Output verification checklist.

If ANY feature not VERIFIED:
Return to implementation.
Repeat Phase 3.
Re-run validation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEFINITION OF DONE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Rewrite is complete ONLY if:

- All phases executed
- Phase 1B executed after analysis
- Legacy archived
- Modular architecture enforced
- No DB modifications
- All tests written
- pytest passed
- Full output displayed
- CI runs pytest
- Feature matrix fully validated

Anything less = NOT COMPLETE.
