-- 005_divisions.sql — register projects as DIVISIONS under the one brain (fractal topology).
-- A division = a project/business the agent fleet works in. agent-zero sees divisions;
-- orchestrators/workers belong to one. Idempotent. Bumps schema_version to 5.

CREATE TABLE IF NOT EXISTS divisions (
    id          TEXT PRIMARY KEY,       -- short slug, e.g. 'oracle-streaming'
    name        TEXT NOT NULL,
    repo_path   TEXT,                   -- where the project lives (in-place, not moved)
    orchestrator TEXT,                  -- the orchestrator agent id for this division (optional)
    status      TEXT DEFAULT 'active',  -- active | paused | archived
    notes       TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_version(version, note)
    VALUES (5, 'coherence: divisions (projects as divisions in the fractal)');
