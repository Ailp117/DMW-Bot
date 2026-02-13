# AGENTS.md — Discord Bot Rewrite Rules (Binding)

Codex: These rules are binding for EVERY step you take in this repo.

## Goal
Complete a full rewrite-from-scratch of the Discord bot with 100% feature parity and the existing DB schema unchanged. The work is not done until all checks pass and code is shipped (not just documentation).

## Non-negotiables
- Do NOT stop after listing required inputs. Continue using the provided inputs.
- Do NOT "only update README/DELIVERY_REPORT". The primary deliverable is working code.
- DB schema must remain unchanged. No renames. No new columns/constraints unless explicitly requested.
- If any info is missing, ask targeted questions, then immediately continue implementation once answered.

## Must-run commands (always)
- `pip install -r requirements.txt`
- `pytest -q`

## Proof requirement
In your final response, include:
- command list executed
- full `pytest -q` output (copied)
- checklist of Definition of Done marked complete

## Iteration loop
If tests fail:
1) fix code
2) rerun `pytest -q`
3) repeat until green

## Deliverables
- Full project tree
- Full code for all changed/new files
- Updated `.github/workflows/bot.yml` aligned with the new codebase
- README with setup + GH Actions + uptime strategy + troubleshooting
- Tests included and passing
