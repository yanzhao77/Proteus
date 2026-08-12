DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_authority_owner') THEN
        CREATE ROLE hermes_authority_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM hermes_control_plane_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_worker_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_read_only_runtime;

CREATE TABLE IF NOT EXISTS project_evidence_facts (
    evidence_fact_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    project_version BIGINT NOT NULL CHECK (project_version >= 0),
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('VALID', 'INVALID')),
    authority TEXT NOT NULL CHECK (authority = 'verification_engine'),
    subject_ref TEXT NOT NULL,
    valid BOOLEAN NOT NULL DEFAULT true,
    invalidated_at TIMESTAMPTZ,
    superseded_by TEXT REFERENCES public.project_evidence_facts(evidence_fact_id),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((valid AND invalidated_at IS NULL) OR (NOT valid))
);

CREATE TABLE IF NOT EXISTS project_policy_decision_facts (
    policy_decision_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    project_version BIGINT NOT NULL CHECK (project_version >= 0),
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('ALLOW', 'DENY', 'REQUIRE_HUMAN')),
    authority TEXT NOT NULL CHECK (authority = 'policy_engine'),
    policy_bundle_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    valid BOOLEAN NOT NULL DEFAULT true,
    invalidated_at TIMESTAMPTZ,
    superseded_by TEXT REFERENCES public.project_policy_decision_facts(policy_decision_id),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((valid AND invalidated_at IS NULL) OR (NOT valid))
);

CREATE TABLE IF NOT EXISTS project_budget_facts (
    budget_fact_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    project_version BIGINT NOT NULL CHECK (project_version >= 0),
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('OK', 'HARD_STOP')),
    authority TEXT NOT NULL CHECK (authority = 'budget_engine'),
    budget_scope_id TEXT NOT NULL,
    version BIGINT NOT NULL CHECK (version >= 0),
    valid BOOLEAN NOT NULL DEFAULT true,
    invalidated_at TIMESTAMPTZ,
    superseded_by TEXT REFERENCES public.project_budget_facts(budget_fact_id),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((valid AND invalidated_at IS NULL) OR (NOT valid))
);

CREATE TABLE IF NOT EXISTS project_gate_decision_facts (
    gate_decision_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    project_version BIGINT NOT NULL CHECK (project_version >= 0),
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('OPEN', 'ANSWERED_NOT_APPLIED', 'ANSWERED_APPLIED')
    ),
    authority TEXT NOT NULL CHECK (authority = 'human_gate'),
    gate_id TEXT NOT NULL,
    decision_ref TEXT NOT NULL,
    valid BOOLEAN NOT NULL DEFAULT true,
    invalidated_at TIMESTAMPTZ,
    superseded_by TEXT REFERENCES public.project_gate_decision_facts(gate_decision_id),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((valid AND invalidated_at IS NULL) OR (NOT valid))
);

CREATE UNIQUE INDEX IF NOT EXISTS project_evidence_facts_one_current
    ON public.project_evidence_facts(project_id, project_version, from_state, to_state)
    WHERE valid AND superseded_by IS NULL AND expires_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS project_policy_facts_one_current
    ON public.project_policy_decision_facts(project_id, project_version, from_state, to_state)
    WHERE valid AND superseded_by IS NULL AND expires_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS project_budget_facts_one_current
    ON public.project_budget_facts(project_id, project_version, from_state, to_state)
    WHERE valid AND superseded_by IS NULL AND expires_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS project_gate_facts_one_current
    ON public.project_gate_decision_facts(project_id, project_version, from_state, to_state)
    WHERE valid AND superseded_by IS NULL AND expires_at IS NULL;

DROP FUNCTION IF EXISTS public.hermes_transition_project_authority(
    TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
);

