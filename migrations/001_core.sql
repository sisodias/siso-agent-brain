CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    parent_task_id TEXT,
    blocked_by_task_id TEXT,
    assigned_agent_id TEXT,
    created_by_agent_id TEXT,
    title TEXT,
    description TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    workspace_path TEXT,
    executive_summary TEXT,
    tokens_burned INTEGER DEFAULT 0,
    started_at DATETIME,
    completed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    project_id TEXT,
    priority TEXT DEFAULT 'medium',
    due_date DATETIME,
    time_spent INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    urgency_score INTEGER DEFAULT 0,
    tags TEXT DEFAULT '',
    archived_at DATETIME,
    estimated_minutes INTEGER DEFAULT 0,
    created_by_user TEXT,
    created_by_session TEXT,
    source_tool TEXT DEFAULT 'manual',
    source_todo_id TEXT,
    cli_instance_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_agent_status ON tasks(assigned_agent_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    agent_id TEXT,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    tier TEXT DEFAULT 'episodic',
    confidence REAL DEFAULT 0.6,
    distilled INTEGER DEFAULT 0,
    expires_at DATETIME,
    access_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_memories_recall ON memories(confidence DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS timeline_events (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    agent_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('BOOT','THOUGHT','ACTION','TOOL_CALL','ERROR','HANDOFF','COMPLETED','USER_PROMPT')),
    message TEXT,
    metadata TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    root_task_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_timeline_timestamp ON timeline_events(timestamp DESC);

CREATE TABLE IF NOT EXISTS cli_instances (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    machine TEXT,
    cwd TEXT NOT NULL,
    status TEXT DEFAULT 'idle' CHECK(status IN ('running','idle','stopped','crashed')),
    last_heartbeat DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_session_id TEXT,
    token_budget INTEGER DEFAULT 1000000,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_cli_instances_status ON cli_instances(status);
CREATE INDEX IF NOT EXISTS idx_cli_instances_heartbeat ON cli_instances(last_heartbeat);

CREATE TABLE IF NOT EXISTS cost_events (
    id TEXT PRIMARY KEY,
    agent_id TEXT,
    run_id TEXT,
    cli TEXT,
    model TEXT,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    est_usd REAL DEFAULT 0.0,
    ts DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cost_events_ts ON cost_events(ts);
