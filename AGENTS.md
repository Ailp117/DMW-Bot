# AGENTS.md — Discord Bot Rewrite Execution Rules (Binding)

These rules are binding for every step taken in this repository.

######################################################################
# PRIMARY GOAL
######################################################################

Perform a complete rewrite-from-scratch of the Discord bot
with 100% feature parity and the existing database schema unchanged.

The task is NOT documentation.
The task is NOT a report.
The task is WORKING, TESTED, CI-READY SOURCE CODE.

######################################################################
# NON-NEGOTIABLE RULES
######################################################################

1. Do NOT stop after listing required inputs.
2. Do NOT only edit README.md or DELIVERY_REPORT.md.
3. Primary deliverable is WORKING SOURCE CODE.
4. Database schema must remain unchanged.
5. No renaming tables, columns, constraints.
6. No adding constraints unless explicitly requested.
7. If information is missing:
   - Ask specifically what is missing.
   - After receiving it, immediately continue implementation.

######################################################################
# ANTI-REPORT RULE
######################################################################

You are not allowed to complete this task by only:

- editing README.md
- editing DELIVERY_REPORT.md
- updating bot.yml
- summarizing actions

If core application files (main.py, commands/, views/, services/, repositories/, db/, etc.)
are not created or modified, the task is incomplete.

######################################################################
# EXECUTION LOOP
######################################################################

If tests fail:

1. Fix the code.
2. Rerun `pytest -q`.
3. Repeat until all tests pass.

Never declare completion while tests are failing.

######################################################################
# REQUIRED COMMANDS
######################################################################

You must execute and show output for:

pip install -r requirements.txt
pytest -q

The full pytest output must be displayed.

######################################################################
# EXECUTION ENFORCEMENT
######################################################################

Before declaring completion, verify:

- At least one core application file changed
- tests/ directory exists with real test cases
- pytest output is shown
- GitHub Actions workflow runs pytest
- No interaction response errors remain
- Persistent views work
- Feature parity verified

If any condition is false → continue working.

######################################################################
# DEFINITION OF DONE
######################################################################

The task is complete only if:

[ ] Feature Matrix created  
[ ] Rewrite complete  
[ ] DB schema unchanged  
[ ] Persistent views restored  
[ ] Voting logic preserved  
[ ] Cleanup logic preserved  
[ ] No interaction double responses  
[ ] Tests green  
[ ] CI workflow aligned  
[ ] README complete  
[ ] Full pytest output shown  

If any box unchecked → continue implementation.
