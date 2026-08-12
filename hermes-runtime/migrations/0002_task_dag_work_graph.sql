ALTER TABLE tasks
    DROP CONSTRAINT IF EXISTS tasks_state_check;
ALTER TABLE tasks
    ADD CONSTRAINT tasks_state_check CHECK (
        state IN (
            'NEW', 'READY', 'ASSIGNED', 'RUNNING', 'COMPLETION_CLAIMED',
            'WAITING', 'VERIFYING', 'PASSED', 'FAILED', 'RETRYING',
            'BLOCKED', 'CANCELLED', 'SUPERSEDED'
        )
    );

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS task_type TEXT;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS created_by_graph_command_id TEXT
    REFERENCES command_receipts(command_id);
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS source_feedback_event_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS tasks_source_feedback_event_unique
    ON tasks(source_feedback_event_id)
    WHERE source_feedback_event_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS tasks_project_task_unique
    ON tasks(project_id, task_id);

CREATE TABLE IF NOT EXISTS project_graph_versions (
    project_id TEXT PRIMARY KEY,
    graph_version BIGINT NOT NULL DEFAULT 0 CHECK (graph_version >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    project_id TEXT NOT NULL REFERENCES project_graph_versions(project_id),
    task_id TEXT NOT NULL,
    depends_on_task_id TEXT NOT NULL,
    created_by_command_id TEXT NOT NULL REFERENCES command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, task_id, depends_on_task_id),
    CHECK (task_id <> depends_on_task_id),
    FOREIGN KEY (project_id, task_id)
        REFERENCES tasks(project_id, task_id),
    FOREIGN KEY (project_id, depends_on_task_id)
        REFERENCES tasks(project_id, task_id)
);

CREATE TABLE IF NOT EXISTS work_graph_edges (
    edge_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project_graph_versions(project_id),
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    created_by_command_id TEXT NOT NULL REFERENCES command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (
        project_id, source_type, source_id, edge_type, target_type, target_id
    ),
    CHECK (
        edge_type <> 'DEPENDS_ON'
        OR (source_type = 'Task' AND target_type = 'Task' AND source_id <> target_id)
    )
);

CREATE TABLE IF NOT EXISTS feedback_records (
    feedback_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project_graph_versions(project_id),
    source_event_id TEXT NOT NULL UNIQUE REFERENCES event_log(event_id),
    source_task_id TEXT NOT NULL REFERENCES tasks(task_id),
    verification_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    repair_task_id TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE task_dependencies IS
'Authoritative scheduling-only Task DAG edges. Every patch is cycle-checked.';
COMMENT ON TABLE work_graph_edges IS
'Typed provenance graph. Only DEPENDS_ON rows also participate in Task DAG semantics.';
