CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    urgency TEXT DEFAULT 'normal',
    summary TEXT NOT NULL,
    body TEXT,
    from_agent TEXT,
    needs_answer INTEGER DEFAULT 0,
    answered INTEGER DEFAULT 0,
    seen INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_notifications_unseen ON notifications(seen, created_at);

CREATE TABLE IF NOT EXISTS pending_questions (
    id TEXT PRIMARY KEY,
    from_agent TEXT,
    question TEXT NOT NULL,
    options TEXT,
    blocking_task_id TEXT,
    status TEXT DEFAULT 'awaiting',
    answer TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    answered_at DATETIME
);
CREATE INDEX IF NOT EXISTS idx_questions_status ON pending_questions(status, created_at);

CREATE TABLE IF NOT EXISTS control_flags (
    scope TEXT PRIMARY KEY,
    paused INTEGER DEFAULT 0,
    reason TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS divisions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    repo_path TEXT,
    orchestrator TEXT,
    status TEXT DEFAULT 'active',
    notes TEXT,
    zero_agent TEXT,
    zero_status TEXT DEFAULT 'asleep',
    last_intent_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS division_inbox (
    id TEXT PRIMARY KEY,
    division TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('down','up')),
    kind TEXT DEFAULT 'intent',
    body TEXT NOT NULL,
    from_agent TEXT,
    status TEXT DEFAULT 'open',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_division_inbox ON division_inbox(division, direction, status, created_at);

CREATE TABLE IF NOT EXISTS units (
    id TEXT PRIMARY KEY,
    kind TEXT,
    tier TEXT DEFAULT 'capability',
    provenance TEXT,
    challenge_hook TEXT,
    rating REAL,
    clean_streak INTEGER DEFAULT 0,
    regressions INTEGER DEFAULT 0,
    circuit_open INTEGER DEFAULT 0,
    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_units_tier ON units(tier);

CREATE TABLE IF NOT EXISTS challenges (
    id TEXT PRIMARY KEY,
    target TEXT NOT NULL,
    challenger TEXT,
    argument TEXT NOT NULL,
    rating INTEGER,
    verdict TEXT DEFAULT 'open',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
