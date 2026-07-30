CREATE TABLE IF NOT EXISTS task_steps (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    step_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','in_progress','retry','done','error','cancelled')),
    assigned_role TEXT,
    step_order INTEGER NOT NULL DEFAULT 0,
    input_payload TEXT,
    output_payload TEXT,
    error_log TEXT,
    claimed_by TEXT,
    claimed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(task_id) REFERENCES tasks(id)
);
CREATE INDEX IF NOT EXISTS idx_task_steps_queue
    ON task_steps(assigned_role, status, step_order);
CREATE INDEX IF NOT EXISTS idx_task_steps_task
    ON task_steps(task_id, step_order);

CREATE TABLE IF NOT EXISTS task_artifacts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    step_id TEXT,
    artifact_type TEXT NOT NULL,
    content TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(task_id) REFERENCES tasks(id),
    FOREIGN KEY(step_id) REFERENCES task_steps(id),
    UNIQUE(task_id, artifact_type, version)
);
CREATE INDEX IF NOT EXISTS idx_task_artifacts_latest
    ON task_artifacts(task_id, artifact_type, version DESC);
