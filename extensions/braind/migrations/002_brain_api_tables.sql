-- 002_brain_api_tables.sql — tables the brain-API needs that aren't in the base schema.
-- Idempotent: safe to re-run. Applied by deploy.sh which records it in schema_version.

CREATE TABLE IF NOT EXISTS cost_events (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT,
    run_id      TEXT,
    cli         TEXT,            -- 'claude' | 'codex' | 'minimax' ...
    model       TEXT,
    tokens_in   INTEGER DEFAULT 0,
    tokens_out  INTEGER DEFAULT 0,
    est_usd     REAL    DEFAULT 0.0,
    ts          DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cost_events_ts ON cost_events(ts);
CREATE INDEX IF NOT EXISTS idx_cost_events_agent ON cost_events(agent_id);

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    note        TEXT
);
INSERT OR IGNORE INTO schema_version(version, note)
    VALUES (2, 'brain-api: cost_events + schema_version');