CREATE OR REPLACE FUNCTION public.hermes_create_project_authority(
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
SET search_path = pg_catalog
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
        SELECT 1 FROM public.command_receipts
        WHERE command_id = p_command_id
          AND project_id = p_project_id
          AND command_type = 'project.create'
          AND status = 'PROCESSING'
    ) THEN
        RAISE EXCEPTION 'PROJECT_COMMAND_SEMANTICS_MISMATCH';
    END IF;
    INSERT INTO public.projects
      (project_id, title, state, version, last_command_id)
    VALUES (p_project_id, p_title, 'CREATED', 0, p_command_id);
    INSERT INTO public.project_graph_versions (project_id, graph_version)
    VALUES (p_project_id, 0);
    INSERT INTO public.project_transition_records
      (transition_id, project_id, command_id, previous_state, new_state,
       project_version, actor_type, actor_id, requested_by_type,
       requested_by_id, reason)
    VALUES ('ptr-' || pg_catalog.gen_random_uuid()::text, p_project_id, p_command_id,
            NULL, 'CREATED', 0, p_actor_type, p_actor_id,
            p_requested_by_type, p_requested_by_id, p_reason);
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_transition_project_authority(
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
    p_authorization_ref TEXT,
    p_evidence_fact_id TEXT,
    p_policy_decision_id TEXT,
    p_budget_fact_id TEXT,
    p_gate_decision_id TEXT
) RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    next_version BIGINT;
    stored_resume_state TEXT;
    stored_command_type TEXT;
    policy_result TEXT;
    requires_guard BOOLEAN;
    requires_tasks BOOLEAN;
