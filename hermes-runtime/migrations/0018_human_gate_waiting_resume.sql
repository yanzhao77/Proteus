-- P3-1: Human Gate authority plus Project waiting/resume context.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_human_gate_owner') THEN
        CREATE ROLE hermes_human_gate_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_gate_request_runtime') THEN
        CREATE ROLE hermes_gate_request_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_gate_decision_runtime') THEN
        CREATE ROLE hermes_gate_decision_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

ALTER TABLE public.projects
    DROP CONSTRAINT IF EXISTS projects_check;
ALTER TABLE public.projects
    DROP CONSTRAINT IF EXISTS projects_waiting_resume_state_check;
ALTER TABLE public.projects
    ADD CONSTRAINT projects_waiting_resume_state_check CHECK (
        (state IN ('PAUSED', 'WAITING_FOR_HUMAN') AND resume_state IS NOT NULL)
        OR (state NOT IN ('PAUSED', 'WAITING_FOR_HUMAN') AND resume_state IS NULL)
    );

CREATE TABLE IF NOT EXISTS public.human_gate_authorization_assertions (
    assertion_id TEXT PRIMARY KEY,
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('approver','operator')),
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT REFERENCES public.tasks(task_id),
    gate_request_id TEXT NOT NULL,
    action_scope TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    assertion_hash TEXT NOT NULL CHECK (assertion_hash LIKE 'sha256:%'),
    verification_ref TEXT NOT NULL,
    admitted_by TEXT NOT NULL,
    admitted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version >= 1),
    CHECK (valid_until > valid_from)
);

CREATE TABLE IF NOT EXISTS public.human_gate_requests (
    gate_request_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT REFERENCES public.tasks(task_id),
    action_scope TEXT NOT NULL,
    request_type TEXT NOT NULL CHECK (request_type IN (
        'approval','decision','resource','clarification','exception',
        'acceptance','exhaustion'
    )),
    requester_type TEXT NOT NULL,
    requester_id TEXT NOT NULL,
    policy_decision_id TEXT REFERENCES public.project_policy_decision_facts(policy_decision_id),
    risk_assessment_id TEXT,
    supporting_evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    requested_constraints JSONB NOT NULL DEFAULT '{}'::jsonb,
    approval_policy TEXT NOT NULL CHECK (approval_policy = 'ALL_REQUIRED'),
    required_approver_count INTEGER NOT NULL CHECK (required_approver_count >= 1),
    authorization_requirements JSONB NOT NULL DEFAULT '{}'::jsonb,
    expires_at TIMESTAMPTZ NOT NULL,
    expected_project_version BIGINT NOT NULL,
    expected_graph_version BIGINT,
    resume_context_id TEXT NOT NULL UNIQUE,
    resume_context_hash TEXT NOT NULL CHECK (resume_context_hash LIKE 'sha256:%'),
    attempt_ledger JSONB NOT NULL DEFAULT '[]'::jsonb,
    remaining_options JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommended_option TEXT,
    reason TEXT NOT NULL,
    request_state TEXT NOT NULL CHECK (
        request_state IN ('REQUESTED','APPROVED','REJECTED','EXPIRED','CANCELLED','SUPERSEDED')
    ),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version >= 1),
    superseded_by TEXT REFERENCES public.human_gate_requests(gate_request_id),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    event_id TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (expires_at > created_at)
);

CREATE TABLE IF NOT EXISTS public.project_resume_contexts (
    resume_context_id TEXT PRIMARY KEY,
    gate_request_id TEXT NOT NULL UNIQUE REFERENCES public.human_gate_requests(gate_request_id),
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    project_before_state TEXT NOT NULL,
    project_before_version BIGINT NOT NULL,
    original_command_type TEXT NOT NULL,
    requester_type TEXT NOT NULL,
    requester_id TEXT NOT NULL,
    policy_decision_id TEXT,
    risk_assessment_id TEXT,
    budget_fact_id TEXT,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    supporting_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    expected_task_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    expected_graph_version BIGINT,
    context_payload JSONB NOT NULL,
    context_hash TEXT NOT NULL CHECK (context_hash LIKE 'sha256:%'),
    schema_version TEXT NOT NULL DEFAULT 'resume-context/1.0',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (project_id, context_hash),
    CHECK (context_payload::text !~* '(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|private key|sk-[A-Za-z0-9]{12,}|password=)')
);

ALTER TABLE public.human_gate_requests
    DROP CONSTRAINT IF EXISTS human_gate_requests_resume_context_fk;
