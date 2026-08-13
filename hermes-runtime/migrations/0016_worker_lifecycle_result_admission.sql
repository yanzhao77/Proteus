-- P2-4: Worker lifecycle, fenced result admission, minimal quarantine and settlement coupling.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_worker_execution_owner') THEN
        CREATE ROLE hermes_worker_execution_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

ALTER TABLE public.execution_request_current_states
    DROP CONSTRAINT IF EXISTS execution_request_current_states_request_state_check;
ALTER TABLE public.execution_request_current_states
    ADD CONSTRAINT execution_request_current_states_request_state_check
    CHECK (request_state IN ('QUEUED','LEASED','RUNNING','SUCCEEDED','FAILED','CANCELLED','TIMED_OUT'));
ALTER TABLE public.execution_request_current_states
    DROP CONSTRAINT IF EXISTS execution_request_current_states_check;
ALTER TABLE public.execution_request_current_states
    ADD CONSTRAINT execution_request_current_states_check
    CHECK (
        (request_state = 'QUEUED' AND current_lease_id IS NULL)
        OR
        (request_state IN ('LEASED','RUNNING') AND current_lease_id IS NOT NULL AND current_fencing_token > 0)
        OR
        (request_state IN ('SUCCEEDED','FAILED','CANCELLED','TIMED_OUT') AND current_lease_id IS NULL)
    );

ALTER TABLE public.execution_queue_current_states
    DROP CONSTRAINT IF EXISTS execution_queue_current_states_queue_state_check;
ALTER TABLE public.execution_queue_current_states
    ADD CONSTRAINT execution_queue_current_states_queue_state_check
    CHECK (queue_state IN ('PENDING','LEASED','TERMINAL'));
ALTER TABLE public.execution_queue_current_states
    DROP CONSTRAINT IF EXISTS execution_queue_current_states_check;
ALTER TABLE public.execution_queue_current_states
    ADD CONSTRAINT execution_queue_current_states_check
    CHECK (
        (queue_state = 'PENDING' AND current_lease_id IS NULL)
        OR
        (queue_state = 'LEASED' AND current_lease_id IS NOT NULL)
        OR
        (queue_state = 'TERMINAL' AND current_lease_id IS NULL)
    );

ALTER TABLE public.agent_runs
    DROP CONSTRAINT IF EXISTS agent_runs_status_check;
ALTER TABLE public.agent_runs
    ADD CONSTRAINT agent_runs_status_check
    CHECK (status IN ('ADMITTED','RUNNING','COMPLETED','SUCCEEDED','FAILED','INVALIDATED','EXPIRED'));
ALTER TABLE public.agent_runs
    ADD COLUMN IF NOT EXISTS execution_request_id TEXT REFERENCES public.execution_requests(execution_request_id),
    ADD COLUMN IF NOT EXISTS execution_attempt BIGINT CHECK (execution_attempt IS NULL OR execution_attempt >= 1),
    ADD COLUMN IF NOT EXISTS lease_id TEXT REFERENCES public.execution_leases(lease_id),
    ADD COLUMN IF NOT EXISTS lease_version BIGINT CHECK (lease_version IS NULL OR lease_version >= 1),
    ADD COLUMN IF NOT EXISTS fencing_token BIGINT CHECK (fencing_token IS NULL OR fencing_token > 0),
    ADD COLUMN IF NOT EXISTS scheduler_id TEXT,
    ADD COLUMN IF NOT EXISTS scheduler_session_id TEXT,
    ADD COLUMN IF NOT EXISTS worker_template_id TEXT,
    ADD COLUMN IF NOT EXISTS worker_template_revision BIGINT CHECK (worker_template_revision IS NULL OR worker_template_revision >= 1),
    ADD COLUMN IF NOT EXISTS worker_template_content_hash TEXT CHECK (worker_template_content_hash IS NULL OR worker_template_content_hash LIKE 'sha256:%'),
    ADD COLUMN IF NOT EXISTS context_bundle_id TEXT REFERENCES public.context_bundles(bundle_id),
    ADD COLUMN IF NOT EXISTS context_manifest_hash TEXT CHECK (context_manifest_hash IS NULL OR context_manifest_hash LIKE 'sha256:%'),
    ADD COLUMN IF NOT EXISTS sandbox_profile_id TEXT REFERENCES public.sandbox_profiles(profile_id),
    ADD COLUMN IF NOT EXISTS sandbox_profile_hash TEXT CHECK (sandbox_profile_hash IS NULL OR sandbox_profile_hash LIKE 'sha256:%'),
    ADD COLUMN IF NOT EXISTS reservation_id TEXT REFERENCES public.resource_reservations(reservation_id),
    ADD COLUMN IF NOT EXISTS started_command_id TEXT REFERENCES public.command_receipts(command_id),
    ADD COLUMN IF NOT EXISTS finished_command_id TEXT REFERENCES public.command_receipts(command_id),
    ADD COLUMN IF NOT EXISTS invalidated_reason TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS agent_runs_one_current_worker_attempt
    ON public.agent_runs(execution_request_id, execution_attempt)
    WHERE run_kind = 'WORKER' AND status IN ('ADMITTED','RUNNING');

CREATE UNIQUE INDEX IF NOT EXISTS agent_runs_one_binding_per_worker_run
    ON public.agent_runs(run_id, execution_request_id, execution_attempt, lease_id, fencing_token)
    WHERE run_kind = 'WORKER' AND execution_request_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.execution_worker_assignments (
    assignment_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    execution_request_id TEXT NOT NULL REFERENCES public.execution_requests(execution_request_id),
    execution_attempt BIGINT NOT NULL CHECK (execution_attempt >= 1),
    lease_id TEXT NOT NULL REFERENCES public.execution_leases(lease_id),
    lease_version BIGINT NOT NULL CHECK (lease_version >= 1),
    fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
    scheduler_id TEXT NOT NULL,
    scheduler_session_id TEXT NOT NULL,
    worker_template_id TEXT NOT NULL,
    worker_template_revision BIGINT NOT NULL CHECK (worker_template_revision >= 1),
    worker_template_content_hash TEXT NOT NULL CHECK (worker_template_content_hash LIKE 'sha256:%'),
    worker_agent_identity TEXT NOT NULL,
    context_identity TEXT NOT NULL,
    context_bundle_id TEXT NOT NULL REFERENCES public.context_bundles(bundle_id),
    context_manifest_hash TEXT NOT NULL CHECK (context_manifest_hash LIKE 'sha256:%'),
    sandbox_profile_id TEXT NOT NULL REFERENCES public.sandbox_profiles(profile_id),
    sandbox_profile_hash TEXT NOT NULL CHECK (sandbox_profile_hash LIKE 'sha256:%'),
    reservation_id TEXT NOT NULL REFERENCES public.resource_reservations(reservation_id),
    assignment_state TEXT NOT NULL CHECK (assignment_state IN ('ASSIGNED','STARTED','INVALIDATED','TERMINAL')),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    payload_hash TEXT NOT NULL CHECK (payload_hash LIKE 'sha256:%'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_run_id TEXT REFERENCES public.agent_runs(run_id),
    started_at TIMESTAMPTZ,
    terminal_at TIMESTAMPTZ,
    terminal_reason TEXT,
    UNIQUE (execution_request_id, execution_attempt),
    UNIQUE (lease_id, fencing_token)
);

CREATE TABLE IF NOT EXISTS public.execution_artifact_candidates (
    candidate_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    execution_request_id TEXT NOT NULL REFERENCES public.execution_requests(execution_request_id),
    execution_attempt BIGINT NOT NULL CHECK (execution_attempt >= 1),
    run_id TEXT NOT NULL REFERENCES public.agent_runs(run_id),
    lease_id TEXT NOT NULL REFERENCES public.execution_leases(lease_id),
    fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
    artifact_kind TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (content_hash LIKE 'sha256:%'),
    storage_ref TEXT NOT NULL CHECK (storage_ref !~* '^(file|/|\\.\\.)'),
    size_bytes BIGINT NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
    media_type TEXT NOT NULL DEFAULT '',
    schema_ref TEXT NOT NULL DEFAULT '',
    provenance JSONB NOT NULL,
    payload_hash TEXT NOT NULL CHECK (payload_hash LIKE 'sha256:%'),
    admission_status TEXT NOT NULL CHECK (admission_status = 'ADMITTED'),
    command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, candidate_id),
    UNIQUE (execution_request_id, execution_attempt, payload_hash)
);

CREATE TABLE IF NOT EXISTS public.execution_evidence_candidates (
    candidate_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    execution_request_id TEXT NOT NULL REFERENCES public.execution_requests(execution_request_id),
    execution_attempt BIGINT NOT NULL CHECK (execution_attempt >= 1),
    run_id TEXT NOT NULL REFERENCES public.agent_runs(run_id),
    lease_id TEXT NOT NULL REFERENCES public.execution_leases(lease_id),
    fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
    evidence_type TEXT NOT NULL,
    schema_ref TEXT NOT NULL DEFAULT '',
    source_ref TEXT NOT NULL,
    source_hash TEXT NOT NULL CHECK (source_hash LIKE 'sha256:%'),
    observed_at TIMESTAMPTZ NOT NULL,
    payload_hash TEXT NOT NULL CHECK (payload_hash LIKE 'sha256:%'),
    admission_status TEXT NOT NULL CHECK (admission_status = 'ADMITTED'),
    command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, candidate_id),
    UNIQUE (execution_request_id, execution_attempt, payload_hash)
);

CREATE TABLE IF NOT EXISTS public.execution_usage_admissions (
    usage_id TEXT PRIMARY KEY REFERENCES public.resource_usage_records(usage_id),
    sample_id TEXT NOT NULL UNIQUE,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    reservation_id TEXT NOT NULL REFERENCES public.resource_reservations(reservation_id),
    execution_request_id TEXT NOT NULL REFERENCES public.execution_requests(execution_request_id),
    execution_attempt BIGINT NOT NULL CHECK (execution_attempt >= 1),
    run_id TEXT NOT NULL REFERENCES public.agent_runs(run_id),
    lease_id TEXT NOT NULL REFERENCES public.execution_leases(lease_id),
    fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
    worker_agent_identity TEXT NOT NULL,
    context_identity TEXT NOT NULL,
    interval_start TIMESTAMPTZ,
    interval_end TIMESTAMPTZ,
    payload_hash TEXT NOT NULL CHECK (payload_hash LIKE 'sha256:%'),
    command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (interval_start IS NULL OR interval_end IS NULL OR interval_end >= interval_start),
    UNIQUE (execution_request_id, execution_attempt, sample_id)
);

