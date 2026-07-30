# Provenance

This repository is a clean SISO-owned extraction from `$SISO_WORKSPACE/SISO_Agent_Base/extensions/braind/`, observed 2026-07-30. The dirty warehouse remains untouched.

Promoted and refactored:

- `braind.py` → `src/server.py`: retained shared-state HTTP behavior; removed Session Intelligence, voice, and Foundry routes; made bind, data, token, and dashboard policy portable.
- `siso-brain` → `bin/siso-brain`: removed a personal host default, repaired the human-question command distinction, added missing governance commands, and made URL, tokens, timeouts, and outbox explicit.
- migrations `002`–`007` → two clean bootstrap migrations: added the missing base schema and repaired the non-idempotent/incompatible unit and division evolution.
- `spine_merge.py` → `tools/spine_merge.py`: replaced a warehouse-wide exclusion list with an explicit Agent Brain durable-table allowlist.

Reclassified rather than copied:

- query intent/session extracts → SISO Session Intelligence;
- harvest queue and farm worker → SISO Foundry;
- scheduler runner and self-build automation → future Agent Automation Work;
- model-key rotation and fair-share proxy → Agent Integrations / model infrastructure;
- system doctor and service probes → SISO Agent Runtime operations;
- launchd and cross-host shipping recipes → future deployment/operator pack.

Compared and decomposed after direct review of the Skills Hub task/state folders:

- `task-manager` task lifecycle, role queue, and versioned artifacts → Agent Brain migration `003_task_workflow.sql` and authorized API/client commands;
- `task-manager` raw SQL and duplicate session, permission, memory, and execution-log ownership → retired or mapped to existing contracts;
- `pm-tasks` → scheduled for retirement after the thin Agent Brain adapter replaces it;
- `os-database` → capability-by-capability homes recorded in `LEGACY-TASK-STATE-ASSESSMENT.json`; the mixed folder is not promoted as a repository.

No runtime database or private machine state was copied. The legacy source remains preserved until compatibility and data-migration receipts are complete.
