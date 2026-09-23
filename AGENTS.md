# Agent guide

**In one line:** Shared state service for the agent stack, owning task lifecycle, artifacts, memories, timeline, fleet heartbeats, costs and human questions. District: `SISO_Agents` (`~/SISO_Workspace/SISO_Agents/siso-agent-brain`).

This repository owns shared state, its API/client contract, schema migrations, and conservative data portability.

- Keep Agent Zero identity and coordination policy outside this repository.
- Keep session mining/ranking, Foundry discovery, schedulers, model routing, and host deployment outside the core.
- Never add credentials, personal endpoints, personal paths, runtime databases, token files, outboxes, or logs to Git.
- Public health output must not disclose database paths or coordination records.
- The dashboard stays disabled by default; the server stays loopback-bound by default.
- Applied migration contents are immutable. Add a new numbered migration instead of editing one.
- Data merge remains dry-run by default and explicit-table allowlisted.
- Legacy import remains dry-run by default; memory and timeline content are opt-in and private file paths never copy.
- Uninstall never deletes runtime state.
- Run `npm test` before publication.