BEGIN
    IF p_actor_type <> 'control_plane' THEN
        RAISE EXCEPTION 'CONTROL_PLANE_AUTHORITY_REQUIRED';
    END IF;
    IF NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'COMMAND_REASON_REQUIRED';
    END IF;
    SELECT command_type INTO stored_command_type
    FROM public.command_receipts
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
    FROM public.projects
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

    requires_guard := p_new_state <> 'CANCELLED';
    requires_tasks := p_expected_state = 'VERIFYING' AND p_new_state = 'HARDENING';

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

    IF requires_guard THEN
        IF p_evidence_fact_id IS NULL THEN
            RAISE EXCEPTION 'PROJECT_EVIDENCE_REQUIRED';
        END IF;
        PERFORM 1 FROM public.project_evidence_facts
        WHERE evidence_fact_id = p_evidence_fact_id
          AND project_id = p_project_id
          AND project_version = p_expected_version
          AND from_state = p_expected_state
          AND to_state = p_new_state
          AND authority = 'verification_engine'
          AND result = 'VALID'
          AND valid
          AND invalidated_at IS NULL
          AND superseded_by IS NULL
          AND (expires_at IS NULL OR expires_at > now())
        FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'PROJECT_EVIDENCE_INVALID';
        END IF;

        IF p_policy_decision_id IS NULL THEN
            RAISE EXCEPTION 'PROJECT_POLICY_DECISION_REQUIRED';
        END IF;
        SELECT result INTO policy_result
        FROM public.project_policy_decision_facts
        WHERE policy_decision_id = p_policy_decision_id
          AND project_id = p_project_id
          AND project_version = p_expected_version
          AND from_state = p_expected_state
          AND to_state = p_new_state
          AND authority = 'policy_engine'
          AND result IN ('ALLOW', 'REQUIRE_HUMAN')
          AND valid
          AND invalidated_at IS NULL
          AND superseded_by IS NULL
          AND (expires_at IS NULL OR expires_at > now())
        FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'PROJECT_POLICY_NOT_ALLOWED';
        END IF;

        IF p_budget_fact_id IS NULL THEN
            RAISE EXCEPTION 'PROJECT_BUDGET_FACT_REQUIRED';
        END IF;
        PERFORM 1 FROM public.project_budget_facts
        WHERE budget_fact_id = p_budget_fact_id
          AND project_id = p_project_id
          AND project_version = p_expected_version
          AND from_state = p_expected_state
          AND to_state = p_new_state
          AND authority = 'budget_engine'
          AND status = 'OK'
          AND valid
          AND invalidated_at IS NULL
          AND superseded_by IS NULL
          AND (expires_at IS NULL OR expires_at > now())
        FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'PROJECT_BUDGET_HARD_STOP';
        END IF;

        IF policy_result = 'REQUIRE_HUMAN' THEN
            IF p_gate_decision_id IS NULL THEN
                RAISE EXCEPTION 'PROJECT_GATE_DECISION_REQUIRED';
            END IF;
            PERFORM 1 FROM public.project_gate_decision_facts
            WHERE gate_decision_id = p_gate_decision_id
              AND project_id = p_project_id
              AND project_version = p_expected_version
              AND from_state = p_expected_state
              AND to_state = p_new_state
              AND authority = 'human_gate'
              AND status = 'ANSWERED_APPLIED'
              AND valid
              AND invalidated_at IS NULL
              AND superseded_by IS NULL
              AND (expires_at IS NULL OR expires_at > now())
            FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'PROJECT_GATE_NOT_APPLIED';
            END IF;
        END IF;
    END IF;

    IF requires_tasks THEN
        PERFORM task_id FROM public.tasks
        WHERE project_id = p_project_id
        ORDER BY task_id
        FOR SHARE;
        IF NOT EXISTS (
            SELECT 1 FROM public.tasks t
            WHERE t.project_id = p_project_id
        ) OR EXISTS (
            SELECT 1 FROM public.tasks t
            LEFT JOIN public.verification_results v
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
    UPDATE public.projects
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
    INSERT INTO public.project_transition_records
      (transition_id, project_id, command_id, previous_state, new_state,
       project_version, actor_type, actor_id, requested_by_type,
       requested_by_id, reason, authorization_ref)
    VALUES ('ptr-' || pg_catalog.gen_random_uuid()::text, p_project_id, p_command_id,
            p_expected_state, p_new_state, next_version, p_actor_type,
            p_actor_id, p_requested_by_type, p_requested_by_id, p_reason,
            NULLIF(p_authorization_ref, ''));
    RETURN next_version;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_project_event_invariant()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.event_log e
        JOIN public.outbox_messages o ON o.event_id = e.event_id
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

CREATE OR REPLACE FUNCTION public.hermes_reject_immutable_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$;

ALTER TABLE public.projects OWNER TO hermes_authority_owner;
ALTER TABLE public.project_transition_records OWNER TO hermes_authority_owner;
ALTER TABLE public.project_evidence_facts OWNER TO hermes_authority_owner;
ALTER TABLE public.project_policy_decision_facts OWNER TO hermes_authority_owner;
ALTER TABLE public.project_budget_facts OWNER TO hermes_authority_owner;
ALTER TABLE public.project_gate_decision_facts OWNER TO hermes_authority_owner;
ALTER FUNCTION public.hermes_create_project_authority(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) OWNER TO hermes_authority_owner;
ALTER FUNCTION public.hermes_transition_project_authority(
    TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TEXT, TEXT, TEXT, TEXT
) OWNER TO hermes_authority_owner;

GRANT SELECT, INSERT, UPDATE ON public.projects TO hermes_authority_owner;
GRANT SELECT, INSERT ON public.project_transition_records TO hermes_authority_owner;
GRANT SELECT, INSERT ON public.project_graph_versions TO hermes_authority_owner;
GRANT SELECT ON public.command_receipts TO hermes_authority_owner;
GRANT SELECT, UPDATE ON public.tasks TO hermes_authority_owner;
GRANT SELECT ON public.verification_results TO hermes_authority_owner;
GRANT SELECT ON public.project_evidence_facts,
    public.project_policy_decision_facts,
    public.project_budget_facts,
    public.project_gate_decision_facts
TO hermes_authority_owner;

REVOKE ALL ON public.project_evidence_facts,
    public.project_policy_decision_facts,
    public.project_budget_facts,
    public.project_gate_decision_facts
FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_create_project_authority(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_transition_project_authority(
    TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;

GRANT SELECT ON public.project_evidence_facts,
    public.project_policy_decision_facts,
    public.project_budget_facts,
    public.project_gate_decision_facts
TO hermes_control_plane_runtime;
GRANT SELECT ON public.project_evidence_facts,
    public.project_policy_decision_facts,
    public.project_budget_facts,
    public.project_gate_decision_facts
TO hermes_read_only_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_create_project_authority(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) TO hermes_control_plane_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_transition_project_authority(
    TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TEXT, TEXT, TEXT, TEXT
) TO hermes_control_plane_runtime;
