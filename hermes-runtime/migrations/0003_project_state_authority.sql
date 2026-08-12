CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN (
            'CREATED', 'INTAKE', 'DISCOVERY', 'PLANNING', 'DESIGNING',
            'IMPLEMENTING', 'VERIFYING', 'HARDENING', 'PACKAGING',
            'DELIVERING', 'ACCEPTED', 'WAITING_FOR_HUMAN',
            'WAITING_FOR_RESOURCE', 'PAUSED', 'BLOCKED', 'RECOVERING',
            'FAILED', 'CANCELLED'
        )
    ),
    version BIGINT NOT NULL CHECK (version >= 0),
    resume_state TEXT,
    last_command_id TEXT NOT NULL REFERENCES command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (state = 'PAUSED' AND resume_state IS NOT NULL)
        OR (state <> 'PAUSED' AND resume_state IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS project_transition_records (
    transition_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    command_id TEXT NOT NULL UNIQUE REFERENCES command_receipts(command_id),
    previous_state TEXT,
    new_state TEXT NOT NULL,
    project_version BIGINT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    requested_by_type TEXT NOT NULL,
    requested_by_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    authorization_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, project_version)
);

CREATE OR REPLACE FUNCTION hermes_create_project_authority(
    p_project_id TEXT,
    p_title TEXT,
    p_command_id TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_requested_by_type TEXT,
    p_requested_by_id TEXT,
    p_reason TEXT
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF p_actor_type <> 'control_plane' THEN
        RAISE EXCEPTION 'CONTROL_PLANE_AUTHORITY_REQUIRED';
    END IF;
    IF NULLIF(btrim(p_title), '') IS NULL OR NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'INVALID_PROJECT_COMMAND';
    END IF;
    IF p_requested_by_type NOT IN ('user', 'main_hermes', 'control_plane') THEN
        RAISE EXCEPTION 'PROJECT_REQUESTER_NOT_AUTHORIZED';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM command_receipts
        WHERE command_id = p_command_id
          AND project_id = p_project_id
          AND command_type = 'project.create'
          AND status = 'PROCESSING'
    ) THEN
        RAISE EXCEPTION 'PROJECT_COMMAND_SEMANTICS_MISMATCH';
    END IF;
    INSERT INTO projects
      (project_id, title, state, version, last_command_id)
    VALUES (p_project_id, p_title, 'CREATED', 0, p_command_id);
    INSERT INTO project_graph_versions (project_id, graph_version)
    VALUES (p_project_id, 0);
    INSERT INTO project_transition_records
      (transition_id, project_id, command_id, previous_state, new_state,
       project_version, actor_type, actor_id, requested_by_type,
       requested_by_id, reason)
    VALUES ('ptr-' || gen_random_uuid()::text, p_project_id, p_command_id,
            NULL, 'CREATED', 0, p_actor_type, p_actor_id,
            p_requested_by_type, p_requested_by_id, p_reason);
END;
$$;

CREATE OR REPLACE FUNCTION hermes_transition_project_authority(
    p_project_id TEXT,
    p_expected_version BIGINT,
    p_expected_state TEXT,
    p_new_state TEXT,
    p_resume_state TEXT,
    p_command_id TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_requested_by_type TEXT,
    p_requested_by_id TEXT,
    p_reason TEXT,
    p_authorization_ref TEXT
) RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    next_version BIGINT;
    stored_resume_state TEXT;
    stored_command_type TEXT;
