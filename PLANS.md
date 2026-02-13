# PLANS.md — Long-running execution plan

## Phase 1 — Inventory
- Enumerate existing commands, views, DB tables, workflow steps
- Produce Feature Matrix: Feature → files → DB tables → expected behavior → tests

## Phase 2 — Implementation
- Rebuild modular structure (services/repositories/views/commands)
- Keep behavior 1:1
- Keep DB schema unchanged

## Phase 3 — Tests
- Unit tests for business logic
- Async tests with mocks
- DB repository tests

## Phase 4 — CI
- Update `.github/workflows/bot.yml` to run tests and use restart strategy for near-24/7
- Ensure workflow fails on failing tests

## Stop condition
Not done until pytest is green and CI workflow is consistent with repo structure.
