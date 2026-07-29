# SISO Agent Brain

SISO Agent Brain is the shared state service for an agent operating stack: tasks, memories, timeline, fleet heartbeats, costs, human questions, divisions, delegation inboxes, control flags, and governed units.

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
```

The server binds to `127.0.0.1:8830`, creates `~/.local/share/siso-agent-brain/brain.db`, and applies immutable migrations. Override those with `SISO_BRAIN_BIND`, `SISO_BRAIN_PORT`, and `SISO_DB`.

The human dashboard is disabled by default because it renders coordination data. The Great Library provides the public documentation page; enable the private runtime face only with `SISO_BRAIN_FACE_ENABLED=1` on a trusted interface.

## Contracts

- Read, write, and spawn tokens form an ordered authorization hierarchy.
- The SQLite file has one service writer; clients never open it directly.
- Unreachable writes enter a configurable local outbox and can be replayed with `siso-brain drain`.
- Migrations are immutable and digest-checked.
- Database union is dry-run by default and allowlists only durable tables.
- Uninstall removes package code and executable links, never the database, tokens, or outbox.

Read [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) and [`MIGRATION-MAP.json`](MIGRATION-MAP.json). Run `npm test` before publishing.