BEGIN
    IF p_actor_type <> 'control_plane' THEN
        RAISE EXCEPTION 'CONTROL_PLANE_AUTHORITY_REQUIRED';
    END IF;
    IF NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'COMMAND_REASON_REQUIRED';
    END IF;
    SELECT command_type INTO stored_command_type
    FROM command_receipts
    WHERE command_id = p_command_id
      AND project_id = p_project_id
      AND status = 'PROCESSING';
    IF stored_command_type IS DISTINCT FROM (CASE
        WHEN p_new_state = 'CANCELLED' THEN 'project.cancel'
        WHEN p_new_state = 'PAUSED' THEN 'project.pause'
        WHEN p_expected_state = 'PAUSED' THEN 'project.resume'
        ELSE 'project.request_transition'
    END) THEN
        RAISE EXCEPTION 'PROJECT_COMMAND_SEMANTICS_MISMATCH';
    END IF;
    SELECT resume_state INTO stored_resume_state
    FROM projects
    WHERE project_id = p_project_id
      AND version = p_expected_version
      AND state = p_expected_state
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PROJECT_AUTHORITY_PRECONDITION_FAILED';
    END IF;
    IF p_expected_state IN ('ACCEPTED', 'FAILED', 'CANCELLED') THEN
        RAISE EXCEPTION 'PROJECT_TERMINAL';
    END IF;
    IF p_new_state = 'CANCELLED' THEN
        IF p_requested_by_type NOT IN ('user', 'system_operator')
          OR NULLIF(btrim(p_authorization_ref), '') IS NULL THEN
            RAISE EXCEPTION 'CANCELLATION_AUTHORIZATION_REQUIRED';
        END IF;
    ELSIF p_new_state = 'PAUSED' THEN
        IF p_expected_state NOT IN (
            'CREATED', 'INTAKE', 'DISCOVERY', 'PLANNING', 'DESIGNING',
            'IMPLEMENTING', 'VERIFYING', 'HARDENING', 'PACKAGING', 'DELIVERING'
        ) OR p_resume_state IS DISTINCT FROM p_expected_state
          OR p_requested_by_type NOT IN (
              'user', 'main_hermes', 'control_plane',
              'recovery_controller', 'system_operator'
          ) THEN
            RAISE EXCEPTION 'ILLEGAL_PROJECT_PAUSE';
        END IF;
    ELSIF p_expected_state = 'PAUSED' THEN
        IF p_new_state IS DISTINCT FROM stored_resume_state
          OR p_resume_state IS NOT NULL
          OR p_requested_by_type NOT IN (
              'user', 'main_hermes', 'control_plane',
              'recovery_controller', 'system_operator'
          ) THEN
            RAISE EXCEPTION 'ILLEGAL_PROJECT_RESUME';
        END IF;
    ELSIF NOT (
        (p_expected_state = 'CREATED' AND p_new_state = 'INTAKE') OR
        (p_expected_state = 'INTAKE' AND p_new_state = 'DISCOVERY') OR
        (p_expected_state = 'DISCOVERY' AND p_new_state = 'PLANNING') OR
        (p_expected_state = 'PLANNING' AND p_new_state = 'DESIGNING') OR
        (p_expected_state = 'DESIGNING' AND p_new_state = 'IMPLEMENTING') OR
        (p_expected_state = 'IMPLEMENTING' AND p_new_state = 'VERIFYING') OR
        (p_expected_state = 'VERIFYING' AND p_new_state = 'HARDENING') OR
        (p_expected_state = 'HARDENING' AND p_new_state = 'PACKAGING') OR
        (p_expected_state = 'PACKAGING' AND p_new_state = 'DELIVERING') OR
        (p_expected_state = 'DELIVERING' AND p_new_state = 'ACCEPTED')
    ) OR p_requested_by_type NOT IN (
        'user', 'main_hermes', 'control_plane', 'recovery_controller'
    ) THEN
        RAISE EXCEPTION 'ILLEGAL_PROJECT_TRANSITION';
    END IF;
    IF p_expected_state = 'VERIFYING' AND p_new_state = 'HARDENING' THEN
        PERFORM task_id FROM tasks
        WHERE project_id = p_project_id
        ORDER BY task_id
        FOR SHARE;
        IF NOT EXISTS (
            SELECT 1 FROM tasks t
            WHERE t.project_id = p_project_id
        ) OR EXISTS (
            SELECT 1 FROM tasks t
            LEFT JOIN verification_results v
              ON v.verification_id = t.current_verification_id
             AND v.task_id = t.task_id
             AND v.artifact_id = t.current_artifact_id
             AND v.artifact_hash = t.current_artifact_hash
             AND v.verdict = 'PASS'
            WHERE t.project_id = p_project_id
              AND (t.state <> 'PASSED' OR v.verification_id IS NULL)
        ) THEN
            RAISE EXCEPTION 'REQUIRED_TASKS_NOT_PASSED';
        END IF;
    END IF;
    next_version := p_expected_version + 1;
    UPDATE projects
    SET state = p_new_state,
        version = next_version,
        resume_state = p_resume_state,
        last_command_id = p_command_id,
        updated_at = now()
    WHERE project_id = p_project_id
      AND version = p_expected_version
      AND state = p_expected_state;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PROJECT_AUTHORITY_PRECONDITION_FAILED';
    END IF;
    INSERT INTO project_transition_records
      (transition_id, project_id, command_id, previous_state, new_state,
       project_version, actor_type, actor_id, requested_by_type,
       requested_by_id, reason, authorization_ref)
    VALUES ('ptr-' || gen_random_uuid()::text, p_project_id, p_command_id,
            p_expected_state, p_new_state, next_version, p_actor_type,
            p_actor_id, p_requested_by_type, p_requested_by_id, p_reason,
            NULLIF(p_authorization_ref, ''));
    RETURN next_version;
