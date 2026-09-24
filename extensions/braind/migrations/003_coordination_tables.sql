-- 003_coordination_tables.sql — brain coordination + control primitives.
-- Idempotent. Applied by deploy; bumps schema_version to 3.

-- Notifications back to Shaan (the missing "talk to me" channel).
CREATE TABLE IF NOT EXISTS notifications (
    id          TEXT PRIMARY KEY,
    urgency     TEXT DEFAULT 'normal',     -- low | normal | high | urgent
    summary     TEXT NOT NULL,
    body        TEXT,
    from_agent  TEXT,
    needs_answer INTEGER DEFAULT 0,
    answered    INTEGER DEFAULT 0,
    seen        INTEGER DEFAULT 0,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_notif_unseen ON notifications(seen, created_at);

-- Async ask -> answer loop: an agent parks a question; Shaan answers; the agent resumes.
CREATE TABLE IF NOT EXISTS pending_questions (
    id          TEXT PRIMARY KEY,
    from_agent  TEXT,
    question    TEXT NOT NULL,
    options     TEXT,                       -- JSON array of choices (optional)
    blocking_task_id TEXT,
    status      TEXT DEFAULT 'awaiting',    -- awaiting | answered | cancelled
    answer      TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    answered_at DATETIME
);
CREATE INDEX IF NOT EXISTS idx_pq_awaiting ON pending_questions(status, created_at);

-- Global / per-division control flags (kill-switch, pause).
CREATE TABLE IF NOT EXISTS control_flags (
    scope       TEXT PRIMARY KEY,           -- 'global' or a division name
    paused      INTEGER DEFAULT 0,
    reason      TEXT,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Scheduler: fire brain verbs / commands on a cadence (farm, digests, proactive agent-zero).
CREATE TABLE IF NOT EXISTS scheduled_triggers (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    schedule    TEXT NOT NULL,              -- cron-ish or interval spec (interpreted by the runner)
    command     TEXT NOT NULL,              -- shell command / brain verb to run
    enabled     INTEGER DEFAULT 1,
    last_run    DATETIME,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_version(version, note)
    VALUES (3, 'coordination: notifications, pending_questions, control_flags, scheduled_triggers');