CREATE TABLE IF NOT EXISTS public.execution_results (
    result_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    execution_request_id TEXT NOT NULL REFERENCES public.execution_requests(execution_request_id),
    execution_attempt BIGINT NOT NULL CHECK (execution_attempt >= 1),
    run_id TEXT NOT NULL REFERENCES public.agent_runs(run_id),
    lease_id TEXT NOT NULL REFERENCES public.execution_leases(lease_id),
    fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
    worker_agent_identity TEXT NOT NULL,
    context_identity TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('SUCCEEDED','FAILED_TRANSIENT','FAILED_PERMANENT','CANCELLED')),
    error_classification TEXT NOT NULL,
    artifact_candidate_refs JSONB NOT NULL,
    evidence_candidate_refs JSONB NOT NULL,
    usage_sample_refs JSONB NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    adapter_identity TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    external_side_effect_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload_hash TEXT NOT NULL CHECK (payload_hash LIKE 'sha256:%'),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    completion_claim_id TEXT UNIQUE,
    settlement_id TEXT UNIQUE REFERENCES public.resource_settlements(settlement_id),
    release_command_id TEXT REFERENCES public.command_receipts(command_id),
    terminal_state TEXT NOT NULL CHECK (terminal_state IN ('SUCCEEDED','FAILED','CANCELLED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (finished_at >= started_at),
    UNIQUE (execution_request_id, execution_attempt),
    UNIQUE (run_id)
);

CREATE TABLE IF NOT EXISTS public.execution_quarantine_records (
    quarantine_id TEXT PRIMARY KEY,
    payload_kind TEXT NOT NULL CHECK (payload_kind IN ('ARTIFACT_CANDIDATE','EVIDENCE_CANDIDATE','USAGE_SAMPLE','EXECUTION_RESULT')),
    project_id TEXT NOT NULL,
    task_id TEXT,
    execution_request_id TEXT,
    execution_attempt BIGINT,
    run_id TEXT,
    submitted_lease_id TEXT,
    submitted_fencing_token BIGINT,
    observed_current_lease_id TEXT,
    observed_current_fencing_token BIGINT,
    worker_agent_identity TEXT,
    context_identity TEXT,
    reason_code TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK (payload_hash LIKE 'sha256:%'),
    safe_payload_envelope JSONB NOT NULL,
    source_command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    idempotency_key TEXT NOT NULL,
    event_id TEXT,
    processing_state TEXT NOT NULL CHECK (processing_state = 'P2_MINIMAL'),
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.execution_result_claim_links (
    result_id TEXT PRIMARY KEY REFERENCES public.execution_results(result_id),
    claim_id TEXT NOT NULL UNIQUE REFERENCES public.completion_claims(claim_id),
    run_id TEXT NOT NULL REFERENCES public.agent_runs(run_id),
    execution_request_id TEXT NOT NULL REFERENCES public.execution_requests(execution_request_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.execution_result_settlement_links (
    result_id TEXT PRIMARY KEY REFERENCES public.execution_results(result_id),
    reservation_id TEXT NOT NULL REFERENCES public.resource_reservations(reservation_id),
    settlement_id TEXT UNIQUE REFERENCES public.resource_settlements(settlement_id),
    release_command_id TEXT UNIQUE REFERENCES public.command_receipts(command_id),
    disposition TEXT NOT NULL CHECK (disposition IN ('SETTLED','RELEASED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.hermes_worker_execution_secret_guard(p_payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
    SELECT p_payload::text ~* '("(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value)"[[:space:]]*:|private key|sk-[A-Za-z0-9]{12,}|password=)'
$$;

CREATE OR REPLACE FUNCTION public.hermes_worker_forbidden_verdict_guard(p_payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
    SELECT p_payload::text ~* '"(verdict|task_status|mark_passed|mark_failed|new_state)"[[:space:]]*:'
$$;

CREATE OR REPLACE FUNCTION public.hermes_worker_accounting_status(
    p_account_id TEXT, p_force_hard_stop BOOLEAN DEFAULT false
) RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    warn_bp INTEGER;
    gate_bp INTEGER;
    hard_bp INTEGER;
    highest_ratio BIGINT;
    result TEXT;
BEGIN
    SELECT warn_basis_points, gate_basis_points, hard_stop_basis_points
    INTO warn_bp, gate_bp, hard_bp
    FROM public.resource_accounts
    WHERE account_id=p_account_id;

    SELECT COALESCE(max(CASE
        WHEN limit_amount=0 AND consumed_amount+reserved_amount=0 THEN 0
        WHEN limit_amount=0 THEN hard_bp
        ELSE (consumed_amount+reserved_amount)*10000/limit_amount
    END), 0) INTO highest_ratio
    FROM public.resource_balances
    WHERE account_id=p_account_id;

    result := CASE
        WHEN p_force_hard_stop OR highest_ratio >= hard_bp THEN 'HARD_STOP'
        WHEN highest_ratio >= gate_bp THEN 'GATE'
        WHEN highest_ratio >= warn_bp THEN 'WARN'
        ELSE 'NORMAL'
    END;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_reject_worker_execution_immutable_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'execution_artifact_candidates','execution_evidence_candidates',
        'execution_usage_admissions','execution_results',
        'execution_quarantine_records','execution_result_claim_links',
        'execution_result_settlement_links'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS worker_execution_immutable ON public.%I', table_name);
        EXECUTE format(
            'CREATE TRIGGER worker_execution_immutable BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_worker_execution_immutable_change()',
            table_name
        );
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_guard_p2_agent_run_update()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'agent_runs is authority-preserved';
    END IF;
    IF NEW.run_id <> OLD.run_id OR NEW.project_id <> OLD.project_id
       OR NEW.task_id <> OLD.task_id OR NEW.run_kind <> OLD.run_kind
       OR NEW.agent_identity <> OLD.agent_identity
       OR NEW.context_identity <> OLD.context_identity
       OR NEW.created_by <> OLD.created_by OR NEW.command_id <> OLD.command_id
       OR NEW.created_at <> OLD.created_at OR NEW.version <> OLD.version + 1
       OR NEW.execution_request_id IS DISTINCT FROM OLD.execution_request_id
       OR NEW.execution_attempt IS DISTINCT FROM OLD.execution_attempt
       OR NEW.lease_id IS DISTINCT FROM OLD.lease_id
       OR NEW.fencing_token IS DISTINCT FROM OLD.fencing_token
       OR NEW.scheduler_id IS DISTINCT FROM OLD.scheduler_id
       OR NEW.scheduler_session_id IS DISTINCT FROM OLD.scheduler_session_id
       OR NEW.worker_template_id IS DISTINCT FROM OLD.worker_template_id
       OR NEW.worker_template_revision IS DISTINCT FROM OLD.worker_template_revision
       OR NEW.context_bundle_id IS DISTINCT FROM OLD.context_bundle_id
       OR NEW.sandbox_profile_id IS DISTINCT FROM OLD.sandbox_profile_id
       OR NEW.reservation_id IS DISTINCT FROM OLD.reservation_id
    THEN
        RAISE EXCEPTION 'invalid AgentRun authority transition';
    END IF;
    IF OLD.status IN ('SUCCEEDED','FAILED','INVALIDATED','EXPIRED') THEN
        RAISE EXCEPTION 'terminal AgentRun cannot change';
    END IF;
    IF NOT (
        (OLD.status='ADMITTED' AND NEW.status IN ('RUNNING','INVALIDATED','EXPIRED'))
        OR (OLD.status='RUNNING' AND NEW.status IN ('SUCCEEDED','FAILED','INVALIDATED','EXPIRED'))
        OR (OLD.status='COMPLETED' AND NEW.status='INVALIDATED')
    ) THEN
        RAISE EXCEPTION 'invalid AgentRun authority transition';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS agent_runs_guarded_update ON public.agent_runs;
CREATE TRIGGER agent_runs_guarded_update
BEFORE UPDATE OR DELETE ON public.agent_runs
FOR EACH ROW EXECUTE FUNCTION public.hermes_guard_p2_agent_run_update();

CREATE OR REPLACE FUNCTION public.hermes_worker_complete_command(
    p_command_id TEXT,
    p_status TEXT,
    p_result_code TEXT,
    p_response JSONB,
    p_event_ids JSONB DEFAULT '[]'::jsonb,
    p_target_version BIGINT DEFAULT NULL
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    UPDATE public.command_receipts
    SET status=p_status,
        result=jsonb_build_object(
            'command_id', p_command_id,
            'status', p_status,
            'result_code', p_result_code,
            'target_version', p_target_version,
            'event_ids', p_event_ids,
            'response', p_response
        ),
        completed_at=clock_timestamp()
    WHERE command_id=p_command_id AND status='PROCESSING';
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_worker_append_event(
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
    INSERT INTO public.event_log(
        event_id, event_type, schema_version, producer_type, producer_id,
        project_id, partition_key, command_id, correlation_id, causation_id,
        task_id, payload
    ) VALUES (
        v_event_id, p_event_type, '1.0', p_actor_type, p_actor_id,
        p_project_id, p_project_id, p_command_id, p_correlation_id,
        p_causation_id, p_task_id, p_payload
    ) RETURNING sequence INTO v_sequence;
    IF p_fault_point = 'after_event_before_outbox' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_event_before_outbox';
    END IF;
    INSERT INTO public.outbox_messages(message_id, event_id, topic, partition_key, sequence, payload)
    VALUES ('msg-' || gen_random_uuid()::text, v_event_id, 'hermes.runtime.events',
            p_project_id, v_sequence, p_payload);
    RETURN v_event_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_quarantine_worker_payload(
    p_project_id TEXT,
    p_task_id TEXT,
    p_execution_request_id TEXT,
    p_execution_attempt BIGINT,
    p_run_id TEXT,
    p_submitted_lease_id TEXT,
    p_submitted_fencing_token BIGINT,
    p_worker_agent_identity TEXT,
    p_context_identity TEXT,
    p_payload_kind TEXT,
    p_reason_code TEXT,
    p_payload_hash TEXT,
    p_safe_payload_envelope JSONB,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    request_row public.execution_request_current_states%ROWTYPE;
    v_event_id TEXT;
    v_quarantine_id TEXT;
    response JSONB;
BEGIN
    IF public.hermes_worker_execution_secret_guard(p_safe_payload_envelope) THEN
        p_safe_payload_envelope := jsonb_build_object('payload_hash', p_payload_hash, 'redacted', true);
    END IF;
    SELECT * INTO request_row
    FROM public.execution_request_current_states
    WHERE execution_request_id=p_execution_request_id;
    v_quarantine_id := 'quarantine-' || gen_random_uuid()::text;
    v_event_id := public.hermes_worker_append_event(
        p_project_id, p_task_id, p_command_id, 'execution.result_quarantined',
        p_actor_type, p_actor_id, p_command_id, p_command_id,
        jsonb_build_object(
            'quarantine_id', v_quarantine_id,
            'payload_kind', p_payload_kind,
            'execution_request_id', p_execution_request_id,
            'execution_attempt', p_execution_attempt,
            'run_id', p_run_id,
            'submitted_lease_id', p_submitted_lease_id,
            'submitted_fencing_token', p_submitted_fencing_token,
            'observed_current_lease_id', request_row.current_lease_id,
            'observed_current_fencing_token', request_row.current_fencing_token,
            'reason_code', p_reason_code,
            'payload_hash', p_payload_hash
        ),
        p_fault_point
    );
    INSERT INTO public.execution_quarantine_records(
        quarantine_id, payload_kind, project_id, task_id, execution_request_id,
        execution_attempt, run_id, submitted_lease_id, submitted_fencing_token,
        observed_current_lease_id, observed_current_fencing_token,
        worker_agent_identity, context_identity, reason_code, payload_hash,
        safe_payload_envelope, source_command_id, idempotency_key,
        processing_state, event_id
    ) VALUES (
        v_quarantine_id, p_payload_kind, p_project_id, p_task_id, p_execution_request_id,
        p_execution_attempt, p_run_id, p_submitted_lease_id, p_submitted_fencing_token,
        request_row.current_lease_id, request_row.current_fencing_token,
        p_worker_agent_identity, p_context_identity, p_reason_code, p_payload_hash,
        p_safe_payload_envelope, p_command_id, p_idempotency_key,
        'P2_MINIMAL', v_event_id
    );
    IF p_fault_point = 'after_quarantine_write' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_quarantine_write';
    END IF;
    response := jsonb_build_object(
        'result_code', p_reason_code,
        'quarantined', true,
        'quarantine_id', v_quarantine_id,
        'event_ids', jsonb_build_array(v_event_id)
    );
    PERFORM public.hermes_worker_complete_command(
        p_command_id, 'REJECTED', p_reason_code, response, jsonb_build_array(v_event_id), NULL
    );
    RETURN response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_validate_current_worker_execution(
    p_project_id TEXT,
    p_execution_request_id TEXT,
    p_execution_attempt BIGINT,
    p_run_id TEXT,
    p_lease_id TEXT,
    p_lease_version BIGINT,
    p_fencing_token BIGINT,
    p_worker_agent_identity TEXT,
    p_context_identity TEXT,
    p_observed_request_version BIGINT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    request_row public.execution_request_current_states%ROWTYPE;
    lease_row public.execution_leases%ROWTYPE;
    run_row public.agent_runs%ROWTYPE;
    current_clock TIMESTAMPTZ := clock_timestamp();
    lock_count INTEGER;
    expected_lock_count INTEGER;
    reason TEXT := 'EXECUTION_CURRENT';
    valid BOOLEAN := true;
BEGIN
    SELECT * INTO request_row
    FROM public.execution_request_current_states
    WHERE execution_request_id=p_execution_request_id
    FOR UPDATE;
    SELECT * INTO lease_row
    FROM public.execution_leases
    WHERE lease_id=p_lease_id AND execution_request_id=p_execution_request_id
    FOR UPDATE;
    SELECT * INTO run_row
    FROM public.agent_runs
    WHERE run_id=p_run_id
    FOR UPDATE;

    IF NOT FOUND OR run_row.run_id IS NULL THEN
        valid := false; reason := 'AGENT_RUN_NOT_FOUND';
    ELSIF request_row.execution_request_id IS NULL OR request_row.request_state <> 'RUNNING' THEN
        valid := false; reason := 'EXECUTION_REQUEST_NOT_RUNNING';
    ELSIF run_row.status <> 'RUNNING' THEN
        valid := false; reason := 'AGENT_RUN_NOT_ACTIVE';
    ELSIF run_row.project_id <> p_project_id OR run_row.execution_request_id <> p_execution_request_id
       OR run_row.execution_attempt <> p_execution_attempt OR run_row.lease_id <> p_lease_id
       THEN
        valid := false; reason := 'AGENT_RUN_SCOPE_MISMATCH';
    ELSIF run_row.agent_identity <> p_worker_agent_identity THEN
        valid := false; reason := 'WORKER_IDENTITY_MISMATCH';
    ELSIF run_row.context_identity <> p_context_identity THEN
        valid := false; reason := 'CONTEXT_IDENTITY_MISMATCH';
    ELSIF lease_row.lease_id IS NULL OR request_row.current_lease_id <> p_lease_id
       OR lease_row.lease_state <> 'ACTIVE' THEN
        valid := false; reason := 'LEASE_NOT_CURRENT';
    ELSIF lease_row.expires_at <= current_clock THEN
        valid := false; reason := 'LEASE_EXPIRED';
    ELSIF lease_row.lease_version <> p_lease_version THEN
        valid := false; reason := 'LEASE_VERSION_CONFLICT';
    ELSIF lease_row.fencing_token <> p_fencing_token
       OR request_row.current_fencing_token <> p_fencing_token THEN
        valid := false; reason := 'FENCING_TOKEN_STALE';
    ELSIF request_row.request_version <> p_observed_request_version THEN
        valid := false; reason := 'EXPECTED_VERSION_CONFLICT';
    ELSE
        SELECT count(*)::INTEGER INTO lock_count
        FROM public.execution_lock_ownerships l
        WHERE l.lease_id=p_lease_id
          AND l.fencing_token=p_fencing_token
          AND l.lock_state='ACTIVE'
          AND l.expires_at > current_clock;
        SELECT COALESCE(jsonb_array_length(lease_row.lock_refs),0) INTO expected_lock_count;
        IF lock_count <> expected_lock_count THEN
            valid := false; reason := 'EXECUTION_LOCK_OWNERSHIP_LOST';
        END IF;
    END IF;

    RETURN jsonb_build_object(
        'valid', valid,
        'reason_code', reason,
        'request_version', COALESCE(request_row.request_version, 0),
        'current_lease_id', request_row.current_lease_id,
        'current_fencing_token', COALESCE(request_row.current_fencing_token, 0),
        'lease_version', COALESCE(lease_row.lease_version, 0),
        'run_status', run_row.status
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_start_worker_run(
    p_project_id TEXT,
    p_execution_request_id TEXT,
    p_execution_attempt BIGINT,
    p_run_id TEXT,
    p_lease_id TEXT,
    p_lease_version BIGINT,
    p_fencing_token BIGINT,
    p_scheduler_id TEXT,
    p_scheduler_session_id TEXT,
    p_worker_agent_identity TEXT,
    p_context_identity TEXT,
    p_worker_template_id TEXT,
    p_worker_template_revision BIGINT,
    p_worker_template_content_hash TEXT,
    p_context_bundle_id TEXT,
    p_context_manifest_hash TEXT,
    p_sandbox_profile_id TEXT,
    p_sandbox_profile_hash TEXT,
    p_reservation_id TEXT,
    p_observed_request_version BIGINT,
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
    request_row public.execution_request_current_states%ROWTYPE;
    snapshot_row public.execution_requests%ROWTYPE;
    lease_row public.execution_leases%ROWTYPE;
    template_availability public.worker_template_availability%ROWTYPE;
    reservation_row public.resource_reservations%ROWTYPE;
    existing_run public.agent_runs%ROWTYPE;
    current_clock TIMESTAMPTZ := clock_timestamp();
    event_id TEXT;
    response JSONB;
BEGIN
    IF p_actor_type <> 'worker' OR p_actor_id <> p_worker_agent_identity THEN
        RAISE EXCEPTION 'WORKER_IDENTITY_MISMATCH';
    END IF;
    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key, request_hash, status, result
    ) VALUES (
        p_command_id, p_project_id, 'execution.start_run', p_idempotency_key,
        p_payload_hash, 'PROCESSING', '{}'::jsonb
    ) ON CONFLICT DO NOTHING;
    SELECT * INTO command_row
    FROM public.command_receipts
    WHERE project_id=p_project_id AND command_type='execution.start_run'
      AND idempotency_key=p_idempotency_key
    FOR UPDATE;
    IF NOT FOUND OR command_row.request_hash <> p_payload_hash THEN
        RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT';
    END IF;
    IF command_row.status = 'APPLIED' THEN
        RETURN command_row.result->'response';
    END IF;
    IF p_fault_point = 'after_receipt_placeholder' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_receipt_placeholder';
    END IF;

    SELECT * INTO snapshot_row
    FROM public.execution_requests
    WHERE execution_request_id=p_execution_request_id AND project_id=p_project_id
    ;
    SELECT * INTO request_row
    FROM public.execution_request_current_states
    WHERE execution_request_id=p_execution_request_id AND project_id=p_project_id
    FOR UPDATE;
    SELECT * INTO lease_row
    FROM public.execution_leases
    WHERE lease_id=p_lease_id AND execution_request_id=p_execution_request_id
    FOR UPDATE;
    IF snapshot_row.execution_request_id IS NULL OR request_row.execution_request_id IS NULL THEN
        RAISE EXCEPTION 'EXECUTION_REQUEST_NOT_RUNNING';
    END IF;
    IF request_row.request_state <> 'LEASED' THEN
        RAISE EXCEPTION 'EXECUTION_REQUEST_NOT_LEASED';
    END IF;
    IF request_row.request_version <> p_observed_request_version THEN
        RAISE EXCEPTION 'EXPECTED_VERSION_CONFLICT';
    END IF;
    IF request_row.current_lease_id <> p_lease_id OR lease_row.lease_id IS NULL
       OR lease_row.lease_state <> 'ACTIVE' THEN
        RAISE EXCEPTION 'LEASE_NOT_CURRENT';
    END IF;
    IF lease_row.expires_at <= current_clock THEN
        RAISE EXCEPTION 'LEASE_EXPIRED';
    END IF;
    IF lease_row.scheduler_id <> p_scheduler_id OR lease_row.scheduler_session_id <> p_scheduler_session_id THEN
        RAISE EXCEPTION 'LEASE_OWNER_MISMATCH';
    END IF;
    IF lease_row.fencing_token <> p_fencing_token OR request_row.current_fencing_token <> p_fencing_token THEN
        RAISE EXCEPTION 'FENCING_TOKEN_STALE';
    END IF;
    IF lease_row.lease_version <> p_lease_version THEN
        RAISE EXCEPTION 'LEASE_VERSION_CONFLICT';
    END IF;
    IF snapshot_row.worker_template_id <> p_worker_template_id
       OR snapshot_row.worker_template_revision <> p_worker_template_revision
       OR snapshot_row.worker_template_content_hash <> p_worker_template_content_hash
       OR snapshot_row.context_bundle_id <> p_context_bundle_id
       OR snapshot_row.context_manifest_hash <> p_context_manifest_hash
       OR snapshot_row.sandbox_profile_id <> p_sandbox_profile_id
       OR snapshot_row.sandbox_profile_hash <> p_sandbox_profile_hash
       OR snapshot_row.reservation_id <> p_reservation_id THEN
        RAISE EXCEPTION 'AGENT_RUN_SCOPE_MISMATCH';
    END IF;
    SELECT * INTO template_availability
    FROM public.worker_template_availability
    WHERE template_id=p_worker_template_id
      AND revision=p_worker_template_revision
      AND availability_version=snapshot_row.worker_template_availability_version
    ;
    IF NOT FOUND OR template_availability.availability_status <> 'AVAILABLE'
       OR template_availability.admission_status <> 'ADMISSIBLE' THEN
        RAISE EXCEPTION 'WORKER_TEMPLATE_UNAVAILABLE';
    END IF;
    SELECT * INTO reservation_row
    FROM public.resource_reservations
    WHERE reservation_id=p_reservation_id AND project_id=p_project_id
    ;
    IF NOT FOUND OR reservation_row.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'RESOURCE_RESERVATION_NOT_ACTIVE';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.agent_runs
        WHERE execution_request_id=p_execution_request_id
          AND execution_attempt=p_execution_attempt
          AND run_kind='WORKER'
          AND status IN ('ADMITTED','RUNNING')
          AND run_id <> p_run_id
    ) THEN
        RAISE EXCEPTION 'AGENT_RUN_ALREADY_ACTIVE';
    END IF;
    SELECT * INTO existing_run FROM public.agent_runs WHERE run_id=p_run_id FOR UPDATE;
    IF existing_run.run_id IS NOT NULL THEN
        IF existing_run.execution_request_id = p_execution_request_id
           AND existing_run.execution_attempt = p_execution_attempt
           AND existing_run.status = 'RUNNING' THEN
            RETURN command_row.result->'response';
        END IF;
        RAISE EXCEPTION 'AGENT_RUN_SCOPE_MISMATCH';
    END IF;
    IF p_fault_point = 'after_authority_validation' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_authority_validation';
    END IF;

    INSERT INTO public.agent_runs(
        run_id, project_id, task_id, run_kind, agent_identity, context_identity,
        status, created_by, command_id, version, execution_request_id,
        execution_attempt, lease_id, lease_version, fencing_token, scheduler_id,
        scheduler_session_id, worker_template_id, worker_template_revision,
        worker_template_content_hash, context_bundle_id, context_manifest_hash,
        sandbox_profile_id, sandbox_profile_hash, reservation_id, started_command_id
    ) VALUES (
        p_run_id, p_project_id, snapshot_row.task_id, 'WORKER',
        p_worker_agent_identity, p_context_identity, 'RUNNING',
        p_actor_id, p_command_id, 1, p_execution_request_id, p_execution_attempt,
        p_lease_id, p_lease_version, p_fencing_token, p_scheduler_id,
        p_scheduler_session_id, p_worker_template_id, p_worker_template_revision,
        p_worker_template_content_hash, p_context_bundle_id, p_context_manifest_hash,
        p_sandbox_profile_id, p_sandbox_profile_hash, p_reservation_id, p_command_id
    );
    INSERT INTO public.execution_worker_assignments(
        assignment_id, project_id, task_id, execution_request_id, execution_attempt,
        lease_id, lease_version, fencing_token, scheduler_id, scheduler_session_id,
        worker_template_id, worker_template_revision, worker_template_content_hash,
        worker_agent_identity, context_identity, context_bundle_id, context_manifest_hash,
        sandbox_profile_id, sandbox_profile_hash, reservation_id, assignment_state,
        command_id, payload_hash, started_run_id, started_at
    ) VALUES (
        'assign-' || gen_random_uuid()::text, p_project_id, snapshot_row.task_id,
        p_execution_request_id, p_execution_attempt, p_lease_id, p_lease_version,
        p_fencing_token, p_scheduler_id, p_scheduler_session_id,
        p_worker_template_id, p_worker_template_revision, p_worker_template_content_hash,
        p_worker_agent_identity, p_context_identity, p_context_bundle_id,
        p_context_manifest_hash, p_sandbox_profile_id, p_sandbox_profile_hash,
        p_reservation_id, 'STARTED', p_command_id, p_payload_hash, p_run_id, current_clock
    );
    IF p_fault_point = 'after_agent_run_created' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_agent_run_created';
    END IF;
    UPDATE public.execution_request_current_states
    SET request_state='RUNNING',
        request_version=request_version + 1,
        updated_at=current_clock,
        command_id=p_command_id
    WHERE execution_request_id=p_execution_request_id;
    UPDATE public.tasks
    SET state='RUNNING', version=version + 1, updated_at=current_clock
    WHERE task_id=snapshot_row.task_id
      AND project_id=p_project_id
      AND state='READY';
    IF NOT FOUND AND NOT EXISTS (
        SELECT 1 FROM public.tasks
        WHERE task_id=snapshot_row.task_id
          AND project_id=p_project_id
          AND state='RUNNING'
    ) THEN
        RAISE EXCEPTION 'EXECUTION_REQUEST_NOT_RUNNING';
    END IF;
    IF p_fault_point = 'after_request_running' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_request_running';
    END IF;
    event_id := public.hermes_worker_append_event(
        p_project_id, snapshot_row.task_id, p_command_id, 'execution.running',
        p_actor_type, p_actor_id, p_command_id, lease_row.acquired_event_id,
        jsonb_build_object(
            'execution_request_id', p_execution_request_id,
            'execution_attempt', p_execution_attempt,
            'run_id', p_run_id,
            'lease_id', p_lease_id,
            'lease_version', p_lease_version,
            'fencing_token', p_fencing_token,
            'worker_agent_identity', p_worker_agent_identity,
            'context_identity', p_context_identity,
            'request_version', request_row.request_version + 1
        ),
        p_fault_point
    );
    response := jsonb_build_object(
        'result_code', 'EXECUTION_RUN_STARTED',
        'execution_request_id', p_execution_request_id,
        'execution_attempt', p_execution_attempt,
        'run_id', p_run_id,
        'request_state', 'RUNNING',
        'request_version', request_row.request_version + 1,
        'lease_id', p_lease_id,
        'fencing_token', p_fencing_token,
        'event_ids', jsonb_build_array(event_id),
        'deduplicated', false
    );
    PERFORM public.hermes_worker_complete_command(
        p_command_id, 'APPLIED', 'EXECUTION_RUN_STARTED',
        response, jsonb_build_array(event_id), request_row.request_version + 1
    );
    IF p_fault_point = 'after_receipt_before_commit' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_receipt_before_commit';
    END IF;
    RETURN response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_record_execution_artifact_candidate(
    p_project_id TEXT,
    p_execution_request_id TEXT,
    p_execution_attempt BIGINT,
    p_run_id TEXT,
    p_lease_id TEXT,
    p_lease_version BIGINT,
    p_fencing_token BIGINT,
    p_worker_agent_identity TEXT,
    p_context_identity TEXT,
    p_observed_request_version BIGINT,
    p_candidate_id TEXT,
    p_artifact_kind TEXT,
    p_content_hash TEXT,
    p_storage_ref TEXT,
    p_size_bytes BIGINT,
    p_media_type TEXT,
    p_schema_ref TEXT,
    p_payload JSONB,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    command_row public.command_receipts%ROWTYPE;
    validation JSONB;
    run_row public.agent_runs%ROWTYPE;
    event_id TEXT;
    response JSONB;
BEGIN
    IF p_actor_type <> 'worker' OR p_actor_id <> p_worker_agent_identity THEN
        RAISE EXCEPTION 'WORKER_IDENTITY_MISMATCH';
    END IF;
    IF public.hermes_worker_execution_secret_guard(p_payload) THEN
        RAISE EXCEPTION 'SECRET_VALUE_FORBIDDEN';
    END IF;
    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key, request_hash, status, result
    ) VALUES (
        p_command_id, p_project_id, 'execution.record_artifact_candidate',
        p_idempotency_key, p_payload_hash, 'PROCESSING', '{}'::jsonb
    ) ON CONFLICT DO NOTHING;
    SELECT * INTO command_row
    FROM public.command_receipts
    WHERE project_id=p_project_id AND command_type='execution.record_artifact_candidate'
      AND idempotency_key=p_idempotency_key
    FOR UPDATE;
    IF NOT FOUND OR command_row.request_hash <> p_payload_hash THEN
        RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT';
    END IF;
    IF command_row.status = 'APPLIED' THEN
        RETURN command_row.result->'response';
    END IF;
    validation := public.hermes_validate_current_worker_execution(
        p_project_id, p_execution_request_id, p_execution_attempt, p_run_id,
        p_lease_id, p_lease_version, p_fencing_token, p_worker_agent_identity,
        p_context_identity, p_observed_request_version
    );
    IF NOT (validation->>'valid')::BOOLEAN THEN
        RETURN public.hermes_quarantine_worker_payload(
            p_project_id, NULL, p_execution_request_id, p_execution_attempt, p_run_id,
            p_lease_id, p_fencing_token, p_worker_agent_identity, p_context_identity,
            'ARTIFACT_CANDIDATE', validation->>'reason_code', p_payload_hash,
            jsonb_build_object('payload_hash', p_payload_hash, 'candidate_id', p_candidate_id),
            p_command_id, p_idempotency_key, p_actor_type, p_actor_id, p_fault_point
        );
    END IF;
    SELECT * INTO run_row FROM public.agent_runs WHERE run_id=p_run_id;
    IF p_storage_ref ~* '^(file|/|\\.\\.)' THEN
        RAISE EXCEPTION 'ARTIFACT_REF_UNSAFE';
    END IF;
    INSERT INTO public.execution_artifact_candidates(
        candidate_id, project_id, task_id, execution_request_id, execution_attempt,
        run_id, lease_id, fencing_token, artifact_kind, content_hash, storage_ref,
        size_bytes, media_type, schema_ref, provenance, payload_hash,
        admission_status, command_id
    ) VALUES (
        p_candidate_id, p_project_id, run_row.task_id, p_execution_request_id,
        p_execution_attempt, p_run_id, p_lease_id, p_fencing_token, p_artifact_kind,
        p_content_hash, p_storage_ref, COALESCE(p_size_bytes,0),
        COALESCE(p_media_type,''), COALESCE(p_schema_ref,''),
        jsonb_build_object(
            'run_id', p_run_id,
            'worker_agent_identity', p_worker_agent_identity,
            'context_identity', p_context_identity,
            'lease_id', p_lease_id,
            'fencing_token', p_fencing_token
        ),
        p_payload_hash, 'ADMITTED', p_command_id
    ) ON CONFLICT (candidate_id) DO NOTHING;
    IF NOT FOUND THEN
        PERFORM 1 FROM public.execution_artifact_candidates
        WHERE candidate_id=p_candidate_id AND payload_hash=p_payload_hash;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT';
        END IF;
    END IF;
    IF p_fault_point = 'after_candidate_write' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_candidate_write';
    END IF;
    event_id := public.hermes_worker_append_event(
        p_project_id, run_row.task_id, p_command_id, 'execution.artifact_candidate_recorded',
        p_actor_type, p_actor_id, p_command_id, p_run_id,
        jsonb_build_object(
            'candidate_id', p_candidate_id,
            'execution_request_id', p_execution_request_id,
            'execution_attempt', p_execution_attempt,
            'run_id', p_run_id,
            'lease_id', p_lease_id,
            'fencing_token', p_fencing_token,
            'content_hash', p_content_hash,
            'payload_hash', p_payload_hash
        ),
        p_fault_point
    );
    response := jsonb_build_object(
        'result_code', 'EXECUTION_ARTIFACT_CANDIDATE_RECORDED',
        'candidate_id', p_candidate_id,
        'event_ids', jsonb_build_array(event_id)
    );
    PERFORM public.hermes_worker_complete_command(
        p_command_id, 'APPLIED', 'EXECUTION_ARTIFACT_CANDIDATE_RECORDED',
        response, jsonb_build_array(event_id), NULL
    );
    RETURN response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_record_execution_evidence_candidate(
    p_project_id TEXT,
    p_execution_request_id TEXT,
    p_execution_attempt BIGINT,
    p_run_id TEXT,
    p_lease_id TEXT,
    p_lease_version BIGINT,
    p_fencing_token BIGINT,
    p_worker_agent_identity TEXT,
    p_context_identity TEXT,
    p_observed_request_version BIGINT,
    p_candidate_id TEXT,
    p_evidence_type TEXT,
    p_schema_ref TEXT,
    p_source_ref TEXT,
    p_source_hash TEXT,
    p_observed_at TIMESTAMPTZ,
    p_payload JSONB,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    command_row public.command_receipts%ROWTYPE;
    validation JSONB;
    run_row public.agent_runs%ROWTYPE;
    event_id TEXT;
    response JSONB;
BEGIN
    IF p_actor_type <> 'worker' OR p_actor_id <> p_worker_agent_identity THEN
        RAISE EXCEPTION 'WORKER_IDENTITY_MISMATCH';
    END IF;
    IF public.hermes_worker_execution_secret_guard(p_payload) THEN
        RAISE EXCEPTION 'SECRET_VALUE_FORBIDDEN';
    END IF;
    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key, request_hash, status, result
    ) VALUES (
        p_command_id, p_project_id, 'execution.record_evidence_candidate',
        p_idempotency_key, p_payload_hash, 'PROCESSING', '{}'::jsonb
    ) ON CONFLICT DO NOTHING;
    SELECT * INTO command_row
    FROM public.command_receipts
    WHERE project_id=p_project_id AND command_type='execution.record_evidence_candidate'
      AND idempotency_key=p_idempotency_key
    FOR UPDATE;
    IF NOT FOUND OR command_row.request_hash <> p_payload_hash THEN
        RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT';
    END IF;
    IF command_row.status = 'APPLIED' THEN
        RETURN command_row.result->'response';
    END IF;
    validation := public.hermes_validate_current_worker_execution(
        p_project_id, p_execution_request_id, p_execution_attempt, p_run_id,
        p_lease_id, p_lease_version, p_fencing_token, p_worker_agent_identity,
        p_context_identity, p_observed_request_version
    );
    IF NOT (validation->>'valid')::BOOLEAN THEN
        RETURN public.hermes_quarantine_worker_payload(
            p_project_id, NULL, p_execution_request_id, p_execution_attempt, p_run_id,
            p_lease_id, p_fencing_token, p_worker_agent_identity, p_context_identity,
            'EVIDENCE_CANDIDATE', validation->>'reason_code', p_payload_hash,
            jsonb_build_object('payload_hash', p_payload_hash, 'candidate_id', p_candidate_id),
            p_command_id, p_idempotency_key, p_actor_type, p_actor_id, p_fault_point
        );
    END IF;
    SELECT * INTO run_row FROM public.agent_runs WHERE run_id=p_run_id;
    INSERT INTO public.execution_evidence_candidates(
        candidate_id, project_id, task_id, execution_request_id, execution_attempt,
        run_id, lease_id, fencing_token, evidence_type, schema_ref, source_ref,
        source_hash, observed_at, payload_hash, admission_status, command_id
    ) VALUES (
        p_candidate_id, p_project_id, run_row.task_id, p_execution_request_id,
        p_execution_attempt, p_run_id, p_lease_id, p_fencing_token, p_evidence_type,
        COALESCE(p_schema_ref,''), p_source_ref, p_source_hash,
        COALESCE(p_observed_at, clock_timestamp()), p_payload_hash, 'ADMITTED',
        p_command_id
    ) ON CONFLICT (candidate_id) DO NOTHING;
    IF NOT FOUND THEN
        PERFORM 1 FROM public.execution_evidence_candidates
        WHERE candidate_id=p_candidate_id AND payload_hash=p_payload_hash;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT';
        END IF;
    END IF;
    IF p_fault_point = 'after_candidate_write' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_candidate_write';
    END IF;
    event_id := public.hermes_worker_append_event(
        p_project_id, run_row.task_id, p_command_id, 'execution.evidence_candidate_recorded',
        p_actor_type, p_actor_id, p_command_id, p_run_id,
        jsonb_build_object(
            'candidate_id', p_candidate_id,
            'execution_request_id', p_execution_request_id,
            'execution_attempt', p_execution_attempt,
            'run_id', p_run_id,
            'lease_id', p_lease_id,
            'fencing_token', p_fencing_token,
            'source_hash', p_source_hash,
            'payload_hash', p_payload_hash
        ),
        p_fault_point
    );
    response := jsonb_build_object(
        'result_code', 'EXECUTION_EVIDENCE_CANDIDATE_RECORDED',
        'candidate_id', p_candidate_id,
        'event_ids', jsonb_build_array(event_id)
    );
    PERFORM public.hermes_worker_complete_command(
        p_command_id, 'APPLIED', 'EXECUTION_EVIDENCE_CANDIDATE_RECORDED',
        response, jsonb_build_array(event_id), NULL
    );
    RETURN response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_record_execution_usage_sample(
    p_project_id TEXT,
    p_execution_request_id TEXT,
    p_execution_attempt BIGINT,
    p_run_id TEXT,
    p_lease_id TEXT,
    p_lease_version BIGINT,
    p_fencing_token BIGINT,
    p_worker_agent_identity TEXT,
    p_context_identity TEXT,
    p_observed_request_version BIGINT,
    p_usage_id TEXT,
    p_sample_id TEXT,
    p_reservation_id TEXT,
    p_currency TEXT,
    p_amounts JSONB,
    p_interval_start TIMESTAMPTZ,
    p_interval_end TIMESTAMPTZ,
    p_payload JSONB,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    command_row public.command_receipts%ROWTYPE;
    validation JSONB;
    run_row public.agent_runs%ROWTYPE;
    reservation_row public.resource_reservations%ROWTYPE;
    item RECORD;
    event_id TEXT;
    response JSONB;
BEGIN
    IF p_actor_type <> 'worker' OR p_actor_id <> p_worker_agent_identity THEN
        RAISE EXCEPTION 'WORKER_IDENTITY_MISMATCH';
    END IF;
    IF public.hermes_worker_execution_secret_guard(p_payload) THEN
        RAISE EXCEPTION 'SECRET_VALUE_FORBIDDEN';
    END IF;
    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key, request_hash, status, result
    ) VALUES (
        p_command_id, p_project_id, 'execution.record_usage_sample',
        p_idempotency_key, p_payload_hash, 'PROCESSING', '{}'::jsonb
    ) ON CONFLICT DO NOTHING;
    SELECT * INTO command_row
    FROM public.command_receipts
    WHERE project_id=p_project_id AND command_type='execution.record_usage_sample'
      AND idempotency_key=p_idempotency_key
    FOR UPDATE;
    IF NOT FOUND OR command_row.request_hash <> p_payload_hash THEN
        RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT';
    END IF;
    IF command_row.status = 'APPLIED' THEN
        RETURN command_row.result->'response';
    END IF;
    validation := public.hermes_validate_current_worker_execution(
        p_project_id, p_execution_request_id, p_execution_attempt, p_run_id,
        p_lease_id, p_lease_version, p_fencing_token, p_worker_agent_identity,
        p_context_identity, p_observed_request_version
    );
    IF NOT (validation->>'valid')::BOOLEAN THEN
        RETURN public.hermes_quarantine_worker_payload(
            p_project_id, NULL, p_execution_request_id, p_execution_attempt, p_run_id,
            p_lease_id, p_fencing_token, p_worker_agent_identity, p_context_identity,
            'USAGE_SAMPLE', validation->>'reason_code', p_payload_hash,
            jsonb_build_object('payload_hash', p_payload_hash, 'sample_id', p_sample_id),
            p_command_id, p_idempotency_key, p_actor_type, p_actor_id, p_fault_point
        );
    END IF;
    SELECT * INTO run_row FROM public.agent_runs WHERE run_id=p_run_id;
    IF run_row.reservation_id <> p_reservation_id THEN
        RAISE EXCEPTION 'AGENT_RUN_SCOPE_MISMATCH';
    END IF;
    SELECT * INTO reservation_row
    FROM public.resource_reservations
    WHERE reservation_id=p_reservation_id AND project_id=p_project_id
    FOR UPDATE;
    IF NOT FOUND OR reservation_row.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'RESOURCE_RESERVATION_NOT_ACTIVE';
    END IF;
    IF p_currency IS DISTINCT FROM reservation_row.currency THEN
        RAISE EXCEPTION 'RESOURCE_CURRENCY_MISMATCH';
    END IF;
    IF jsonb_typeof(p_amounts) <> 'object' OR p_amounts='{}'::jsonb THEN
        RAISE EXCEPTION 'RESOURCE_AMOUNT_INVALID';
    END IF;
    FOR item IN SELECT key,value FROM jsonb_each(p_amounts) LOOP
        IF item.key NOT IN (
            'llm_tokens','llm_cost_minor','agent_runs','retry_count','execution_time_ms',
            'cpu_time_ms','gpu_time_ms','docker_runtime_ms','browser_runtime_ms',
            'external_api_calls','storage_bytes','human_attention_requests'
        ) THEN RAISE EXCEPTION 'RESOURCE_DIMENSION_UNKNOWN'; END IF;
        IF jsonb_typeof(item.value)<>'number' OR item.value::text !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'RESOURCE_AMOUNT_INVALID';
        END IF;
    END LOOP;
    IF EXISTS(SELECT 1 FROM public.execution_usage_admissions WHERE sample_id=p_sample_id) THEN
        PERFORM 1 FROM public.execution_usage_admissions
        WHERE sample_id=p_sample_id AND payload_hash=p_payload_hash;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT';
        END IF;
    ELSE
        INSERT INTO public.resource_usage_records(
            usage_id, sample_id, reservation_id, project_id, owner_type, owner_id,
            currency, command_id
        ) VALUES (
            p_usage_id, p_sample_id, p_reservation_id, p_project_id,
            'preparation', reservation_row.owner_id, p_currency, p_command_id
        );
        FOR item IN SELECT key,value FROM jsonb_each(p_amounts) LOOP
            INSERT INTO public.resource_usage_amounts(usage_id, dimension, amount)
            VALUES (p_usage_id, item.key, (item.value::text)::BIGINT);
        END LOOP;
        INSERT INTO public.execution_usage_admissions(
            usage_id, sample_id, project_id, task_id, reservation_id,
            execution_request_id, execution_attempt, run_id, lease_id,
            fencing_token, worker_agent_identity, context_identity,
            interval_start, interval_end, payload_hash, command_id
        ) VALUES (
            p_usage_id, p_sample_id, p_project_id, run_row.task_id, p_reservation_id,
            p_execution_request_id, p_execution_attempt, p_run_id, p_lease_id,
            p_fencing_token, p_worker_agent_identity, p_context_identity,
            p_interval_start, p_interval_end, p_payload_hash, p_command_id
        );
    END IF;
    IF p_fault_point = 'after_usage_admission' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_usage_admission';
    END IF;
    event_id := public.hermes_worker_append_event(
        p_project_id, run_row.task_id, p_command_id, 'execution.usage_recorded',
        p_actor_type, p_actor_id, p_command_id, p_run_id,
        jsonb_build_object(
            'usage_id', p_usage_id,
            'sample_id', p_sample_id,
            'reservation_id', p_reservation_id,
            'execution_request_id', p_execution_request_id,
            'execution_attempt', p_execution_attempt,
            'run_id', p_run_id,
            'lease_id', p_lease_id,
            'fencing_token', p_fencing_token,
            'amounts', p_amounts,
            'payload_hash', p_payload_hash
        ),
        p_fault_point
    );
    response := jsonb_build_object(
        'result_code', 'EXECUTION_USAGE_RECORDED',
        'usage_id', p_usage_id,
        'sample_id', p_sample_id,
        'event_ids', jsonb_build_array(event_id)
    );
    PERFORM public.hermes_worker_complete_command(
        p_command_id, 'APPLIED', 'EXECUTION_USAGE_RECORDED',
        response, jsonb_build_array(event_id), NULL
    );
    RETURN response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_execution_settle_or_release(
    p_project_id TEXT,
    p_reservation_id TEXT,
    p_result_id TEXT,
    p_command_id TEXT,
    p_expected_account_version BIGINT,
    p_terminal_state TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    reservation_row public.resource_reservations%ROWTYPE;
    account_row public.resource_accounts%ROWTYPE;
    item RECORD;
    balance_row RECORD;
    usage_exists BOOLEAN;
    actual JSONB := '{}'::jsonb;
    released JSONB := '{}'::jsonb;
    v_over_limit BOOLEAN := false;
    v_account_version BIGINT;
    v_threshold_status TEXT;
    v_settlement_id TEXT := 'settlement-' || p_result_id;
    release_command_id TEXT := p_command_id;
BEGIN
    SELECT * INTO reservation_row
    FROM public.resource_reservations
    WHERE reservation_id=p_reservation_id AND project_id=p_project_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'RESOURCE_RESERVATION_NOT_ACTIVE';
    END IF;
    IF reservation_row.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'RESOURCE_SETTLEMENT_ALREADY_APPLIED';
    END IF;
    SELECT * INTO account_row
    FROM public.resource_accounts
    WHERE account_id=reservation_row.account_id
    FOR UPDATE;
    IF account_row.version <> p_expected_account_version THEN
        RAISE EXCEPTION 'RESOURCE_ACCOUNT_VERSION_CONFLICT';
    END IF;
    SELECT EXISTS(
        SELECT 1 FROM public.resource_usage_records WHERE reservation_id=p_reservation_id
    ) INTO usage_exists;
    IF usage_exists THEN
        FOR item IN
            SELECT d.dimension,COALESCE(u.amount,0)::BIGINT AS consumed,COALESCE(r.amount,0)::BIGINT AS reserved
            FROM (SELECT dimension FROM public.resource_reservation_amounts WHERE reservation_id=p_reservation_id
                  UNION SELECT ua.dimension FROM public.resource_usage_records ur
                        JOIN public.resource_usage_amounts ua USING(usage_id)
                        WHERE ur.reservation_id=p_reservation_id) d
            LEFT JOIN (SELECT dimension,sum(amount) amount FROM public.resource_usage_records ur
                       JOIN public.resource_usage_amounts ua USING(usage_id)
                       WHERE ur.reservation_id=p_reservation_id GROUP BY dimension) u USING(dimension)
            LEFT JOIN (SELECT dimension,amount FROM public.resource_reservation_amounts
                       WHERE reservation_id=p_reservation_id) r USING(dimension)
        LOOP
            UPDATE public.resource_balances
            SET consumed_amount=consumed_amount+item.consumed,
                reserved_amount=reserved_amount-item.reserved
            WHERE account_id=reservation_row.account_id AND dimension=item.dimension
              AND reserved_amount>=item.reserved
            RETURNING * INTO balance_row;
            IF NOT FOUND THEN RAISE EXCEPTION 'RESOURCE_SETTLEMENT_USAGE_CONFLICT'; END IF;
            actual := actual || jsonb_build_object(item.dimension,item.consumed);
            released := released || jsonb_build_object(item.dimension,item.reserved);
            v_over_limit := v_over_limit OR item.consumed>item.reserved
              OR balance_row.consumed_amount+balance_row.reserved_amount>balance_row.limit_amount;
        END LOOP;
        v_account_version := account_row.version + 1;
        INSERT INTO public.resource_settlements(
            settlement_id, reservation_id, account_id, project_id,
            account_version, over_limit, command_id
        ) VALUES (
            v_settlement_id, p_reservation_id, reservation_row.account_id,
            p_project_id, v_account_version, v_over_limit, p_command_id
        );
        INSERT INTO public.resource_settlement_usage(settlement_id, usage_id)
        SELECT v_settlement_id, usage_id
        FROM public.resource_usage_records
        WHERE reservation_id=p_reservation_id;
        UPDATE public.resource_reservations
        SET status='SETTLED', terminal_at=clock_timestamp()
        WHERE reservation_id=p_reservation_id;
        v_threshold_status := public.hermes_worker_accounting_status(reservation_row.account_id, v_over_limit);
        UPDATE public.resource_accounts
        SET version=v_account_version, threshold_status=v_threshold_status, updated_at=clock_timestamp()
        WHERE account_id=reservation_row.account_id;
        UPDATE public.project_budget_facts SET valid=false, invalidated_at=clock_timestamp()
        WHERE resource_account_id=reservation_row.account_id AND valid;
        RETURN jsonb_build_object(
            'disposition', 'SETTLED',
            'settlement_id', v_settlement_id,
            'account_id', reservation_row.account_id,
            'account_version', v_account_version,
            'actual', actual,
            'released', released,
            'over_limit', v_over_limit,
            'threshold_status', v_threshold_status
        );
    END IF;

    FOR item IN SELECT dimension,amount FROM public.resource_reservation_amounts
                WHERE reservation_id=p_reservation_id LOOP
        UPDATE public.resource_balances
        SET reserved_amount=reserved_amount-item.amount
        WHERE account_id=reservation_row.account_id AND dimension=item.dimension
          AND reserved_amount>=item.amount;
        IF NOT FOUND THEN RAISE EXCEPTION 'RESOURCE_SETTLEMENT_USAGE_CONFLICT'; END IF;
        released := released || jsonb_build_object(item.dimension,item.amount);
    END LOOP;
    UPDATE public.resource_reservations
    SET status=CASE WHEN p_terminal_state='CANCELLED' THEN 'CANCELLED' ELSE 'RELEASED' END,
        terminal_at=clock_timestamp()
    WHERE reservation_id=p_reservation_id;
    v_account_version := account_row.version + 1;
    v_threshold_status := public.hermes_worker_accounting_status(reservation_row.account_id, false);
    UPDATE public.resource_accounts
    SET version=v_account_version, threshold_status=v_threshold_status, updated_at=clock_timestamp()
    WHERE account_id=reservation_row.account_id;
    UPDATE public.project_budget_facts SET valid=false, invalidated_at=clock_timestamp()
    WHERE resource_account_id=reservation_row.account_id AND valid;
    RETURN jsonb_build_object(
        'disposition', 'RELEASED',
        'release_command_id', release_command_id,
        'account_id', reservation_row.account_id,
        'account_version', v_account_version,
        'actual', actual,
        'released', released,
        'over_limit', false,
        'threshold_status', v_threshold_status
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_submit_execution_result(
    p_project_id TEXT,
    p_execution_request_id TEXT,
    p_execution_attempt BIGINT,
    p_run_id TEXT,
    p_lease_id TEXT,
    p_lease_version BIGINT,
    p_fencing_token BIGINT,
    p_worker_agent_identity TEXT,
    p_context_identity TEXT,
    p_observed_request_version BIGINT,
    p_result_id TEXT,
    p_outcome TEXT,
    p_error_classification TEXT,
    p_artifact_candidate_refs JSONB,
    p_evidence_candidate_refs JSONB,
    p_usage_sample_refs JSONB,
    p_started_at TIMESTAMPTZ,
    p_finished_at TIMESTAMPTZ,
    p_adapter_identity TEXT,
    p_adapter_version TEXT,
    p_external_side_effect_refs JSONB,
    p_primary_artifact_candidate_id TEXT,
    p_completion_claim_id TEXT,
    p_expected_account_version BIGINT,
    p_payload JSONB,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    command_row public.command_receipts%ROWTYPE;
    validation JSONB;
    run_row public.agent_runs%ROWTYPE;
    request_row public.execution_request_current_states%ROWTYPE;
    lease_row public.execution_leases%ROWTYPE;
    artifact_candidate public.execution_artifact_candidates%ROWTYPE;
    artifact_ref TEXT;
    evidence_ref TEXT;
    usage_ref TEXT;
    settlement JSONB;
    result_event_id TEXT;
    terminal_event_id TEXT;
    completed_event_id TEXT;
    settled_event_id TEXT;
    claim_event_id TEXT;
    all_event_ids JSONB := '[]'::jsonb;
    target_request_state TEXT;
    target_run_status TEXT;
    response JSONB;
BEGIN
    IF p_actor_type <> 'worker' OR p_actor_id <> p_worker_agent_identity THEN
        RAISE EXCEPTION 'WORKER_IDENTITY_MISMATCH';
    END IF;
    IF public.hermes_worker_execution_secret_guard(p_payload) THEN
        RAISE EXCEPTION 'SECRET_VALUE_FORBIDDEN';
    END IF;
    IF public.hermes_worker_forbidden_verdict_guard(p_payload) THEN
        RETURN public.hermes_quarantine_worker_payload(
            p_project_id, NULL, p_execution_request_id, p_execution_attempt, p_run_id,
            p_lease_id, p_fencing_token, p_worker_agent_identity, p_context_identity,
            'EXECUTION_RESULT', 'WORKER_VERDICT_FORBIDDEN', p_payload_hash,
            jsonb_build_object('payload_hash', p_payload_hash, 'forbidden_fields', true),
            p_command_id, p_idempotency_key, p_actor_type, p_actor_id, p_fault_point
        );
    END IF;
    IF p_outcome NOT IN ('SUCCEEDED','FAILED_TRANSIENT','FAILED_PERMANENT','CANCELLED') THEN
        RAISE EXCEPTION 'EXECUTION_RESULT_OUTCOME_INVALID';
    END IF;
    IF p_finished_at < p_started_at THEN
        RAISE EXCEPTION 'EXECUTION_RESULT_TIME_INVALID';
    END IF;
    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key, request_hash, status, result
    ) VALUES (
        p_command_id, p_project_id, 'execution.submit_result',
        p_idempotency_key, p_payload_hash, 'PROCESSING', '{}'::jsonb
    ) ON CONFLICT DO NOTHING;
    SELECT * INTO command_row
    FROM public.command_receipts
    WHERE project_id=p_project_id AND command_type='execution.submit_result'
      AND idempotency_key=p_idempotency_key
    FOR UPDATE;
    IF NOT FOUND OR command_row.request_hash <> p_payload_hash THEN
        RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT';
    END IF;
    IF command_row.status = 'APPLIED' THEN
        RETURN command_row.result->'response';
    END IF;
    IF p_fault_point = 'after_receipt_placeholder' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_receipt_placeholder';
    END IF;

    validation := public.hermes_validate_current_worker_execution(
        p_project_id, p_execution_request_id, p_execution_attempt, p_run_id,
        p_lease_id, p_lease_version, p_fencing_token, p_worker_agent_identity,
        p_context_identity, p_observed_request_version
    );
    IF NOT (validation->>'valid')::BOOLEAN THEN
        RETURN public.hermes_quarantine_worker_payload(
            p_project_id, NULL, p_execution_request_id, p_execution_attempt, p_run_id,
            p_lease_id, p_fencing_token, p_worker_agent_identity, p_context_identity,
            'EXECUTION_RESULT', validation->>'reason_code', p_payload_hash,
            jsonb_build_object('payload_hash', p_payload_hash, 'result_id', p_result_id),
            p_command_id, p_idempotency_key, p_actor_type, p_actor_id, p_fault_point
        );
    END IF;
    SELECT * INTO run_row FROM public.agent_runs WHERE run_id=p_run_id FOR UPDATE;
    SELECT * INTO request_row
    FROM public.execution_request_current_states
    WHERE execution_request_id=p_execution_request_id
    FOR UPDATE;
    SELECT * INTO lease_row
    FROM public.execution_leases
    WHERE lease_id=p_lease_id
    FOR UPDATE;
    IF EXISTS (
        SELECT 1 FROM public.execution_results
        WHERE execution_request_id=p_execution_request_id
          AND execution_attempt=p_execution_attempt
    ) THEN
        PERFORM 1 FROM public.execution_results
        WHERE result_id=p_result_id AND payload_hash=p_payload_hash;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'EXECUTION_RESULT_ALREADY_RECORDED';
        END IF;
    END IF;

    FOR artifact_ref IN SELECT jsonb_array_elements_text(COALESCE(p_artifact_candidate_refs,'[]'::jsonb)) LOOP
        PERFORM 1 FROM public.execution_artifact_candidates
        WHERE candidate_id=artifact_ref
          AND execution_request_id=p_execution_request_id
          AND execution_attempt=p_execution_attempt
          AND run_id=p_run_id
          AND lease_id=p_lease_id
          AND fencing_token=p_fencing_token;
        IF NOT FOUND THEN RAISE EXCEPTION 'EXECUTION_RESULT_REF_SCOPE_MISMATCH'; END IF;
    END LOOP;
    FOR evidence_ref IN SELECT jsonb_array_elements_text(COALESCE(p_evidence_candidate_refs,'[]'::jsonb)) LOOP
        PERFORM 1 FROM public.execution_evidence_candidates
        WHERE candidate_id=evidence_ref
          AND execution_request_id=p_execution_request_id
          AND execution_attempt=p_execution_attempt
          AND run_id=p_run_id
          AND lease_id=p_lease_id
          AND fencing_token=p_fencing_token;
        IF NOT FOUND THEN RAISE EXCEPTION 'EXECUTION_RESULT_REF_SCOPE_MISMATCH'; END IF;
    END LOOP;
    FOR usage_ref IN SELECT jsonb_array_elements_text(COALESCE(p_usage_sample_refs,'[]'::jsonb)) LOOP
        PERFORM 1 FROM public.execution_usage_admissions
        WHERE sample_id=usage_ref
          AND execution_request_id=p_execution_request_id
          AND execution_attempt=p_execution_attempt
          AND run_id=p_run_id
          AND lease_id=p_lease_id
          AND fencing_token=p_fencing_token;
        IF NOT FOUND THEN RAISE EXCEPTION 'EXECUTION_RESULT_REF_SCOPE_MISMATCH'; END IF;
    END LOOP;
    IF p_fault_point = 'after_result_validated' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_result_validated';
    END IF;

    target_request_state := CASE
        WHEN p_outcome='SUCCEEDED' THEN 'SUCCEEDED'
        WHEN p_outcome='CANCELLED' THEN 'CANCELLED'
        ELSE 'FAILED'
    END;
    target_run_status := CASE
        WHEN p_outcome='SUCCEEDED' THEN 'SUCCEEDED'
        ELSE 'FAILED'
    END;

    IF p_outcome='SUCCEEDED' THEN
        IF p_primary_artifact_candidate_id IS NULL OR p_completion_claim_id IS NULL THEN
            RAISE EXCEPTION 'COMPLETION_CLAIM_ARTIFACT_REQUIRED';
        END IF;
        SELECT * INTO artifact_candidate
        FROM public.execution_artifact_candidates
        WHERE candidate_id=p_primary_artifact_candidate_id
          AND execution_request_id=p_execution_request_id
          AND execution_attempt=p_execution_attempt
          AND run_id=p_run_id
        ;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'COMPLETION_CLAIM_ARTIFACT_REQUIRED';
        END IF;
    END IF;

    INSERT INTO public.execution_results(
        result_id, project_id, task_id, execution_request_id, execution_attempt,
        run_id, lease_id, fencing_token, worker_agent_identity, context_identity,
        outcome, error_classification, artifact_candidate_refs,
        evidence_candidate_refs, usage_sample_refs, started_at, finished_at,
        adapter_identity, adapter_version, external_side_effect_refs, payload_hash,
        command_id, completion_claim_id, terminal_state
    ) VALUES (
        p_result_id, p_project_id, run_row.task_id, p_execution_request_id,
        p_execution_attempt, p_run_id, p_lease_id, p_fencing_token,
        p_worker_agent_identity, p_context_identity, p_outcome,
        COALESCE(p_error_classification,''), COALESCE(p_artifact_candidate_refs,'[]'::jsonb),
        COALESCE(p_evidence_candidate_refs,'[]'::jsonb), COALESCE(p_usage_sample_refs,'[]'::jsonb),
        p_started_at, p_finished_at, p_adapter_identity, p_adapter_version,
        COALESCE(p_external_side_effect_refs,'[]'::jsonb), p_payload_hash,
        p_command_id, p_completion_claim_id, target_request_state
    );
    IF p_fault_point = 'after_result_write' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_result_write';
    END IF;

    result_event_id := public.hermes_worker_append_event(
        p_project_id, run_row.task_id, p_command_id, 'execution.result_recorded',
        p_actor_type, p_actor_id, p_command_id, p_run_id,
        jsonb_build_object(
            'result_id', p_result_id,
            'execution_request_id', p_execution_request_id,
            'execution_attempt', p_execution_attempt,
            'run_id', p_run_id,
            'lease_id', p_lease_id,
            'fencing_token', p_fencing_token,
            'outcome', p_outcome,
            'payload_hash', p_payload_hash
        ),
        p_fault_point
    );
    all_event_ids := all_event_ids || jsonb_build_array(result_event_id);

    IF p_outcome='SUCCEEDED' THEN
        INSERT INTO public.artifacts(
            artifact_id, task_id, content_hash, media_type, produced_by, produced_by_run_id
        ) VALUES (
            'artifact-' || p_primary_artifact_candidate_id,
            run_row.task_id, artifact_candidate.content_hash,
            artifact_candidate.media_type, p_worker_agent_identity, p_run_id
        ) ON CONFLICT (artifact_id) DO NOTHING;
        INSERT INTO public.completion_claims(
            claim_id, task_id, run_id, worker_identity, artifact_id,
            artifact_hash, summary, command_id
        ) VALUES (
            p_completion_claim_id, run_row.task_id, p_run_id, p_worker_agent_identity,
            'artifact-' || p_primary_artifact_candidate_id,
            artifact_candidate.content_hash, 'execution result succeeded', p_command_id
        ) ON CONFLICT (claim_id) DO NOTHING;
        INSERT INTO public.execution_result_claim_links(
            result_id, claim_id, run_id, execution_request_id
        ) VALUES (
            p_result_id, p_completion_claim_id, p_run_id, p_execution_request_id
        );
        UPDATE public.tasks
        SET state='COMPLETION_CLAIMED',
            version=version + 1,
            current_artifact_id='artifact-' || p_primary_artifact_candidate_id,
            current_artifact_hash=artifact_candidate.content_hash,
            completion_worker_identity=p_worker_agent_identity,
            completion_worker_run_id=p_run_id,
            completion_worker_context_identity=p_context_identity,
            updated_at=clock_timestamp()
        WHERE task_id=run_row.task_id
          AND project_id=p_project_id
          AND state='RUNNING';
        IF p_fault_point = 'after_completion_claim' THEN
            RAISE EXCEPTION 'injected worker execution crash: after_completion_claim';
        END IF;
        claim_event_id := public.hermes_worker_append_event(
            p_project_id, run_row.task_id, p_command_id, 'task.completion_claimed',
            'control_plane', 'p2-result-bridge', p_command_id, result_event_id,
            jsonb_build_object(
                'claim_id', p_completion_claim_id,
                'result_id', p_result_id,
                'run_id', p_run_id,
                'artifact_id', 'artifact-' || p_primary_artifact_candidate_id,
                'artifact_hash', artifact_candidate.content_hash
            ),
            p_fault_point
        );
        all_event_ids := all_event_ids || jsonb_build_array(claim_event_id);
    END IF;

    settlement := public.hermes_execution_settle_or_release(
        p_project_id, run_row.reservation_id, p_result_id, p_command_id,
        p_expected_account_version, target_request_state
    );
    IF p_fault_point = 'after_settlement' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_settlement';
    END IF;
    INSERT INTO public.execution_result_settlement_links(
        result_id, reservation_id, settlement_id, release_command_id, disposition
    ) VALUES (
        p_result_id, run_row.reservation_id,
        NULLIF(settlement->>'settlement_id',''),
        CASE WHEN settlement->>'disposition'='RELEASED' THEN p_command_id ELSE NULL END,
        settlement->>'disposition'
    );
    settled_event_id := public.hermes_worker_append_event(
        p_project_id, run_row.task_id, p_command_id, 'execution.settled',
        'control_plane', 'p2-result-admission', p_command_id, result_event_id,
        jsonb_build_object(
            'result_id', p_result_id,
            'reservation_id', run_row.reservation_id,
            'settlement', settlement
        ),
        p_fault_point
    );
    all_event_ids := all_event_ids || jsonb_build_array(settled_event_id);

    UPDATE public.agent_runs
    SET status=target_run_status,
        completed_at=clock_timestamp(),
        finished_command_id=p_command_id,
        version=version + 1
    WHERE run_id=p_run_id AND status='RUNNING';
    IF p_fault_point = 'after_run_terminal' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_run_terminal';
    END IF;
    UPDATE public.execution_request_current_states
    SET request_state=target_request_state,
        request_version=request_version + 1,
        current_lease_id=NULL,
        updated_at=clock_timestamp(),
        command_id=p_command_id
    WHERE execution_request_id=p_execution_request_id;
    IF p_fault_point = 'after_request_terminal' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_request_terminal';
    END IF;
    UPDATE public.execution_leases
    SET lease_state='RELINQUISHED',
        lease_version=lease_version + 1,
        terminal_reason='EXECUTION_' || target_request_state,
        terminal_command_id=p_command_id,
        terminal_at=clock_timestamp()
    WHERE lease_id=p_lease_id AND lease_state='ACTIVE';
    UPDATE public.execution_lock_ownerships
    SET lock_state='RELEASED', released_at=clock_timestamp()
    WHERE lease_id=p_lease_id AND lock_state='ACTIVE';
    UPDATE public.execution_queue_current_states
    SET queue_state='TERMINAL',
        current_lease_id=NULL,
        updated_at=clock_timestamp(),
        command_id=p_command_id
    WHERE execution_request_id=p_execution_request_id;
    IF p_fault_point = 'after_lease_release' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_lease_release';
    END IF;

    terminal_event_id := public.hermes_worker_append_event(
        p_project_id, run_row.task_id, p_command_id,
        CASE WHEN target_request_state='SUCCEEDED' THEN 'execution.run_succeeded'
             WHEN target_request_state='CANCELLED' THEN 'execution.cancelled'
             ELSE 'execution.run_failed' END,
        'control_plane', 'p2-result-admission', p_command_id, result_event_id,
        jsonb_build_object(
            'result_id', p_result_id,
            'execution_request_id', p_execution_request_id,
            'execution_attempt', p_execution_attempt,
            'run_id', p_run_id,
            'lease_id', p_lease_id,
            'fencing_token', p_fencing_token,
            'request_state', target_request_state,
            'run_status', target_run_status
        ),
        p_fault_point
    );
    completed_event_id := public.hermes_worker_append_event(
        p_project_id, run_row.task_id, p_command_id, 'execution.completed',
        'control_plane', 'p2-result-admission', p_command_id, terminal_event_id,
        jsonb_build_object(
            'result_id', p_result_id,
            'execution_request_id', p_execution_request_id,
            'execution_attempt', p_execution_attempt,
            'request_state', target_request_state,
            'verification_required', p_outcome='SUCCEEDED'
        ),
        p_fault_point
    );
    all_event_ids := all_event_ids || jsonb_build_array(terminal_event_id, completed_event_id);

    response := jsonb_build_object(
        'result_code', 'EXECUTION_RESULT_ADMITTED',
        'result_id', p_result_id,
        'execution_request_id', p_execution_request_id,
        'execution_attempt', p_execution_attempt,
        'run_id', p_run_id,
        'request_state', target_request_state,
        'run_status', target_run_status,
        'completion_claim_id', p_completion_claim_id,
        'settlement', settlement,
        'event_ids', all_event_ids
    );
    PERFORM public.hermes_worker_complete_command(
        p_command_id, 'APPLIED', 'EXECUTION_RESULT_ADMITTED',
        response, all_event_ids, request_row.request_version + 1
    );
    IF p_fault_point = 'after_receipt_before_commit' THEN
        RAISE EXCEPTION 'injected worker execution crash: after_receipt_before_commit';
    END IF;
    RETURN response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_invalidate_worker_run_on_lease_terminal()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF OLD.lease_state = 'ACTIVE' AND NEW.lease_state IN ('EXPIRED','SUPERSEDED') THEN
        UPDATE public.agent_runs
        SET status=CASE WHEN NEW.lease_state='EXPIRED' THEN 'EXPIRED' ELSE 'INVALIDATED' END,
            completed_at=clock_timestamp(),
            finished_command_id=NEW.terminal_command_id,
            invalidated_reason=NEW.terminal_reason,
            version=version + 1
        WHERE lease_id=NEW.lease_id
          AND fencing_token=NEW.fencing_token
          AND run_kind='WORKER'
          AND status='RUNNING';
        UPDATE public.execution_worker_assignments
        SET assignment_state='INVALIDATED',
            terminal_at=clock_timestamp(),
            terminal_reason=NEW.terminal_reason
        WHERE lease_id=NEW.lease_id
          AND fencing_token=NEW.fencing_token
          AND assignment_state='STARTED';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS execution_lease_terminal_invalidates_worker_run ON public.execution_leases;
CREATE TRIGGER execution_lease_terminal_invalidates_worker_run
AFTER UPDATE OF lease_state ON public.execution_leases
FOR EACH ROW EXECUTE FUNCTION public.hermes_invalidate_worker_run_on_lease_terminal();

ALTER TABLE public.execution_worker_assignments OWNER TO hermes_worker_execution_owner;
ALTER TABLE public.execution_artifact_candidates OWNER TO hermes_worker_execution_owner;
ALTER TABLE public.execution_evidence_candidates OWNER TO hermes_worker_execution_owner;
ALTER TABLE public.execution_usage_admissions OWNER TO hermes_worker_execution_owner;
ALTER TABLE public.execution_results OWNER TO hermes_worker_execution_owner;
ALTER TABLE public.execution_quarantine_records OWNER TO hermes_worker_execution_owner;
ALTER TABLE public.execution_result_claim_links OWNER TO hermes_worker_execution_owner;
ALTER TABLE public.execution_result_settlement_links OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_worker_execution_secret_guard(JSONB) OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_worker_forbidden_verdict_guard(JSONB) OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_worker_accounting_status(TEXT,BOOLEAN) OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_reject_worker_execution_immutable_change() OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_guard_p2_agent_run_update() OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_worker_complete_command(TEXT,TEXT,TEXT,JSONB,JSONB,BIGINT) OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_worker_append_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_quarantine_worker_payload(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_validate_current_worker_execution(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,BIGINT) OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_start_worker_run(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_record_execution_artifact_candidate(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_record_execution_evidence_candidate(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_record_execution_usage_sample(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,JSONB,TIMESTAMPTZ,TIMESTAMPTZ,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_execution_settle_or_release(TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT) OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_submit_execution_result(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,JSONB,JSONB,JSONB,TIMESTAMPTZ,TIMESTAMPTZ,TEXT,TEXT,JSONB,TEXT,TEXT,BIGINT,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_worker_execution_owner;
ALTER FUNCTION public.hermes_invalidate_worker_run_on_lease_terminal() OWNER TO hermes_worker_execution_owner;

GRANT SELECT ON public.projects, public.tasks, public.execution_requests,
    public.execution_request_current_states, public.execution_queue_current_states,
    public.execution_leases, public.execution_lock_ownerships,
    public.worker_template_availability, public.context_bundles,
    public.sandbox_profiles, public.resource_reservations,
    public.resource_reservation_amounts, public.resource_accounts,
    public.resource_balances, public.resource_usage_records,
    public.resource_usage_amounts, public.resource_settlements,
    public.agent_runs, public.command_receipts, public.event_log,
    public.artifacts, public.completion_claims, public.project_budget_facts,
    public.execution_artifact_candidates, public.execution_evidence_candidates,
    public.execution_usage_admissions, public.execution_results
    TO hermes_worker_execution_owner;
GRANT UPDATE ON public.worker_template_availability
    TO hermes_worker_execution_owner;
GRANT INSERT, UPDATE ON public.command_receipts TO hermes_worker_execution_owner;
GRANT INSERT, UPDATE ON public.agent_runs, public.execution_request_current_states,
    public.execution_queue_current_states, public.execution_leases,
    public.execution_lock_ownerships, public.execution_worker_assignments,
    public.resource_reservations, public.resource_accounts, public.resource_balances,
    public.project_budget_facts, public.execution_results
    TO hermes_worker_execution_owner;
GRANT INSERT ON public.execution_artifact_candidates,
    public.execution_evidence_candidates, public.execution_usage_admissions,
    public.execution_quarantine_records, public.execution_result_claim_links,
    public.execution_result_settlement_links, public.resource_usage_records,
    public.resource_usage_amounts, public.resource_settlements,
    public.resource_settlement_usage, public.artifacts, public.completion_claims,
    public.event_log, public.outbox_messages, public.audit_records
    TO hermes_worker_execution_owner;
GRANT UPDATE ON public.execution_quarantine_records, public.tasks
    TO hermes_worker_execution_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_worker_execution_owner;
REVOKE EXECUTE ON FUNCTION public.hermes_accounting_status(TEXT,BOOLEAN)
    FROM hermes_worker_execution_owner;
GRANT SELECT, INSERT, UPDATE ON public.command_receipts TO hermes_worker_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_start_worker_run(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO hermes_worker_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_record_execution_artifact_candidate(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO hermes_worker_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_record_execution_evidence_candidate(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO hermes_worker_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_record_execution_usage_sample(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,JSONB,TIMESTAMPTZ,TIMESTAMPTZ,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO hermes_worker_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_submit_execution_result(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,JSONB,JSONB,JSONB,TIMESTAMPTZ,TIMESTAMPTZ,TEXT,TEXT,JSONB,TEXT,TEXT,BIGINT,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO hermes_worker_runtime;
GRANT SELECT ON public.execution_worker_assignments,
    public.execution_artifact_candidates, public.execution_evidence_candidates,
    public.execution_usage_admissions, public.execution_results,
    public.execution_quarantine_records
    TO hermes_worker_runtime, hermes_read_only_runtime, hermes_control_plane_runtime;

REVOKE ALL ON public.execution_worker_assignments,
    public.execution_artifact_candidates, public.execution_evidence_candidates,
    public.execution_usage_admissions, public.execution_results,
    public.execution_quarantine_records, public.execution_result_claim_links,
    public.execution_result_settlement_links FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_worker_execution_secret_guard(JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_worker_forbidden_verdict_guard(JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_worker_accounting_status(TEXT,BOOLEAN) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_reject_worker_execution_immutable_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_guard_p2_agent_run_update() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_worker_complete_command(TEXT,TEXT,TEXT,JSONB,JSONB,BIGINT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_worker_append_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_quarantine_worker_payload(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_validate_current_worker_execution(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,BIGINT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_start_worker_run(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_record_execution_artifact_candidate(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_record_execution_evidence_candidate(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_record_execution_usage_sample(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,JSONB,TIMESTAMPTZ,TIMESTAMPTZ,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_execution_settle_or_release(TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_submit_execution_result(TEXT,TEXT,BIGINT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,JSONB,JSONB,JSONB,TIMESTAMPTZ,TIMESTAMPTZ,TEXT,TEXT,JSONB,TEXT,TEXT,BIGINT,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_invalidate_worker_run_on_lease_terminal() FROM PUBLIC;

REVOKE INSERT, UPDATE, DELETE ON public.execution_worker_assignments,
    public.execution_artifact_candidates, public.execution_evidence_candidates,
    public.execution_usage_admissions, public.execution_results,
    public.execution_quarantine_records, public.execution_result_claim_links,
    public.execution_result_settlement_links
FROM hermes_worker_runtime, hermes_scheduler_runtime, hermes_accounting_runtime,
     hermes_verifier_runtime, hermes_control_plane_runtime, hermes_read_only_runtime,
     hermes_execution_runtime, hermes_capability_runtime, hermes_selection_runtime,
     hermes_policy_runtime, hermes_risk_runtime, hermes_planner_runtime,
     hermes_diagnosis_runtime, hermes_situation_runtime;

REVOKE EXECUTE ON FUNCTION public.hermes_execution_settle_or_release(TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT)
FROM hermes_worker_runtime, hermes_scheduler_runtime, hermes_accounting_runtime,
     hermes_verifier_runtime, hermes_control_plane_runtime, hermes_read_only_runtime,
     hermes_execution_runtime, hermes_capability_runtime, hermes_selection_runtime,
     hermes_policy_runtime, hermes_risk_runtime, hermes_planner_runtime,
     hermes_diagnosis_runtime, hermes_situation_runtime, PUBLIC;
REVOKE CREATE ON SCHEMA public FROM hermes_worker_runtime;

COMMENT ON TABLE public.execution_results IS
'P2-4 immutable structured Worker ExecutionResult. SUCCEEDED means execution protocol success only; VerificationResult remains independent authority.';
COMMENT ON TABLE public.execution_quarantine_records IS
'P2-4 minimal durable quarantine for stale/invalid Worker payloads. P3 owns review, adoption, redrive and retention operations.';
COMMENT ON TABLE public.execution_usage_admissions IS
'P2-4 provenance bridge from fenced Worker usage samples to P1 resource_usage_records; no second Usage ledger.';
