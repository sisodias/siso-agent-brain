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