ALTER TABLE public.human_gate_requests
    ADD CONSTRAINT human_gate_requests_resume_context_fk
    FOREIGN KEY (resume_context_id)
    REFERENCES public.project_resume_contexts(resume_context_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE IF NOT EXISTS public.human_gate_decisions (
    gate_decision_id TEXT PRIMARY KEY,
    gate_request_id TEXT NOT NULL REFERENCES public.human_gate_requests(gate_request_id),
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    gate_request_version BIGINT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('APPROVE','REJECT')),
    approver_type TEXT NOT NULL,
    approver_id TEXT NOT NULL,
    authorization_ref TEXT NOT NULL,
    assertion_id TEXT NOT NULL REFERENCES public.human_gate_authorization_assertions(assertion_id),
    assertion_hash TEXT NOT NULL CHECK (assertion_hash LIKE 'sha256:%'),
    decision_reason TEXT NOT NULL,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    constraints JSONB NOT NULL DEFAULT '{}'::jsonb,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL,
    decision_state TEXT NOT NULL CHECK (
        decision_state IN ('CURRENT','SUPERSEDED','EXPIRED','APPLIED')
    ),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version >= 1),
    payload_hash TEXT NOT NULL CHECK (payload_hash LIKE 'sha256:%'),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    event_id TEXT UNIQUE,
    CHECK (expires_at > issued_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS human_gate_one_current_decision
    ON public.human_gate_decisions(gate_request_id)
    WHERE decision_state = 'CURRENT';

CREATE TABLE IF NOT EXISTS public.project_waiting_records (
    waiting_record_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT REFERENCES public.tasks(task_id),
    waiting_type TEXT NOT NULL CHECK (waiting_type = 'HUMAN'),
    gate_request_id TEXT NOT NULL REFERENCES public.human_gate_requests(gate_request_id),
    resume_context_id TEXT NOT NULL REFERENCES public.project_resume_contexts(resume_context_id),
    entered_from_state TEXT NOT NULL,
    entered_project_version BIGINT NOT NULL,
    blocking_reason TEXT NOT NULL,
    waiting_state TEXT NOT NULL CHECK (
        waiting_state IN ('WAITING','RESOLVED','REJECTED','EXPIRED','CANCELLED','SUPERSEDED')
    ),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version >= 1),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    event_id TEXT UNIQUE,
    entered_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    resolved_at TIMESTAMPTZ,
    CHECK ((waiting_state = 'WAITING' AND resolved_at IS NULL)
           OR (waiting_state <> 'WAITING' AND resolved_at IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS project_one_current_waiting_record
    ON public.project_waiting_records(project_id)
    WHERE waiting_state = 'WAITING';

CREATE TABLE IF NOT EXISTS public.human_gate_decision_applications (
    application_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    gate_request_id TEXT NOT NULL REFERENCES public.human_gate_requests(gate_request_id),
    gate_decision_id TEXT NOT NULL UNIQUE REFERENCES public.human_gate_decisions(gate_decision_id),
    waiting_record_id TEXT NOT NULL UNIQUE REFERENCES public.project_waiting_records(waiting_record_id),
    resume_context_id TEXT NOT NULL REFERENCES public.project_resume_contexts(resume_context_id),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    project_before_state TEXT NOT NULL,
    project_after_state TEXT NOT NULL,
    project_before_version BIGINT NOT NULL,
    project_after_version BIGINT NOT NULL,
    guard_fact_refs JSONB NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    decision_event_id TEXT UNIQUE REFERENCES public.event_log(event_id),
    project_event_id TEXT UNIQUE REFERENCES public.event_log(event_id),
    CHECK (
        (decision_event_id IS NULL AND project_event_id IS NULL)
        OR (decision_event_id IS NOT NULL AND project_event_id IS NOT NULL)
    )
);

CREATE OR REPLACE FUNCTION public.hermes_human_gate_secret_guard(p_payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
    SELECT p_payload::text ~* '("(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value)"[[:space:]]*:|private key|sk-[A-Za-z0-9]{12,}|password=)'
$$;

CREATE OR REPLACE FUNCTION public.hermes_reject_human_gate_immutable_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS project_resume_context_immutable ON public.project_resume_contexts;
CREATE TRIGGER project_resume_context_immutable
BEFORE UPDATE OR DELETE ON public.project_resume_contexts
FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_human_gate_immutable_change();

DROP TRIGGER IF EXISTS human_gate_application_immutable ON public.human_gate_decision_applications;
CREATE TRIGGER human_gate_application_immutable
BEFORE UPDATE OR DELETE ON public.human_gate_decision_applications
FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_human_gate_immutable_change();

CREATE OR REPLACE FUNCTION public.hermes_reject_human_gate_application_mutation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
    END IF;
    IF OLD.decision_event_id IS NULL AND OLD.project_event_id IS NULL
       AND NEW.decision_event_id IS NOT NULL AND NEW.project_event_id IS NOT NULL
       AND NEW.application_id = OLD.application_id
       AND NEW.project_id = OLD.project_id
       AND NEW.gate_request_id = OLD.gate_request_id
       AND NEW.gate_decision_id = OLD.gate_decision_id
       AND NEW.waiting_record_id = OLD.waiting_record_id
       AND NEW.resume_context_id = OLD.resume_context_id
       AND NEW.command_id = OLD.command_id
       AND NEW.project_before_state = OLD.project_before_state
       AND NEW.project_after_state = OLD.project_after_state
       AND NEW.project_before_version = OLD.project_before_version
       AND NEW.project_after_version = OLD.project_after_version
       AND NEW.guard_fact_refs = OLD.guard_fact_refs
       AND NEW.applied_at = OLD.applied_at THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS human_gate_application_immutable ON public.human_gate_decision_applications;
CREATE TRIGGER human_gate_application_immutable
BEFORE UPDATE OR DELETE ON public.human_gate_decision_applications
FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_human_gate_application_mutation();

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
              'project.paused', 'project.waiting_entered',
              'project.resumed', 'project.cancelled'
          )
          AND (e.payload ->> 'project_version')::BIGINT = NEW.version
          AND e.payload ->> 'new_state' = NEW.state
    ) THEN
        RAISE EXCEPTION 'PROJECT_STATE_EVENT_INVARIANT_VIOLATION';
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_human_gate_append_event(
    p_project_id TEXT,
    p_task_id TEXT,
    p_command_id TEXT,
    p_event_type TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_correlation_id TEXT,
    p_causation_id TEXT,
    p_payload JSONB,
    p_fault_point TEXT DEFAULT NULL
) RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_event_id TEXT := 'evt-' || gen_random_uuid()::text;
    v_sequence BIGINT;
BEGIN
    IF public.hermes_human_gate_secret_guard(p_payload) THEN
        RAISE EXCEPTION 'SECRET_VALUE_FORBIDDEN';
    END IF;
    INSERT INTO public.event_log(
        event_id, event_type, schema_version, producer_type, producer_id,
        project_id, partition_key, command_id, correlation_id, task_id, payload
    ) VALUES (
        v_event_id, p_event_type, '1.0', p_actor_type, p_actor_id,
        p_project_id, p_project_id, p_command_id, p_correlation_id, p_task_id,
        p_payload
    ) RETURNING sequence INTO v_sequence;
    IF p_fault_point = 'after_event_before_outbox' THEN
        RAISE EXCEPTION 'INJECTED_HUMAN_GATE_CRASH_AFTER_EVENT';
    END IF;
    INSERT INTO public.outbox_messages(message_id, event_id, topic, partition_key, sequence, payload)
    VALUES ('msg-' || gen_random_uuid()::text, v_event_id, 'hermes.runtime.events',
            p_project_id, v_sequence, p_payload);
    RETURN v_event_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_human_gate_begin_command(
    p_project_id TEXT,
    p_command_type TEXT,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT
) RETURNS public.command_receipts
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    command_row public.command_receipts%ROWTYPE;
BEGIN
    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key,
        request_hash, status, result
    ) VALUES (
        p_command_id, p_project_id, p_command_type,
        p_idempotency_key, p_payload_hash, 'PROCESSING', '{}'::jsonb
    ) ON CONFLICT DO NOTHING;
    SELECT * INTO command_row
    FROM public.command_receipts
    WHERE project_id=p_project_id AND command_type=p_command_type
      AND idempotency_key=p_idempotency_key
    FOR UPDATE;
    IF NOT FOUND OR command_row.request_hash <> p_payload_hash THEN
        RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT';
    END IF;
    RETURN command_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_human_gate_complete_command(
    p_command_id TEXT,
    p_result_code TEXT,
    p_target_version BIGINT,
    p_event_ids JSONB,
    p_response JSONB
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    UPDATE public.command_receipts
    SET status='APPLIED',
        result=jsonb_build_object(
            'command_id', p_command_id,
            'status', 'APPLIED',
            'result_code', p_result_code,
            'target_version', p_target_version,
            'event_ids', p_event_ids,
            'response', p_response
        ),
        completed_at=clock_timestamp()
    WHERE command_id=p_command_id AND status='PROCESSING';
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_request_human_gate(
    p_project_id TEXT,
    p_gate_request_id TEXT,
    p_task_id TEXT,
    p_action_scope TEXT,
    p_request_type TEXT,
    p_requester_type TEXT,
    p_requester_id TEXT,
    p_expected_project_version BIGINT,
    p_resume_context JSONB,
    p_policy_decision_id TEXT,
    p_risk_assessment_id TEXT,
    p_supporting_evidence_refs JSONB,
    p_requested_constraints JSONB,
    p_approval_policy TEXT,
    p_required_approver_count INTEGER,
    p_authorization_requirements JSONB,
    p_expires_at TIMESTAMPTZ,
    p_expected_graph_version BIGINT,
    p_attempt_ledger JSONB,
    p_remaining_options JSONB,
    p_recommended_option TEXT,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_reason TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    command_row public.command_receipts%ROWTYPE;
    project_row public.projects%ROWTYPE;
    policy_row public.project_policy_decision_facts%ROWTYPE;
    context_id TEXT := COALESCE(p_resume_context->>'context_id', 'ctx-' || p_gate_request_id);
    context_hash TEXT := p_resume_context->>'context_hash';
    v_event_id TEXT;
    response JSONB;
BEGIN
    IF p_actor_type NOT IN ('main_hermes','control_plane','recovery_controller')
       OR p_requester_type NOT IN ('main_hermes','control_plane','recovery_controller') THEN
        RAISE EXCEPTION 'GATE_APPROVER_UNAUTHORIZED';
    END IF;
    IF p_required_approver_count <> 1 OR p_approval_policy <> 'ALL_REQUIRED' THEN
        RAISE EXCEPTION 'GATE_RESUME_GUARD_FAILED';
    END IF;
    IF p_expires_at IS NULL OR p_expires_at <= clock_timestamp() THEN
        RAISE EXCEPTION 'GATE_REQUEST_EXPIRED';
    END IF;
    IF context_hash IS NULL OR context_hash !~ '^sha256:' THEN
        RAISE EXCEPTION 'GATE_RESUME_GUARD_FAILED';
    END IF;
    IF public.hermes_human_gate_secret_guard(p_resume_context) THEN
        RAISE EXCEPTION 'SECRET_VALUE_FORBIDDEN';
    END IF;
    SELECT * INTO project_row
    FROM public.projects
    WHERE project_id=p_project_id AND version=p_expected_project_version
    FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'EXPECTED_VERSION_CONFLICT'; END IF;
    IF project_row.state IN ('ACCEPTED','FAILED','CANCELLED') THEN
        RAISE EXCEPTION 'PROJECT_TERMINAL';
    END IF;
    IF p_policy_decision_id IS NOT NULL THEN
        SELECT * INTO policy_row
        FROM public.project_policy_decision_facts
        WHERE policy_decision_id=p_policy_decision_id
          AND project_id=p_project_id
          AND project_version=p_expected_project_version
          AND result='REQUIRE_HUMAN'
          AND valid
          AND invalidated_at IS NULL
          AND superseded_by IS NULL
          AND (expires_at IS NULL OR expires_at > clock_timestamp());
        IF NOT FOUND THEN RAISE EXCEPTION 'GATE_RESUME_GUARD_FAILED'; END IF;
    ELSIF p_request_type <> 'exhaustion' THEN
        RAISE EXCEPTION 'GATE_RESUME_GUARD_FAILED';
    END IF;
    IF p_request_type = 'exhaustion'
       AND (jsonb_array_length(COALESCE(p_attempt_ledger, '[]'::jsonb)) = 0
            OR jsonb_array_length(COALESCE(p_remaining_options, '[]'::jsonb)) = 0
            OR p_recommended_option IS NULL) THEN
        RAISE EXCEPTION 'GATE_RESUME_GUARD_FAILED';
    END IF;
    command_row := public.hermes_human_gate_begin_command(
        p_project_id, 'human_gate.request', p_command_id, p_idempotency_key, p_payload_hash
    );
    IF command_row.status='APPLIED' THEN RETURN command_row.result->'response'; END IF;
    IF command_row.status='REJECTED' THEN RAISE EXCEPTION '%', command_row.result->>'result_code'; END IF;

    INSERT INTO public.human_gate_requests(
        gate_request_id, project_id, task_id, action_scope, request_type,
        requester_type, requester_id, policy_decision_id, risk_assessment_id,
        supporting_evidence_refs, requested_constraints, approval_policy,
        required_approver_count, authorization_requirements, expires_at,
        expected_project_version, expected_graph_version, resume_context_id,
        resume_context_hash, attempt_ledger, remaining_options, recommended_option,
        reason, request_state, command_id
    ) VALUES (
        p_gate_request_id, p_project_id, p_task_id, p_action_scope, p_request_type,
        p_requester_type, p_requester_id, p_policy_decision_id, p_risk_assessment_id,
        COALESCE(p_supporting_evidence_refs, '[]'::jsonb),
        COALESCE(p_requested_constraints, '{}'::jsonb), p_approval_policy,
        p_required_approver_count, COALESCE(p_authorization_requirements, '{}'::jsonb),
        p_expires_at, p_expected_project_version, p_expected_graph_version,
        context_id, context_hash, COALESCE(p_attempt_ledger, '[]'::jsonb),
        COALESCE(p_remaining_options, '[]'::jsonb), p_recommended_option,
        p_reason, 'REQUESTED', p_command_id
    );
    INSERT INTO public.project_resume_contexts(
        resume_context_id, gate_request_id, project_id, project_before_state,
        project_before_version, original_command_type, requester_type, requester_id,
        policy_decision_id, risk_assessment_id, budget_fact_id, evidence_refs,
        supporting_refs, expected_task_versions, expected_graph_version,
        context_payload, context_hash
    ) VALUES (
        context_id, p_gate_request_id, p_project_id,
        COALESCE(p_resume_context->>'project_before_state', project_row.state),
        p_expected_project_version,
        COALESCE(p_resume_context->>'original_command_type', 'project.resume_from_gate'),
        p_requester_type, p_requester_id, p_policy_decision_id, p_risk_assessment_id,
        p_resume_context->>'budget_fact_id',
        COALESCE(p_resume_context->'evidence_refs', '[]'::jsonb),
        COALESCE(p_resume_context->'supporting_refs', '[]'::jsonb),
        COALESCE(p_resume_context->'expected_task_versions', '{}'::jsonb),
        p_expected_graph_version, p_resume_context, context_hash
    );
    IF p_fault_point = 'after_request_before_event' THEN
        RAISE EXCEPTION 'INJECTED_HUMAN_GATE_CRASH_AFTER_REQUEST';
    END IF;
    v_event_id := public.hermes_human_gate_append_event(
        p_project_id, p_task_id, p_command_id, 'human_gate.requested',
        p_actor_type, p_actor_id, p_command_id, p_policy_decision_id,
        jsonb_build_object(
            'project_id', p_project_id,
            'task_id', p_task_id,
            'gate_request_id', p_gate_request_id,
            'request_state', 'REQUESTED',
            'requester', jsonb_build_object('type',p_requester_type,'id',p_requester_id),
            'action_scope', p_action_scope,
            'resume_context_id', context_id,
            'resume_context_hash', context_hash,
            'reason', p_reason,
            'supporting_refs', p_supporting_evidence_refs
        ),
        p_fault_point
    );
    UPDATE public.human_gate_requests SET event_id=v_event_id WHERE gate_request_id=p_gate_request_id;
    response := jsonb_build_object(
        'result_code','HUMAN_GATE_REQUESTED',
        'gate_request_id',p_gate_request_id,
        'resume_context_id',context_id,
        'resume_context_hash',context_hash,
        'request_state','REQUESTED',
        'request_version',1,
        'event_ids',jsonb_build_array(v_event_id)
    );
    PERFORM public.hermes_human_gate_complete_command(
        p_command_id, 'HUMAN_GATE_REQUESTED', 1, jsonb_build_array(v_event_id), response
    );
    IF p_fault_point = 'after_outbox_before_receipt' THEN
        RAISE EXCEPTION 'INJECTED_HUMAN_GATE_CRASH_AFTER_OUTBOX';
    END IF;
    RETURN response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_enter_project_waiting_for_gate(
    p_project_id TEXT,
    p_waiting_record_id TEXT,
    p_gate_request_id TEXT,
    p_resume_context_id TEXT,
    p_expected_project_version BIGINT,
    p_blocking_reason TEXT,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_reason TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    command_row public.command_receipts%ROWTYPE;
    project_row public.projects%ROWTYPE;
    request_row public.human_gate_requests%ROWTYPE;
    context_row public.project_resume_contexts%ROWTYPE;
    next_version BIGINT;
    v_event_id TEXT;
    response JSONB;
BEGIN
    IF p_actor_type <> 'control_plane' THEN RAISE EXCEPTION 'CONTROL_PLANE_AUTHORITY_REQUIRED'; END IF;
    command_row := public.hermes_human_gate_begin_command(
        p_project_id, 'project.enter_waiting', p_command_id, p_idempotency_key, p_payload_hash
    );
    IF command_row.status='APPLIED' THEN RETURN command_row.result->'response'; END IF;
    SELECT * INTO project_row FROM public.projects
    WHERE project_id=p_project_id AND version=p_expected_project_version FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'EXPECTED_VERSION_CONFLICT'; END IF;
    IF project_row.state IN ('ACCEPTED','FAILED','CANCELLED') THEN RAISE EXCEPTION 'PROJECT_TERMINAL'; END IF;
    IF EXISTS (SELECT 1 FROM public.project_waiting_records WHERE project_id=p_project_id AND waiting_state='WAITING') THEN
        RAISE EXCEPTION 'PROJECT_ALREADY_WAITING';
    END IF;
    SELECT * INTO request_row FROM public.human_gate_requests
    WHERE gate_request_id=p_gate_request_id AND project_id=p_project_id FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'GATE_REQUEST_NOT_FOUND'; END IF;
    IF request_row.request_state <> 'REQUESTED' OR request_row.version <> 1 THEN
        RAISE EXCEPTION 'GATE_REQUEST_STALE';
    END IF;
    IF request_row.expires_at <= clock_timestamp() THEN RAISE EXCEPTION 'GATE_REQUEST_EXPIRED'; END IF;
    SELECT * INTO context_row FROM public.project_resume_contexts
    WHERE resume_context_id=p_resume_context_id
      AND gate_request_id=p_gate_request_id
      AND project_id=p_project_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'GATE_RESUME_CONTEXT_MISMATCH'; END IF;
    INSERT INTO public.project_waiting_records(
        waiting_record_id, project_id, task_id, waiting_type, gate_request_id,
        resume_context_id, entered_from_state, entered_project_version,
        blocking_reason, waiting_state, command_id
    ) VALUES (
        p_waiting_record_id, p_project_id, request_row.task_id, 'HUMAN',
        p_gate_request_id, p_resume_context_id, project_row.state,
        project_row.version, p_blocking_reason, 'WAITING', p_command_id
    );
    IF p_fault_point = 'after_waiting_before_context' THEN
        RAISE EXCEPTION 'INJECTED_HUMAN_GATE_CRASH_AFTER_WAITING';
    END IF;
    next_version := project_row.version + 1;
    UPDATE public.projects
    SET state='WAITING_FOR_HUMAN', resume_state=project_row.state,
        version=next_version, last_command_id=p_command_id, updated_at=clock_timestamp()
    WHERE project_id=p_project_id AND version=project_row.version;
    IF p_fault_point = 'after_context_before_event' THEN
        RAISE EXCEPTION 'INJECTED_HUMAN_GATE_CRASH_AFTER_CONTEXT';
    END IF;
    v_event_id := public.hermes_human_gate_append_event(
        p_project_id, request_row.task_id, p_command_id, 'project.waiting_entered',
        p_actor_type, p_actor_id, p_command_id, p_gate_request_id,
        jsonb_build_object(
            'project_id',p_project_id,
            'gate_request_id',p_gate_request_id,
            'waiting_record_id',p_waiting_record_id,
            'resume_context_id',p_resume_context_id,
            'resume_context_hash',context_row.context_hash,
            'previous_state',project_row.state,
            'new_state','WAITING_FOR_HUMAN',
            'project_version',next_version,
            'reason',p_blocking_reason
        ),
        p_fault_point
    );
    UPDATE public.project_waiting_records SET event_id=v_event_id WHERE waiting_record_id=p_waiting_record_id;
    INSERT INTO public.project_transition_records
      (transition_id, project_id, command_id, previous_state, new_state,
       project_version, actor_type, actor_id, requested_by_type,
       requested_by_id, reason)
    VALUES ('ptr-' || gen_random_uuid()::text, p_project_id, p_command_id,
            project_row.state, 'WAITING_FOR_HUMAN', next_version, p_actor_type,
            p_actor_id, request_row.requester_type, request_row.requester_id, p_blocking_reason);
    response := jsonb_build_object(
        'result_code','PROJECT_WAITING_ENTERED',
        'waiting_record_id',p_waiting_record_id,
        'gate_request_id',p_gate_request_id,
        'project_state','WAITING_FOR_HUMAN',
        'project_version',next_version,
        'event_ids',jsonb_build_array(v_event_id)
    );
    PERFORM public.hermes_human_gate_complete_command(
        p_command_id, 'PROJECT_WAITING_ENTERED', next_version, jsonb_build_array(v_event_id), response
    );
    RETURN response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_submit_human_gate_decision(
    p_project_id TEXT,
    p_gate_decision_id TEXT,
    p_gate_request_id TEXT,
    p_decision TEXT,
    p_approver_type TEXT,
    p_approver_id TEXT,
    p_authorization_ref TEXT,
    p_assertion_id TEXT,
    p_assertion_hash TEXT,
    p_evidence_refs JSONB,
    p_constraints JSONB,
    p_expires_at TIMESTAMPTZ,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_reason TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    command_row public.command_receipts%ROWTYPE;
    request_row public.human_gate_requests%ROWTYPE;
    auth_row public.human_gate_authorization_assertions%ROWTYPE;
    v_event_id TEXT;
    new_request_state TEXT;
    response JSONB;
BEGIN
    IF p_actor_type <> p_approver_type OR p_actor_id <> p_approver_id THEN
        RAISE EXCEPTION 'GATE_APPROVER_UNAUTHORIZED';
    END IF;
    IF p_approver_type NOT IN ('user','system_operator') THEN
        RAISE EXCEPTION 'GATE_APPROVER_UNAUTHORIZED';
    END IF;
    IF p_decision NOT IN ('APPROVE','REJECT') THEN RAISE EXCEPTION 'GATE_DECISION_NOT_APPROVED'; END IF;
    IF p_expires_at IS NULL OR p_expires_at <= clock_timestamp() THEN
        RAISE EXCEPTION 'GATE_DECISION_EXPIRED';
    END IF;
    command_row := public.hermes_human_gate_begin_command(
        p_project_id, 'human_gate.decide', p_command_id, p_idempotency_key, p_payload_hash
    );
    IF command_row.status='APPLIED' THEN RETURN command_row.result->'response'; END IF;
    SELECT * INTO request_row FROM public.human_gate_requests
    WHERE gate_request_id=p_gate_request_id AND project_id=p_project_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'GATE_REQUEST_NOT_FOUND'; END IF;
    IF request_row.request_state <> 'REQUESTED' THEN
        IF request_row.request_state = 'EXPIRED' THEN RAISE EXCEPTION 'GATE_REQUEST_EXPIRED';
        ELSIF request_row.request_state = 'SUPERSEDED' THEN RAISE EXCEPTION 'GATE_DECISION_SUPERSEDED';
        ELSE RAISE EXCEPTION 'GATE_REQUEST_STALE'; END IF;
    END IF;
    IF request_row.expires_at <= clock_timestamp() THEN RAISE EXCEPTION 'GATE_REQUEST_EXPIRED'; END IF;
    IF request_row.requester_type = p_approver_type AND request_row.requester_id = p_approver_id THEN
        RAISE EXCEPTION 'GATE_SELF_APPROVAL_FORBIDDEN';
    END IF;
    SELECT * INTO auth_row FROM public.human_gate_authorization_assertions
    WHERE assertion_id=p_assertion_id
      AND project_id=p_project_id
      AND gate_request_id=p_gate_request_id
      AND subject=p_approver_id
      AND action_scope=request_row.action_scope
      AND assertion_hash=p_assertion_hash
      AND revoked_at IS NULL
      AND valid_from <= clock_timestamp()
      AND valid_until > clock_timestamp()
    FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'GATE_APPROVER_UNAUTHORIZED'; END IF;
    IF auth_row.task_id IS NOT NULL AND auth_row.task_id IS DISTINCT FROM request_row.task_id THEN
        RAISE EXCEPTION 'GATE_SCOPE_MISMATCH';
    END IF;
    new_request_state := CASE WHEN p_decision='APPROVE' THEN 'APPROVED' ELSE 'REJECTED' END;
    INSERT INTO public.human_gate_decisions(
        gate_decision_id, gate_request_id, project_id, gate_request_version,
        decision, approver_type, approver_id, authorization_ref, assertion_id,
        assertion_hash, decision_reason, evidence_refs, constraints, expires_at,
        decision_state, payload_hash, command_id
    ) VALUES (
        p_gate_decision_id, p_gate_request_id, p_project_id, request_row.version,
        p_decision, p_approver_type, p_approver_id, p_authorization_ref,
        p_assertion_id, p_assertion_hash, p_reason, COALESCE(p_evidence_refs,'[]'::jsonb),
        COALESCE(p_constraints,'{}'::jsonb), p_expires_at, 'CURRENT',
        p_payload_hash, p_command_id
    );
    UPDATE public.human_gate_requests
    SET request_state=new_request_state, version=version+1, updated_at=clock_timestamp()
    WHERE gate_request_id=p_gate_request_id AND version=request_row.version;
    IF p_fault_point = 'after_decision_before_event' THEN
        RAISE EXCEPTION 'INJECTED_HUMAN_GATE_CRASH_AFTER_DECISION';
    END IF;
    v_event_id := public.hermes_human_gate_append_event(
        p_project_id, request_row.task_id, p_command_id,
        CASE WHEN p_decision='APPROVE' THEN 'human_gate.approved' ELSE 'human_gate.rejected' END,
        p_approver_type, p_approver_id, p_command_id, p_gate_request_id,
        jsonb_build_object(
            'project_id',p_project_id,
            'gate_request_id',p_gate_request_id,
            'gate_decision_id',p_gate_decision_id,
            'decision',p_decision,
            'request_state',new_request_state,
            'approver',jsonb_build_object('type',p_approver_type,'id',p_approver_id),
            'authorization_ref',p_authorization_ref,
            'reason',p_reason,
            'resume_context_hash',request_row.resume_context_hash
        ),
        p_fault_point
    );
    UPDATE public.human_gate_decisions SET event_id=v_event_id WHERE gate_decision_id=p_gate_decision_id;
    response := jsonb_build_object(
        'result_code', CASE WHEN p_decision='APPROVE' THEN 'HUMAN_GATE_APPROVED' ELSE 'HUMAN_GATE_REJECTED' END,
        'gate_request_id',p_gate_request_id,
        'gate_decision_id',p_gate_decision_id,
        'request_state',new_request_state,
        'decision',p_decision,
        'request_version',request_row.version + 1,
        'decision_version',1,
        'event_ids',jsonb_build_array(v_event_id)
    );
    PERFORM public.hermes_human_gate_complete_command(
        p_command_id, response->>'result_code', request_row.version + 1, jsonb_build_array(v_event_id), response
    );
    RETURN response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_apply_human_gate_decision(
    p_project_id TEXT,
    p_gate_request_id TEXT,
    p_gate_decision_id TEXT,
    p_waiting_record_id TEXT,
    p_expected_project_version BIGINT,
    p_expected_waiting_version BIGINT,
    p_expected_gate_version BIGINT,
    p_expected_decision_version BIGINT,
    p_resume_context_hash TEXT,
    p_target_state TEXT,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_reason TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    command_row public.command_receipts%ROWTYPE;
    project_row public.projects%ROWTYPE;
    request_row public.human_gate_requests%ROWTYPE;
    decision_row public.human_gate_decisions%ROWTYPE;
    waiting_row public.project_waiting_records%ROWTYPE;
    context_row public.project_resume_contexts%ROWTYPE;
    auth_row public.human_gate_authorization_assertions%ROWTYPE;
    target_state TEXT;
    next_project_version BIGINT;
    gate_fact_id TEXT := 'gate-fact-' || gen_random_uuid()::text;
    v_decision_event_id TEXT;
    v_project_event_id TEXT;
    response JSONB;
BEGIN
    IF p_actor_type <> 'control_plane' THEN RAISE EXCEPTION 'CONTROL_PLANE_AUTHORITY_REQUIRED'; END IF;
    command_row := public.hermes_human_gate_begin_command(
        p_project_id, 'human_gate.apply_decision', p_command_id, p_idempotency_key, p_payload_hash
    );
    IF command_row.status='APPLIED' THEN RETURN command_row.result->'response'; END IF;
    SELECT * INTO project_row FROM public.projects
    WHERE project_id=p_project_id AND version=p_expected_project_version FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'EXPECTED_VERSION_CONFLICT'; END IF;
    IF project_row.state <> 'WAITING_FOR_HUMAN' THEN RAISE EXCEPTION 'PROJECT_NOT_WAITING'; END IF;
    SELECT * INTO waiting_row FROM public.project_waiting_records
    WHERE waiting_record_id=p_waiting_record_id AND project_id=p_project_id FOR UPDATE;
    IF NOT FOUND OR waiting_row.waiting_state <> 'WAITING' THEN RAISE EXCEPTION 'PROJECT_NOT_WAITING'; END IF;
    IF waiting_row.version <> p_expected_waiting_version THEN RAISE EXCEPTION 'EXPECTED_VERSION_CONFLICT'; END IF;
    SELECT * INTO request_row FROM public.human_gate_requests
    WHERE gate_request_id=p_gate_request_id AND project_id=p_project_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'GATE_REQUEST_NOT_FOUND'; END IF;
    IF request_row.version <> p_expected_gate_version THEN RAISE EXCEPTION 'GATE_REQUEST_STALE'; END IF;
    IF request_row.request_state <> 'APPROVED' THEN RAISE EXCEPTION 'GATE_DECISION_NOT_APPROVED'; END IF;
    IF request_row.expires_at <= clock_timestamp() THEN RAISE EXCEPTION 'GATE_REQUEST_EXPIRED'; END IF;
    SELECT * INTO decision_row FROM public.human_gate_decisions
    WHERE gate_decision_id=p_gate_decision_id AND gate_request_id=p_gate_request_id
      AND project_id=p_project_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'GATE_DECISION_NOT_APPROVED'; END IF;
    IF decision_row.version <> p_expected_decision_version THEN RAISE EXCEPTION 'EXPECTED_VERSION_CONFLICT'; END IF;
    IF decision_row.decision_state <> 'CURRENT' THEN RAISE EXCEPTION 'GATE_DECISION_SUPERSEDED'; END IF;
    IF decision_row.decision <> 'APPROVE' THEN RAISE EXCEPTION 'GATE_DECISION_NOT_APPROVED'; END IF;
    IF decision_row.expires_at <= clock_timestamp() THEN RAISE EXCEPTION 'GATE_DECISION_EXPIRED'; END IF;
    SELECT * INTO context_row FROM public.project_resume_contexts
    WHERE resume_context_id=waiting_row.resume_context_id
      AND gate_request_id=p_gate_request_id
      AND project_id=p_project_id;
    IF NOT FOUND OR context_row.context_hash <> p_resume_context_hash THEN
        RAISE EXCEPTION 'GATE_RESUME_CONTEXT_MISMATCH';
    END IF;
    SELECT * INTO auth_row FROM public.human_gate_authorization_assertions
    WHERE assertion_id=decision_row.assertion_id
      AND revoked_at IS NULL
      AND valid_from <= clock_timestamp()
      AND valid_until > clock_timestamp();
    IF NOT FOUND THEN RAISE EXCEPTION 'GATE_APPROVER_UNAUTHORIZED'; END IF;
    target_state := COALESCE(p_target_state, context_row.project_before_state);
    IF target_state IS DISTINCT FROM project_row.resume_state THEN
        RAISE EXCEPTION 'GATE_RESUME_GUARD_FAILED';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.project_evidence_facts
        WHERE project_id=p_project_id AND project_version=p_expected_project_version
          AND from_state='WAITING_FOR_HUMAN' AND to_state=target_state
          AND authority='verification_engine' AND result='VALID' AND valid
          AND invalidated_at IS NULL AND superseded_by IS NULL
          AND (expires_at IS NULL OR expires_at > clock_timestamp())
    ) THEN RAISE EXCEPTION 'GATE_EVIDENCE_INVALID'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.project_policy_decision_facts
        WHERE project_id=p_project_id AND project_version=p_expected_project_version
          AND from_state='WAITING_FOR_HUMAN' AND to_state=target_state
          AND authority='policy_engine' AND result IN ('ALLOW','REQUIRE_HUMAN') AND valid
          AND invalidated_at IS NULL AND superseded_by IS NULL
          AND (expires_at IS NULL OR expires_at > clock_timestamp())
    ) THEN RAISE EXCEPTION 'GATE_RESUME_GUARD_FAILED'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.project_budget_facts
        WHERE project_id=p_project_id AND project_version=p_expected_project_version
          AND from_state='WAITING_FOR_HUMAN' AND to_state=target_state
          AND authority='budget_engine' AND status='OK' AND valid
          AND invalidated_at IS NULL AND superseded_by IS NULL
          AND (expires_at IS NULL OR expires_at > clock_timestamp())
    ) THEN RAISE EXCEPTION 'GATE_RESUME_GUARD_FAILED'; END IF;

    INSERT INTO public.project_gate_decision_facts(
        gate_decision_id, project_id, project_version, from_state, to_state,
        status, authority, gate_id, decision_ref, expires_at
    ) VALUES (
        gate_fact_id, p_project_id, p_expected_project_version, 'WAITING_FOR_HUMAN',
        target_state, 'ANSWERED_APPLIED', 'human_gate', p_gate_request_id,
        p_gate_decision_id, decision_row.expires_at
    );
    INSERT INTO public.human_gate_decision_applications(
        application_id, project_id, gate_request_id, gate_decision_id,
        waiting_record_id, resume_context_id, command_id, project_before_state,
        project_after_state, project_before_version, project_after_version,
        guard_fact_refs, decision_event_id, project_event_id
    ) VALUES (
        'hga-' || gen_random_uuid()::text, p_project_id, p_gate_request_id,
        p_gate_decision_id, p_waiting_record_id, context_row.resume_context_id,
        p_command_id, project_row.state, target_state, project_row.version,
        project_row.version + 1, jsonb_build_array(gate_fact_id),
        NULL, NULL
    );
    IF p_fault_point = 'after_application_before_project' THEN
        RAISE EXCEPTION 'INJECTED_HUMAN_GATE_CRASH_AFTER_APPLICATION';
    END IF;
    next_project_version := project_row.version + 1;
    UPDATE public.projects
    SET state=target_state, resume_state=NULL, version=next_project_version,
        last_command_id=p_command_id, updated_at=clock_timestamp()
    WHERE project_id=p_project_id AND version=project_row.version;
    UPDATE public.project_waiting_records
    SET waiting_state='RESOLVED', version=version+1, resolved_at=clock_timestamp()
    WHERE waiting_record_id=p_waiting_record_id;
    UPDATE public.human_gate_decisions
    SET decision_state='APPLIED', version=version+1
    WHERE gate_decision_id=p_gate_decision_id;
    IF p_fault_point = 'after_project_before_event' THEN
        RAISE EXCEPTION 'INJECTED_HUMAN_GATE_CRASH_AFTER_PROJECT';
    END IF;
    v_decision_event_id := public.hermes_human_gate_append_event(
        p_project_id, request_row.task_id, p_command_id, 'human_gate.decision_applied',
        p_actor_type, p_actor_id, p_command_id, p_gate_decision_id,
        jsonb_build_object(
            'project_id',p_project_id,
            'gate_request_id',p_gate_request_id,
            'gate_decision_id',p_gate_decision_id,
            'waiting_record_id',p_waiting_record_id,
            'resume_context_hash',context_row.context_hash,
            'guard_fact_refs',jsonb_build_array(gate_fact_id),
            'reason',p_reason
        ),
        p_fault_point
    );
    v_project_event_id := public.hermes_human_gate_append_event(
        p_project_id, request_row.task_id, p_command_id, 'project.resumed',
        p_actor_type, p_actor_id, p_command_id, v_decision_event_id,
        jsonb_build_object(
            'project_id',p_project_id,
            'gate_request_id',p_gate_request_id,
            'gate_decision_id',p_gate_decision_id,
            'waiting_record_id',p_waiting_record_id,
            'resume_context_hash',context_row.context_hash,
            'previous_state',project_row.state,
            'new_state',target_state,
            'project_version',next_project_version,
            'reason',p_reason
        ),
        p_fault_point
    );
    INSERT INTO public.project_transition_records
      (transition_id, project_id, command_id, previous_state, new_state,
       project_version, actor_type, actor_id, requested_by_type,
       requested_by_id, reason)
    VALUES ('ptr-' || gen_random_uuid()::text, p_project_id, p_command_id,
            project_row.state, target_state, next_project_version, p_actor_type,
            p_actor_id, request_row.requester_type, request_row.requester_id, p_reason);
    UPDATE public.human_gate_decision_applications
    SET decision_event_id=v_decision_event_id, project_event_id=v_project_event_id
    WHERE gate_decision_id=p_gate_decision_id;
    response := jsonb_build_object(
        'result_code','HUMAN_GATE_DECISION_APPLIED',
        'gate_request_id',p_gate_request_id,
        'gate_decision_id',p_gate_decision_id,
        'waiting_record_id',p_waiting_record_id,
        'project_state',target_state,
        'project_version',next_project_version,
        'event_ids',jsonb_build_array(v_decision_event_id, v_project_event_id)
    );
    PERFORM public.hermes_human_gate_complete_command(
        p_command_id, 'HUMAN_GATE_DECISION_APPLIED', next_project_version,
        jsonb_build_array(v_decision_event_id, v_project_event_id), response
    );
    RETURN response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_expire_human_gate_request(
    p_project_id TEXT,
    p_gate_request_id TEXT,
    p_authorization_ref TEXT,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_reason TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    command_row public.command_receipts%ROWTYPE;
    request_row public.human_gate_requests%ROWTYPE;
    v_event_id TEXT;
    response JSONB;
BEGIN
    IF p_actor_type <> 'control_plane' THEN RAISE EXCEPTION 'CONTROL_PLANE_AUTHORITY_REQUIRED'; END IF;
    command_row := public.hermes_human_gate_begin_command(
        p_project_id, 'human_gate.expire', p_command_id, p_idempotency_key, p_payload_hash
    );
    IF command_row.status='APPLIED' THEN RETURN command_row.result->'response'; END IF;
    SELECT * INTO request_row FROM public.human_gate_requests
    WHERE gate_request_id=p_gate_request_id AND project_id=p_project_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'GATE_REQUEST_NOT_FOUND'; END IF;
    IF request_row.request_state <> 'REQUESTED' THEN RAISE EXCEPTION 'GATE_REQUEST_STALE'; END IF;
    IF request_row.expires_at > clock_timestamp() THEN RAISE EXCEPTION 'GATE_REQUEST_STALE'; END IF;
    UPDATE public.human_gate_requests
    SET request_state='EXPIRED', version=version+1, updated_at=clock_timestamp()
    WHERE gate_request_id=p_gate_request_id;
    UPDATE public.project_waiting_records
    SET waiting_state='EXPIRED', version=version+1, resolved_at=clock_timestamp()
    WHERE gate_request_id=p_gate_request_id AND waiting_state='WAITING';
    IF p_fault_point = 'after_expiry_before_event' THEN
        RAISE EXCEPTION 'INJECTED_HUMAN_GATE_CRASH_AFTER_EXPIRY';
    END IF;
    v_event_id := public.hermes_human_gate_append_event(
        p_project_id, request_row.task_id, p_command_id, 'human_gate.expired',
        p_actor_type, p_actor_id, p_command_id, p_gate_request_id,
        jsonb_build_object('project_id',p_project_id,'gate_request_id',p_gate_request_id,
                           'request_state','EXPIRED','reason',p_reason,
                           'resume_context_hash',request_row.resume_context_hash),
        p_fault_point
    );
    response := jsonb_build_object('result_code','HUMAN_GATE_EXPIRED',
        'gate_request_id',p_gate_request_id,'request_state','EXPIRED',
        'event_ids',jsonb_build_array(v_event_id));
    PERFORM public.hermes_human_gate_complete_command(
        p_command_id, 'HUMAN_GATE_EXPIRED', request_row.version + 1, jsonb_build_array(v_event_id), response
    );
    RETURN response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_cancel_human_gate_request(
    p_project_id TEXT,
    p_gate_request_id TEXT,
    p_authorization_ref TEXT,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_reason TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    command_row public.command_receipts%ROWTYPE;
    request_row public.human_gate_requests%ROWTYPE;
    v_event_id TEXT;
    response JSONB;
BEGIN
    IF p_actor_type NOT IN ('system_operator','main_hermes','control_plane')
       OR NULLIF(btrim(p_authorization_ref), '') IS NULL THEN
        RAISE EXCEPTION 'GATE_APPROVER_UNAUTHORIZED';
    END IF;
    command_row := public.hermes_human_gate_begin_command(
        p_project_id, 'human_gate.cancel', p_command_id, p_idempotency_key, p_payload_hash
    );
    IF command_row.status='APPLIED' THEN RETURN command_row.result->'response'; END IF;
    SELECT * INTO request_row FROM public.human_gate_requests
    WHERE gate_request_id=p_gate_request_id AND project_id=p_project_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'GATE_REQUEST_NOT_FOUND'; END IF;
    IF request_row.request_state IN ('APPROVED','REJECTED') THEN RAISE EXCEPTION 'GATE_REQUEST_STALE'; END IF;
    IF request_row.request_state <> 'REQUESTED' THEN RAISE EXCEPTION 'GATE_REQUEST_STALE'; END IF;
    UPDATE public.human_gate_requests
    SET request_state='CANCELLED', version=version+1, updated_at=clock_timestamp()
    WHERE gate_request_id=p_gate_request_id;
    UPDATE public.project_waiting_records
    SET waiting_state='CANCELLED', version=version+1, resolved_at=clock_timestamp()
    WHERE gate_request_id=p_gate_request_id AND waiting_state='WAITING';
    v_event_id := public.hermes_human_gate_append_event(
        p_project_id, request_row.task_id, p_command_id, 'human_gate.cancelled',
        p_actor_type, p_actor_id, p_command_id, p_gate_request_id,
        jsonb_build_object('project_id',p_project_id,'gate_request_id',p_gate_request_id,
                           'authorization_ref',p_authorization_ref,
                           'request_state','CANCELLED','reason',p_reason,
                           'resume_context_hash',request_row.resume_context_hash),
        p_fault_point
    );
    response := jsonb_build_object('result_code','HUMAN_GATE_CANCELLED',
        'gate_request_id',p_gate_request_id,'request_state','CANCELLED',
        'event_ids',jsonb_build_array(v_event_id));
    PERFORM public.hermes_human_gate_complete_command(
        p_command_id, 'HUMAN_GATE_CANCELLED', request_row.version + 1, jsonb_build_array(v_event_id), response
    );
    RETURN response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_supersede_human_gate_request(
    p_project_id TEXT,
    p_old_gate_request_id TEXT,
    p_new_gate_request_id TEXT,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_reason TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    command_row public.command_receipts%ROWTYPE;
    old_row public.human_gate_requests%ROWTYPE;
    new_row public.human_gate_requests%ROWTYPE;
    v_event_id TEXT;
    response JSONB;
BEGIN
    IF p_actor_type <> 'control_plane' THEN RAISE EXCEPTION 'CONTROL_PLANE_AUTHORITY_REQUIRED'; END IF;
    command_row := public.hermes_human_gate_begin_command(
        p_project_id, 'human_gate.supersede', p_command_id, p_idempotency_key, p_payload_hash
    );
    IF command_row.status='APPLIED' THEN RETURN command_row.result->'response'; END IF;
    SELECT * INTO old_row FROM public.human_gate_requests
    WHERE gate_request_id=p_old_gate_request_id AND project_id=p_project_id FOR UPDATE;
    SELECT * INTO new_row FROM public.human_gate_requests
    WHERE gate_request_id=p_new_gate_request_id AND project_id=p_project_id FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'GATE_REQUEST_NOT_FOUND'; END IF;
    IF old_row.request_state <> 'REQUESTED' THEN RAISE EXCEPTION 'GATE_REQUEST_STALE'; END IF;
    IF old_row.action_scope <> new_row.action_scope THEN RAISE EXCEPTION 'GATE_SCOPE_MISMATCH'; END IF;
    UPDATE public.human_gate_requests
    SET request_state='SUPERSEDED', superseded_by=p_new_gate_request_id,
        version=version+1, updated_at=clock_timestamp()
    WHERE gate_request_id=p_old_gate_request_id;
    UPDATE public.project_waiting_records
    SET waiting_state='SUPERSEDED', version=version+1, resolved_at=clock_timestamp()
    WHERE gate_request_id=p_old_gate_request_id AND waiting_state='WAITING';
    IF p_fault_point = 'after_supersede_before_event' THEN
        RAISE EXCEPTION 'INJECTED_HUMAN_GATE_CRASH_AFTER_SUPERSEDE';
    END IF;
    v_event_id := public.hermes_human_gate_append_event(
        p_project_id, old_row.task_id, p_command_id, 'human_gate.superseded',
        p_actor_type, p_actor_id, p_command_id, p_old_gate_request_id,
        jsonb_build_object('project_id',p_project_id,'gate_request_id',p_old_gate_request_id,
                           'superseded_by',p_new_gate_request_id,
                           'request_state','SUPERSEDED','reason',p_reason,
                           'resume_context_hash',old_row.resume_context_hash),
        p_fault_point
    );
    response := jsonb_build_object('result_code','HUMAN_GATE_SUPERSEDED',
        'gate_request_id',p_old_gate_request_id,'superseded_by',p_new_gate_request_id,
        'request_state','SUPERSEDED','event_ids',jsonb_build_array(v_event_id));
    PERFORM public.hermes_human_gate_complete_command(
        p_command_id, 'HUMAN_GATE_SUPERSEDED', old_row.version + 1, jsonb_build_array(v_event_id), response
    );
    RETURN response;
END;
$$;

ALTER TABLE public.human_gate_authorization_assertions OWNER TO hermes_human_gate_owner;
ALTER TABLE public.human_gate_requests OWNER TO hermes_human_gate_owner;
ALTER TABLE public.project_resume_contexts OWNER TO hermes_human_gate_owner;
ALTER TABLE public.human_gate_decisions OWNER TO hermes_human_gate_owner;
ALTER TABLE public.project_waiting_records OWNER TO hermes_human_gate_owner;
ALTER TABLE public.human_gate_decision_applications OWNER TO hermes_human_gate_owner;

ALTER FUNCTION public.hermes_human_gate_secret_guard(JSONB) OWNER TO hermes_human_gate_owner;
ALTER FUNCTION public.hermes_reject_human_gate_immutable_change() OWNER TO hermes_human_gate_owner;
ALTER FUNCTION public.hermes_reject_human_gate_application_mutation() OWNER TO hermes_human_gate_owner;
ALTER FUNCTION public.hermes_human_gate_append_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) OWNER TO hermes_human_gate_owner;
ALTER FUNCTION public.hermes_human_gate_begin_command(TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_human_gate_owner;
ALTER FUNCTION public.hermes_human_gate_complete_command(TEXT,TEXT,BIGINT,JSONB,JSONB) OWNER TO hermes_human_gate_owner;
ALTER FUNCTION public.hermes_request_human_gate(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,JSONB,TEXT,TEXT,JSONB,JSONB,TEXT,INTEGER,JSONB,TIMESTAMPTZ,BIGINT,JSONB,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_human_gate_owner;
ALTER FUNCTION public.hermes_enter_project_waiting_for_gate(TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_human_gate_owner;
ALTER FUNCTION public.hermes_submit_human_gate_decision(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,JSONB,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_human_gate_owner;
ALTER FUNCTION public.hermes_apply_human_gate_decision(TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_human_gate_owner;
ALTER FUNCTION public.hermes_expire_human_gate_request(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_human_gate_owner;
ALTER FUNCTION public.hermes_cancel_human_gate_request(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_human_gate_owner;
ALTER FUNCTION public.hermes_supersede_human_gate_request(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_human_gate_owner;

GRANT SELECT, INSERT, UPDATE ON public.command_receipts TO hermes_human_gate_owner;
GRANT SELECT, INSERT, UPDATE ON public.human_gate_authorization_assertions TO hermes_human_gate_owner;
GRANT SELECT, INSERT, UPDATE ON public.human_gate_requests TO hermes_human_gate_owner;
GRANT SELECT, INSERT ON public.project_resume_contexts TO hermes_human_gate_owner;
GRANT SELECT, INSERT, UPDATE ON public.human_gate_decisions TO hermes_human_gate_owner;
GRANT SELECT, INSERT, UPDATE ON public.project_waiting_records TO hermes_human_gate_owner;
GRANT SELECT, INSERT ON public.human_gate_decision_applications TO hermes_human_gate_owner;
GRANT SELECT, INSERT ON public.event_log TO hermes_human_gate_owner;
GRANT SELECT, INSERT ON public.outbox_messages TO hermes_human_gate_owner;
GRANT SELECT, INSERT ON public.project_gate_decision_facts TO hermes_human_gate_owner;
GRANT SELECT, INSERT ON public.project_transition_records TO hermes_human_gate_owner;
GRANT SELECT, UPDATE ON public.projects TO hermes_human_gate_owner;
GRANT SELECT ON public.tasks TO hermes_human_gate_owner;
GRANT SELECT ON public.project_policy_decision_facts, public.project_budget_facts,
    public.project_evidence_facts TO hermes_human_gate_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_human_gate_owner;

REVOKE ALL ON public.human_gate_authorization_assertions,
    public.human_gate_requests, public.project_resume_contexts,
    public.human_gate_decisions, public.project_waiting_records,
    public.human_gate_decision_applications
FROM PUBLIC;

REVOKE ALL ON FUNCTION public.hermes_human_gate_secret_guard(JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_reject_human_gate_immutable_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_reject_human_gate_application_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_human_gate_append_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_human_gate_begin_command(TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_human_gate_complete_command(TEXT,TEXT,BIGINT,JSONB,JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_request_human_gate(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,JSONB,TEXT,TEXT,JSONB,JSONB,TEXT,INTEGER,JSONB,TIMESTAMPTZ,BIGINT,JSONB,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_enter_project_waiting_for_gate(TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_submit_human_gate_decision(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,JSONB,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_apply_human_gate_decision(TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_expire_human_gate_request(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_cancel_human_gate_request(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_supersede_human_gate_request(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.hermes_request_human_gate(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,JSONB,TEXT,TEXT,JSONB,JSONB,TEXT,INTEGER,JSONB,TIMESTAMPTZ,BIGINT,JSONB,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
TO hermes_gate_request_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_submit_human_gate_decision(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,JSONB,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
TO hermes_gate_decision_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_enter_project_waiting_for_gate(TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_apply_human_gate_decision(TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_expire_human_gate_request(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_cancel_human_gate_request(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_supersede_human_gate_request(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
TO hermes_control_plane_runtime;

GRANT SELECT ON public.human_gate_requests, public.human_gate_decisions,
    public.project_waiting_records, public.project_resume_contexts,
    public.human_gate_decision_applications
TO hermes_read_only_runtime;

REVOKE CREATE ON SCHEMA public FROM hermes_gate_request_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_gate_decision_runtime;
