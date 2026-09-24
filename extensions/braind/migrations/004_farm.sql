-- 004_farm.sql — self-improving Farm: harvested candidates + human-gate verdicts.
-- Idempotent. Bumps schema_version to 4.

CREATE TABLE IF NOT EXISTS farm_candidates (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,          -- 'github-topics' | 'youtube' | ...
    name        TEXT NOT NULL,
    url         TEXT,
    summary     TEXT,
    signal      TEXT,                   -- why it surfaced (stars, recency, match)
    fit_score   REAL DEFAULT 0.0,       -- 0..1 stack-fit (scorer)
    verdict     TEXT DEFAULT 'new',     -- new | proposed | adopt | wrap | build | reject
    decided_by  TEXT,                   -- 'shaan' | 'agent-zero' (human gate)
    harvested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    decided_at  DATETIME
);
CREATE INDEX IF NOT EXISTS idx_farm_verdict ON farm_candidates(verdict, fit_score);
CREATE UNIQUE INDEX IF NOT EXISTS idx_farm_url ON farm_candidates(url);

INSERT OR IGNORE INTO schema_version(version, note)
    VALUES (4, 'farm: farm_candidates (harvest -> score -> human-gate)');
