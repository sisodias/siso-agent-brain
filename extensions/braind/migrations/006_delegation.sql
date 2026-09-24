-- 006_delegation.sql — three-tier delegation: system-wide agent-zero -> project-zeros.
-- The division_inbox is the brain-backed channel: agent-zero writes intents DOWN to a
-- division's zero; the division writes status UP. Survives restarts, works cross-machine.
-- Idempotent. Bumps schema_version to 6.

CREATE TABLE IF NOT EXISTS division_inbox (
    id          TEXT PRIMARY KEY,
    division    TEXT NOT NULL,           -- which division this is for (FK-ish to divisions.id)
    direction   TEXT NOT NULL,           -- 'down' (intent from agent-zero) | 'up' (status from division)
    kind        TEXT DEFAULT 'intent',   -- intent | status | result | question
    body        TEXT NOT NULL,
    from_agent  TEXT,                     -- 'agent-zero' or '<division>-zero'
    status      TEXT DEFAULT 'open',      -- open | acked | done
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_dinbox_div ON division_inbox(division, direction, status, created_at);

-- track each division's plan-holder ("<project>-zero") + liveness, on top of divisions.
ALTER TABLE divisions ADD COLUMN zero_agent TEXT;          -- e.g. 'oracle-zero'
ALTER TABLE divisions ADD COLUMN zero_status TEXT DEFAULT 'asleep';  -- asleep | waking | active
ALTER TABLE divisions ADD COLUMN last_intent_at DATETIME;

INSERT OR IGNORE INTO schema_version(version, note)
    VALUES (6, 'delegation: division_inbox + divisions.zero_agent/zero_status (3-tier)');
