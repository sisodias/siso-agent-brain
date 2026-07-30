# SISO Agent Brain

SISO Agent Brain is the shared state service for an agent operating stack: task lifecycle and queues, versioned task artifacts, memories, timeline, fleet heartbeats, costs, human questions, divisions, delegation inboxes, control flags, and governed units.

It is **not** Agent Zero, Session Intelligence, Foundry, a scheduler, a model router, or a secrets manager. Those systems use the Brain through its API and keep independent source and release lifecycles.

## Run it

```bash
./install.sh

mkdir -p ~/.config/siso/brain-tokens
openssl rand -hex 32 > ~/.config/siso/brain-tokens/read.token
openssl rand -hex 32 > ~/.config/siso/brain-tokens/write.token
openssl rand -hex 32 > ~/.config/siso/brain-tokens/spawn.token

siso-brain-server
siso-brain health
SISO_BRAIN_TOKEN="$(cat ~/.config/siso/brain-tokens/write.token)" siso-brain heartbeat --id local-agent

siso-brain task-create --id TASK-001 --description "Map the task system" --agent local-agent --urgency 80
siso-brain step-add --task TASK-001 --name implement --role builder --order 1
siso-brain step-claim --role builder --by local-agent
siso-brain step-update --id <claimed-step-id> --status done
```

The server binds to `127.0.0.1:8830`, creates `~/.local/share/siso-agent-brain/brain.db`, and applies immutable migrations. Override those with `SISO_BRAIN_BIND`, `SISO_BRAIN_PORT`, and `SISO_DB`.

The human dashboard is disabled by default because it renders coordination data. The Great Library provides the public documentation page; enable the private runtime face only with `SISO_BRAIN_FACE_ENABLED=1` on a trusted interface.

## Contracts

- Read, write, and spawn tokens form an ordered authorization hierarchy.
- The SQLite file has one service writer; clients never open it directly.
- Task claims use an immediate write transaction, so two workers cannot receive the same pending step.
- Unreachable writes enter a configurable local outbox and can be replayed with `siso-brain drain`.
- Migrations are immutable and digest-checked.
- Database union is dry-run by default and allowlists only durable tables.
- Legacy task-state import is dry-run by default, profile-detected, field-allowlisted, and requires explicit flags for memory or timeline content.
- Uninstall removes package code and executable links, never the database, tokens, or outbox.

## Migrate reviewed legacy task state

Stop the Brain service, migrate an empty target database, and dry-run first:

```bash
scripts/migrate.py --database ./brain-target.db
tools/import_legacy_tasks.py --source ./legacy.db --target ./brain-target.db
tools/import_legacy_tasks.py --source ./legacy.db --target ./brain-target.db --apply
```

The importer recognizes the reviewed OS Database and Task Manager layouts. It imports task truth plus compatible steps/artifacts; it never imports raw SQL, sessions, tool permissions, project hierarchy, automations, or private file-path artifacts. Memory and timeline content require `--include-memory` and `--include-timeline` because those records may contain sensitive material.

Read [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html), [`docs/TASK-STATE-MIGRATION.html`](docs/TASK-STATE-MIGRATION.html), [`MIGRATION-MAP.json`](MIGRATION-MAP.json), and [`LEGACY-TASK-STATE-ASSESSMENT.json`](LEGACY-TASK-STATE-ASSESSMENT.json). Run `npm test` before publishing.