END;
$$;

CREATE OR REPLACE FUNCTION hermes_project_event_invariant()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM event_log e
        JOIN outbox_messages o ON o.event_id = e.event_id
        WHERE e.command_id = NEW.last_command_id
          AND e.project_id = NEW.project_id
          AND e.event_type IN (
              'project.created', 'project.state_transition.applied',
              'project.paused', 'project.resumed', 'project.cancelled'
          )
          AND (e.payload ->> 'project_version')::BIGINT = NEW.version
          AND e.payload ->> 'new_state' = NEW.state
    ) THEN
        RAISE EXCEPTION 'PROJECT_STATE_EVENT_INVARIANT_VIOLATION';
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS projects_require_event ON projects;
CREATE CONSTRAINT TRIGGER projects_require_event
AFTER INSERT OR UPDATE OF state, version ON projects
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION hermes_project_event_invariant();

DROP TRIGGER IF EXISTS project_transition_records_immutable ON project_transition_records;
CREATE TRIGGER project_transition_records_immutable
BEFORE UPDATE OR DELETE ON project_transition_records
FOR EACH ROW EXECUTE FUNCTION hermes_reject_immutable_change();

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_control_plane_runtime') THEN
        CREATE ROLE hermes_control_plane_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_worker_runtime') THEN
        CREATE ROLE hermes_worker_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_read_only_runtime') THEN
        CREATE ROLE hermes_read_only_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

REVOKE ALL ON projects, project_transition_records FROM PUBLIC;
REVOKE ALL ON FUNCTION hermes_create_project_authority(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION hermes_transition_project_authority(
    TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;

GRANT SELECT ON projects, project_transition_records, tasks
    TO hermes_control_plane_runtime;
GRANT SELECT, INSERT, UPDATE ON command_receipts
    TO hermes_control_plane_runtime;
GRANT SELECT, INSERT ON event_log, outbox_messages, audit_records
    TO hermes_control_plane_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public
    TO hermes_control_plane_runtime;
GRANT EXECUTE ON FUNCTION hermes_create_project_authority(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) TO hermes_control_plane_runtime;
GRANT EXECUTE ON FUNCTION hermes_transition_project_authority(
    TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) TO hermes_control_plane_runtime;

GRANT SELECT ON projects TO hermes_worker_runtime, hermes_read_only_runtime;
