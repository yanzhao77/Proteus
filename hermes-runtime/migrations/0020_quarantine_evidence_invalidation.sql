-- P3-3: Quarantine operations and Evidence invalidation authority overlay.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_p3_quarantine_evidence_owner') THEN
        CREATE ROLE hermes_p3_quarantine_evidence_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_quarantine_review_runtime') THEN
        CREATE ROLE hermes_quarantine_review_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_quarantine_adoption_runtime') THEN
        CREATE ROLE hermes_quarantine_adoption_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_quarantine_redrive_runtime') THEN
        CREATE ROLE hermes_quarantine_redrive_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_evidence_invalidation_runtime') THEN
        CREATE ROLE hermes_evidence_invalidation_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.quarantine_current_states (
    quarantine_id TEXT PRIMARY KEY REFERENCES public.execution_quarantine_records(quarantine_id),
    lifecycle_state TEXT NOT NULL CHECK (
        lifecycle_state IN (
            'QUARANTINED','UNDER_REVIEW','DISCARDED','ADOPTION_REQUESTED',
            'ADOPTED','REDRIVE_REQUESTED','REDRIVEN','EXPIRED'
        )
    ),
    version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0),
    retention_until TIMESTAMPTZ NOT NULL,
    last_operation_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS public.quarantine_operations (
    operation_id TEXT PRIMARY KEY,
    quarantine_id TEXT NOT NULL REFERENCES public.execution_quarantine_records(quarantine_id),
    project_id TEXT NOT NULL,
    task_id TEXT,
    operation_type TEXT NOT NULL CHECK (
        operation_type IN (
            'START_REVIEW','DISCARD','REQUEST_ADOPTION','MARK_ADOPTED',
            'REQUEST_REDRIVE','MARK_REDRIVEN','EXPIRE'
        )
    ),
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    expected_version BIGINT NOT NULL CHECK (expected_version >= 0),
    resulting_version BIGINT NOT NULL CHECK (resulting_version > expected_version),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    authorization_ref TEXT,
    reason TEXT NOT NULL,
    operation_payload_hash TEXT NOT NULL CHECK (operation_payload_hash LIKE 'sha256:%'),
    original_payload_hash TEXT NOT NULL CHECK (original_payload_hash LIKE 'sha256:%'),
    source_command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    idempotency_key TEXT NOT NULL,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    event_id TEXT NOT NULL UNIQUE REFERENCES public.event_log(event_id),
    causation_id TEXT,
    correlation_id TEXT NOT NULL,
    retention_until TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (quarantine_id, resulting_version)
);

ALTER TABLE public.quarantine_current_states
    DROP CONSTRAINT IF EXISTS quarantine_current_states_last_operation_fk;
ALTER TABLE public.quarantine_current_states
    ADD CONSTRAINT quarantine_current_states_last_operation_fk
    FOREIGN KEY (last_operation_id)
    REFERENCES public.quarantine_operations(operation_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE IF NOT EXISTS public.quarantine_adoption_requests (
    adoption_request_id TEXT PRIMARY KEY,
    quarantine_id TEXT NOT NULL REFERENCES public.execution_quarantine_records(quarantine_id),
    project_id TEXT NOT NULL,
    task_id TEXT,
    operation_id TEXT NOT NULL UNIQUE REFERENCES public.quarantine_operations(operation_id),
    guarded_command_id TEXT NOT NULL,
    guarded_idempotency_key TEXT NOT NULL,
    semantic_command_type TEXT NOT NULL,
    guard_refs JSONB NOT NULL,
    guard_payload_hash TEXT NOT NULL CHECK (guard_payload_hash LIKE 'sha256:%'),
    original_source_command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    original_causation_id TEXT,
    request_state TEXT NOT NULL CHECK (
        request_state IN ('REQUESTED','ADOPTED','BLOCKED','EXPIRED')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (project_id, guarded_command_id),
    UNIQUE (project_id, guarded_idempotency_key),
    CHECK (guard_refs::text !~* '(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|private key|sk-[A-Za-z0-9]{12,}|password=)')
);

CREATE TABLE IF NOT EXISTS public.quarantine_redrive_requests (
    redrive_request_id TEXT PRIMARY KEY,
    quarantine_id TEXT NOT NULL REFERENCES public.execution_quarantine_records(quarantine_id),
    project_id TEXT NOT NULL,
    task_id TEXT,
    execution_request_id TEXT,
    operation_id TEXT NOT NULL UNIQUE REFERENCES public.quarantine_operations(operation_id),
    redrive_command_id TEXT NOT NULL,
    redrive_idempotency_key TEXT NOT NULL,
    redrive_payload JSONB NOT NULL,
    redrive_payload_hash TEXT NOT NULL CHECK (redrive_payload_hash LIKE 'sha256:%'),
    original_source_command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    original_idempotency_key TEXT NOT NULL,
    original_causation_id TEXT,
    request_state TEXT NOT NULL CHECK (
        request_state IN ('REQUESTED','REDRIVEN','BLOCKED','EXPIRED')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (project_id, redrive_command_id),
    UNIQUE (project_id, redrive_idempotency_key),
    CHECK (redrive_payload::text !~* '(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|private key|sk-[A-Za-z0-9]{12,}|password=)')
);

CREATE TABLE IF NOT EXISTS public.evidence_current_states (
    evidence_id TEXT PRIMARY KEY REFERENCES public.evidence(evidence_id),
    validity_state TEXT NOT NULL CHECK (validity_state IN ('VALID','INVALIDATED')),
    version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0),
    current_invalidation_id TEXT,
    invalidated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK ((validity_state = 'VALID' AND invalidated_at IS NULL)
           OR (validity_state = 'INVALIDATED' AND invalidated_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS public.evidence_invalidation_records (
    invalidation_id TEXT PRIMARY KEY,
    evidence_id TEXT NOT NULL REFERENCES public.evidence(evidence_id),
    project_id TEXT NOT NULL,
    task_id TEXT,
    artifact_id TEXT NOT NULL,
    artifact_hash TEXT NOT NULL CHECK (artifact_hash LIKE 'sha256:%'),
    producer TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    reason TEXT NOT NULL,
    scope TEXT NOT NULL,
    expected_version BIGINT NOT NULL CHECK (expected_version >= 0),
    resulting_version BIGINT NOT NULL CHECK (resulting_version > expected_version),
    payload_hash TEXT NOT NULL CHECK (payload_hash LIKE 'sha256:%'),
    affected_refs JSONB NOT NULL,
    dependency_refs JSONB NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    authorization_ref TEXT,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    event_id TEXT NOT NULL UNIQUE REFERENCES public.event_log(event_id),
    idempotency_key TEXT NOT NULL,
    causation_id TEXT,
    correlation_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (evidence_id, resulting_version),
    CHECK (affected_refs::text !~* '(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|private key|sk-[A-Za-z0-9]{12,}|password=)'),
    CHECK (dependency_refs::text !~* '(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|private key|sk-[A-Za-z0-9]{12,}|password=)')
);

ALTER TABLE public.evidence_current_states
    DROP CONSTRAINT IF EXISTS evidence_current_states_invalidation_fk;
ALTER TABLE public.evidence_current_states
    ADD CONSTRAINT evidence_current_states_invalidation_fk
    FOREIGN KEY (current_invalidation_id)
    REFERENCES public.evidence_invalidation_records(invalidation_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE IF NOT EXISTS public.evidence_dependency_stale_records (
    stale_record_id TEXT PRIMARY KEY,
    invalidation_id TEXT NOT NULL REFERENCES public.evidence_invalidation_records(invalidation_id),
    evidence_id TEXT NOT NULL REFERENCES public.evidence(evidence_id),
    project_id TEXT NOT NULL,
    task_id TEXT,
    dependency_type TEXT NOT NULL CHECK (
        dependency_type IN (
            'verification_result','human_gate_decision','resume_context',
            'execution_request','task','project','unknown_scope'
        )
    ),
    dependency_id TEXT NOT NULL,
    required_action TEXT NOT NULL CHECK (
        required_action IN (
            'REVERIFICATION_REQUIRED','DECISION_STALE','GATE_EVIDENCE_INVALID',
            'EXECUTION_ADMISSION_BLOCKED'
        )
    ),
    dependency_version BIGINT,
    status TEXT NOT NULL CHECK (status IN ('OPEN','ACKNOWLEDGED','RESOLVED')) DEFAULT 'OPEN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (invalidation_id, dependency_type, dependency_id)
);

CREATE TABLE IF NOT EXISTS public.reverification_requirements (
    requirement_id TEXT PRIMARY KEY,
    invalidation_id TEXT NOT NULL REFERENCES public.evidence_invalidation_records(invalidation_id),
    evidence_id TEXT NOT NULL REFERENCES public.evidence(evidence_id),
    project_id TEXT NOT NULL,
    task_id TEXT,
    reason_code TEXT NOT NULL,
    required_action TEXT NOT NULL CHECK (required_action = 'REVERIFICATION_REQUIRED'),
    requirement_state TEXT NOT NULL CHECK (
        requirement_state IN ('OPEN','SUPERSEDED','SATISFIED','CANCELLED')
    ) DEFAULT 'OPEN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (invalidation_id, task_id)
);

CREATE OR REPLACE FUNCTION public.hermes_p3_qe_reject_append_only_change()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'P3_HISTORY_IS_APPEND_ONLY';
END;
$$;

DROP TRIGGER IF EXISTS quarantine_operations_append_only ON public.quarantine_operations;
CREATE TRIGGER quarantine_operations_append_only
BEFORE UPDATE OR DELETE ON public.quarantine_operations
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_qe_reject_append_only_change();

DROP TRIGGER IF EXISTS quarantine_adoption_requests_append_only ON public.quarantine_adoption_requests;
CREATE TRIGGER quarantine_adoption_requests_append_only
BEFORE UPDATE OR DELETE ON public.quarantine_adoption_requests
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_qe_reject_append_only_change();

DROP TRIGGER IF EXISTS quarantine_redrive_requests_append_only ON public.quarantine_redrive_requests;
CREATE TRIGGER quarantine_redrive_requests_append_only
BEFORE UPDATE OR DELETE ON public.quarantine_redrive_requests
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_qe_reject_append_only_change();

DROP TRIGGER IF EXISTS evidence_invalidation_records_append_only ON public.evidence_invalidation_records;
CREATE TRIGGER evidence_invalidation_records_append_only
BEFORE UPDATE OR DELETE ON public.evidence_invalidation_records
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_qe_reject_append_only_change();

DROP TRIGGER IF EXISTS evidence_dependency_stale_records_append_only ON public.evidence_dependency_stale_records;
CREATE TRIGGER evidence_dependency_stale_records_append_only
BEFORE UPDATE OR DELETE ON public.evidence_dependency_stale_records
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_qe_reject_append_only_change();

DROP TRIGGER IF EXISTS reverification_requirements_append_only ON public.reverification_requirements;
CREATE TRIGGER reverification_requirements_append_only
BEFORE UPDATE OR DELETE ON public.reverification_requirements
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_qe_reject_append_only_change();

CREATE OR REPLACE FUNCTION public.hermes_p3_qe_payload_hash(p_payload JSONB)
RETURNS TEXT
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    SELECT 'sha256:' || encode(public.digest(convert_to(p_payload::text, 'UTF8'), 'sha256'), 'hex')
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_qe_secret_guard(p_payload JSONB)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF p_payload::text ~* '(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|private key|sk-[A-Za-z0-9]{12,}|password=)' THEN
        RAISE EXCEPTION 'SECRET_PAYLOAD_FORBIDDEN';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_qe_assert_actor(p_authority TEXT, p_actor_type TEXT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF p_actor_type IN ('worker','scheduler','action_planner','planner','verifier') THEN
        RAISE EXCEPTION '%', CASE
            WHEN p_authority = 'evidence' THEN 'EVIDENCE_INVALIDATION_UNAUTHORIZED'
            ELSE 'QUARANTINE_REVIEW_UNAUTHORIZED'
        END;
    END IF;
    IF p_actor_type NOT IN (
        'system_operator','control_plane','recovery_controller',
        'verification_engine','evidence_authority'
    ) THEN
        RAISE EXCEPTION '%', CASE
            WHEN p_authority = 'evidence' THEN 'EVIDENCE_INVALIDATION_UNAUTHORIZED'
            ELSE 'QUARANTINE_REVIEW_UNAUTHORIZED'
        END;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_qe_begin_command(
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
    v_existing public.command_receipts%ROWTYPE;
BEGIN
    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key,
        request_hash, status, result
    ) VALUES (
        p_command_id, p_project_id, p_command_type, p_idempotency_key,
        p_payload_hash, 'PROCESSING', '{}'::jsonb
    )
    ON CONFLICT (project_id, command_type, idempotency_key) DO NOTHING;

    SELECT * INTO v_existing
    FROM public.command_receipts
    WHERE project_id = p_project_id
      AND command_type = p_command_type
      AND idempotency_key = p_idempotency_key
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'COMMAND_RECEIPT_NOT_FOUND';
    END IF;
    IF v_existing.command_id <> p_command_id THEN
        IF v_existing.request_hash <> p_payload_hash THEN
            RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT';
        END IF;
    END IF;
    IF v_existing.request_hash <> p_payload_hash THEN
        RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT';
    END IF;
    RETURN v_existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_qe_complete_command(
    p_command_id TEXT,
    p_status TEXT,
    p_result JSONB
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    UPDATE public.command_receipts
    SET status=p_status, result=p_result, completed_at=clock_timestamp()
    WHERE command_id=p_command_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_qe_append_event(
    p_project_id TEXT,
    p_partition_key TEXT,
    p_command_id TEXT,
    p_event_type TEXT,
    p_producer_type TEXT,
    p_producer_id TEXT,
    p_payload JSONB,
    p_correlation_id TEXT
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
        event_id,event_type,schema_version,producer_type,producer_id,
        project_id,partition_key,command_id,correlation_id,payload
    ) VALUES (
        v_event_id,p_event_type,'1.0',p_producer_type,p_producer_id,
        p_project_id,p_partition_key,p_command_id,p_correlation_id,p_payload
    )
    RETURNING sequence INTO v_sequence;
    INSERT INTO public.outbox_messages(message_id,event_id,topic,partition_key,sequence,payload)
    VALUES ('msg-' || gen_random_uuid()::text, v_event_id, 'hermes.runtime.events',
            p_partition_key, v_sequence, p_payload);
    RETURN v_event_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_evidence_refs_are_current(p_refs JSONB)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_ref TEXT;
    v_evidence_id TEXT;
    v_state TEXT;
    v_legacy_valid BOOLEAN;
BEGIN
    IF p_refs IS NULL OR jsonb_typeof(p_refs) <> 'array' THEN
        RETURN true;
    END IF;
    FOR v_ref IN SELECT jsonb_array_elements_text(p_refs)
    LOOP
        v_evidence_id := regexp_replace(v_ref, '^evidence:', '');
        SELECT e.valid, ecs.validity_state INTO v_legacy_valid, v_state
        FROM public.evidence e
        LEFT JOIN public.evidence_current_states ecs ON ecs.evidence_id = e.evidence_id
        WHERE e.evidence_id = v_evidence_id;
        IF FOUND AND (NOT v_legacy_valid OR v_state = 'INVALIDATED') THEN
            RETURN false;
        END IF;
    END LOOP;
    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_qe_gate_decision_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF NOT public.hermes_p3_evidence_refs_are_current(NEW.evidence_refs) THEN
        RAISE EXCEPTION 'GATE_EVIDENCE_INVALID';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS human_gate_decision_p3_evidence_guard ON public.human_gate_decisions;
CREATE TRIGGER human_gate_decision_p3_evidence_guard
BEFORE INSERT ON public.human_gate_decisions
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_qe_gate_decision_guard();

CREATE OR REPLACE FUNCTION public.hermes_p3_qe_gate_application_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_decision_refs JSONB;
    v_context_refs JSONB;
BEGIN
    SELECT evidence_refs INTO v_decision_refs
    FROM public.human_gate_decisions
    WHERE gate_decision_id = NEW.gate_decision_id;
    SELECT evidence_refs INTO v_context_refs
    FROM public.project_resume_contexts
    WHERE resume_context_id = NEW.resume_context_id;
    IF NOT public.hermes_p3_evidence_refs_are_current(COALESCE(v_decision_refs, '[]'::jsonb))
       OR NOT public.hermes_p3_evidence_refs_are_current(COALESCE(v_context_refs, '[]'::jsonb)) THEN
        RAISE EXCEPTION 'GATE_EVIDENCE_INVALID';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS human_gate_application_p3_evidence_guard ON public.human_gate_decision_applications;
CREATE TRIGGER human_gate_application_p3_evidence_guard
BEFORE INSERT ON public.human_gate_decision_applications
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_qe_gate_application_guard();

CREATE OR REPLACE FUNCTION public.hermes_p3_quarantine_operate(
    p_operation_type TEXT,
    p_project_id TEXT,
    p_quarantine_id TEXT,
    p_expected_version BIGINT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_authorization_ref TEXT,
    p_reason TEXT,
    p_retention_until TIMESTAMPTZ,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT,
    p_causation_id TEXT,
    p_correlation_id TEXT,
    p_extra JSONB,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_command public.command_receipts%ROWTYPE;
    v_origin public.execution_quarantine_records%ROWTYPE;
    v_current public.quarantine_current_states%ROWTYPE;
    v_from_state TEXT;
    v_to_state TEXT;
    v_operation_id TEXT := 'qop-' || gen_random_uuid()::text;
    v_event_id TEXT;
    v_response JSONB;
    v_guard_refs JSONB := COALESCE(p_extra->'guard_refs', '{}'::jsonb);
    v_redrive_payload JSONB := COALESCE(p_extra->'redrive_payload', '{}'::jsonb);
    v_authority_kind TEXT := 'review';
BEGIN
    IF p_operation_type IN ('REQUEST_ADOPTION','MARK_ADOPTED') THEN
        v_authority_kind := 'adoption';
    ELSIF p_operation_type IN ('REQUEST_REDRIVE','MARK_REDRIVEN') THEN
        v_authority_kind := 'redrive';
    END IF;
    PERFORM public.hermes_p3_qe_assert_actor('quarantine', p_actor_type);
    PERFORM public.hermes_p3_qe_secret_guard(COALESCE(p_extra, '{}'::jsonb));
    v_command := public.hermes_p3_qe_begin_command(
        p_project_id, 'quarantine.' || lower(p_operation_type),
        p_command_id, p_idempotency_key, p_payload_hash
    );
    IF v_command.status = 'APPLIED' THEN
        RETURN v_command.result->'response';
    END IF;

    SELECT * INTO v_origin
    FROM public.execution_quarantine_records
    WHERE quarantine_id = p_quarantine_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'QUARANTINE_RECORD_NOT_FOUND';
    END IF;
    IF v_origin.project_id <> p_project_id THEN
        RAISE EXCEPTION 'QUARANTINE_RECORD_NOT_FOUND';
    END IF;
    INSERT INTO public.quarantine_current_states(
        quarantine_id,lifecycle_state,version,retention_until
    ) VALUES (
        p_quarantine_id,'QUARANTINED',0,
        COALESCE(p_retention_until, clock_timestamp() + interval '30 days')
    )
    ON CONFLICT (quarantine_id) DO NOTHING;

    SELECT * INTO v_current
    FROM public.quarantine_current_states
    WHERE quarantine_id = p_quarantine_id
    FOR UPDATE;
    IF v_current.lifecycle_state IN ('DISCARDED','ADOPTED','REDRIVEN','EXPIRED') THEN
        RAISE EXCEPTION 'QUARANTINE_ALREADY_RESOLVED';
    END IF;
    IF v_current.version <> p_expected_version THEN
        RAISE EXCEPTION 'EXPECTED_VERSION_CONFLICT';
    END IF;
    IF v_current.retention_until <= clock_timestamp() AND p_operation_type <> 'EXPIRE' THEN
        RAISE EXCEPTION 'QUARANTINE_RETENTION_EXPIRED';
    END IF;
    v_from_state := v_current.lifecycle_state;
    v_to_state := CASE p_operation_type
        WHEN 'START_REVIEW' THEN 'UNDER_REVIEW'
        WHEN 'DISCARD' THEN 'DISCARDED'
        WHEN 'REQUEST_ADOPTION' THEN 'ADOPTION_REQUESTED'
        WHEN 'MARK_ADOPTED' THEN 'ADOPTED'
        WHEN 'REQUEST_REDRIVE' THEN 'REDRIVE_REQUESTED'
        WHEN 'MARK_REDRIVEN' THEN 'REDRIVEN'
        WHEN 'EXPIRE' THEN 'EXPIRED'
        ELSE NULL
    END;
    IF v_to_state IS NULL THEN
        RAISE EXCEPTION 'QUARANTINE_OPERATION_UNSUPPORTED';
    END IF;
    IF NOT (
        (v_from_state='QUARANTINED' AND v_to_state IN ('UNDER_REVIEW','EXPIRED')) OR
        (v_from_state='UNDER_REVIEW' AND v_to_state IN ('DISCARDED','ADOPTION_REQUESTED','REDRIVE_REQUESTED','EXPIRED')) OR
        (v_from_state='ADOPTION_REQUESTED' AND v_to_state IN ('ADOPTED','EXPIRED')) OR
        (v_from_state='REDRIVE_REQUESTED' AND v_to_state IN ('REDRIVEN','EXPIRED'))
    ) THEN
        RAISE EXCEPTION 'QUARANTINE_ALREADY_RESOLVED';
    END IF;

    IF p_operation_type = 'REQUEST_ADOPTION' THEN
        IF COALESCE(p_extra->>'task_directive','') IN ('PASS','PASSED','FAIL','FAILED') THEN
            RAISE EXCEPTION 'QUARANTINE_ADOPTION_GUARD_FAILED';
        END IF;
        IF COALESCE(p_extra->>'guarded_command_id','') = ''
           OR COALESCE(p_extra->>'guarded_idempotency_key','') = ''
           OR COALESCE(p_extra->>'semantic_command_type','') = '' THEN
            RAISE EXCEPTION 'QUARANTINE_ADOPTION_GUARD_FAILED';
        END IF;
        IF v_origin.submitted_fencing_token IS NOT NULL
           AND v_origin.observed_current_fencing_token IS NOT NULL
           AND v_origin.submitted_fencing_token <> v_origin.observed_current_fencing_token THEN
            RAISE EXCEPTION 'QUARANTINE_ADOPTION_GUARD_FAILED';
        END IF;
        IF v_guard_refs ? 'evidence_refs'
           AND NOT public.hermes_p3_evidence_refs_are_current(v_guard_refs->'evidence_refs') THEN
            RAISE EXCEPTION 'REVERIFICATION_REQUIRED';
        END IF;
    END IF;

    IF p_operation_type = 'REQUEST_REDRIVE' THEN
        IF COALESCE(p_extra->>'redrive_command_id','') = ''
           OR COALESCE(p_extra->>'redrive_idempotency_key','') = ''
           OR p_extra->>'redrive_command_id' = v_origin.source_command_id
           OR p_extra->>'redrive_idempotency_key' = v_origin.idempotency_key THEN
            RAISE EXCEPTION 'QUARANTINE_REDRIVE_CONFLICT';
        END IF;
    END IF;

    IF p_fault_point = 'after_operation_before_event' THEN
        RAISE EXCEPTION 'INJECTED_P3_QUARANTINE_CRASH_AFTER_OPERATION';
    END IF;

    v_event_id := public.hermes_p3_qe_append_event(
        p_project_id,
        p_project_id,
        p_command_id,
        'quarantine.' || lower(p_operation_type),
        p_actor_type,
        p_actor_id,
        jsonb_build_object(
            'quarantine_id',p_quarantine_id,
            'operation_id',v_operation_id,
            'operation_type',p_operation_type,
            'from_state',v_from_state,
            'to_state',v_to_state,
            'entity_version',p_expected_version + 1,
            'original_payload_hash',v_origin.payload_hash,
            'causation_id',COALESCE(p_causation_id,v_origin.source_command_id)
        ),
        COALESCE(p_correlation_id,p_command_id)
    );

    INSERT INTO public.quarantine_operations(
        operation_id,quarantine_id,project_id,task_id,operation_type,
        from_state,to_state,expected_version,resulting_version,
        actor_type,actor_id,authorization_ref,reason,operation_payload_hash,
        original_payload_hash,source_command_id,idempotency_key,command_id,
        event_id,causation_id,correlation_id,retention_until
    ) VALUES (
        v_operation_id,p_quarantine_id,p_project_id,v_origin.task_id,p_operation_type,
        v_from_state,v_to_state,p_expected_version,p_expected_version + 1,
        p_actor_type,p_actor_id,p_authorization_ref,p_reason,p_payload_hash,
        v_origin.payload_hash,v_origin.source_command_id,p_idempotency_key,p_command_id,
        v_event_id,COALESCE(p_causation_id,v_origin.source_command_id),
        COALESCE(p_correlation_id,p_command_id),COALESCE(p_retention_until,v_current.retention_until)
    );

    IF p_operation_type = 'REQUEST_ADOPTION' THEN
        INSERT INTO public.quarantine_adoption_requests(
            adoption_request_id,quarantine_id,project_id,task_id,operation_id,
            guarded_command_id,guarded_idempotency_key,semantic_command_type,
            guard_refs,guard_payload_hash,original_source_command_id,
            original_causation_id,request_state
        ) VALUES (
            'qadopt-' || gen_random_uuid()::text,p_quarantine_id,p_project_id,
            v_origin.task_id,v_operation_id,p_extra->>'guarded_command_id',
            p_extra->>'guarded_idempotency_key',p_extra->>'semantic_command_type',
            v_guard_refs,public.hermes_p3_qe_payload_hash(v_guard_refs),
            v_origin.source_command_id,COALESCE(p_causation_id,v_origin.source_command_id),
            'REQUESTED'
        );
    ELSIF p_operation_type = 'REQUEST_REDRIVE' THEN
        INSERT INTO public.quarantine_redrive_requests(
            redrive_request_id,quarantine_id,project_id,task_id,execution_request_id,
            operation_id,redrive_command_id,redrive_idempotency_key,
            redrive_payload,redrive_payload_hash,original_source_command_id,
            original_idempotency_key,original_causation_id,request_state
        ) VALUES (
            'qredrive-' || gen_random_uuid()::text,p_quarantine_id,p_project_id,
            v_origin.task_id,v_origin.execution_request_id,v_operation_id,
            p_extra->>'redrive_command_id',p_extra->>'redrive_idempotency_key',
            v_redrive_payload,public.hermes_p3_qe_payload_hash(v_redrive_payload),
            v_origin.source_command_id,v_origin.idempotency_key,
            COALESCE(p_causation_id,v_origin.source_command_id),'REQUESTED'
        );
    ELSIF p_operation_type = 'MARK_ADOPTED' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.quarantine_adoption_requests
            WHERE adoption_request_id = p_extra->>'adoption_request_id'
              AND quarantine_id = p_quarantine_id
              AND request_state = 'REQUESTED'
        ) THEN RAISE EXCEPTION 'QUARANTINE_ADOPTION_GUARD_FAILED'; END IF;
    ELSIF p_operation_type = 'MARK_REDRIVEN' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.quarantine_redrive_requests
            WHERE redrive_request_id = p_extra->>'redrive_request_id'
              AND quarantine_id = p_quarantine_id
              AND request_state = 'REQUESTED'
        ) THEN RAISE EXCEPTION 'QUARANTINE_REDRIVE_CONFLICT'; END IF;
    END IF;

    IF p_fault_point = 'after_event_before_state' THEN
        RAISE EXCEPTION 'INJECTED_P3_QUARANTINE_CRASH_AFTER_EVENT';
    END IF;

    UPDATE public.quarantine_current_states
    SET lifecycle_state=v_to_state,
        version=p_expected_version + 1,
        retention_until=COALESCE(p_retention_until, retention_until),
        last_operation_id=v_operation_id,
        updated_at=clock_timestamp()
    WHERE quarantine_id=p_quarantine_id AND version=p_expected_version;

    v_response := jsonb_build_object(
        'result_code','QUARANTINE_OPERATION_APPLIED',
        'quarantine_id',p_quarantine_id,
        'operation_id',v_operation_id,
        'lifecycle_state',v_to_state,
        'entity_version',p_expected_version + 1,
        'event_id',v_event_id
    );
    PERFORM public.hermes_p3_qe_complete_command(
        p_command_id,'APPLIED',
        jsonb_build_object('response',v_response,'events',jsonb_build_array(v_event_id))
    );
    RETURN v_response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_start_quarantine_review(
    p_project_id TEXT,p_quarantine_id TEXT,p_expected_version BIGINT,
    p_actor_type TEXT,p_actor_id TEXT,p_authorization_ref TEXT,p_reason TEXT,
    p_retention_until TIMESTAMPTZ,p_command_id TEXT,p_idempotency_key TEXT,
    p_payload_hash TEXT,p_causation_id TEXT,p_correlation_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RETURN public.hermes_p3_quarantine_operate(
        'START_REVIEW',p_project_id,p_quarantine_id,p_expected_version,
        p_actor_type,p_actor_id,p_authorization_ref,p_reason,p_retention_until,
        p_command_id,p_idempotency_key,p_payload_hash,p_causation_id,p_correlation_id,
        '{}'::jsonb,p_fault_point
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_discard_quarantine(
    p_project_id TEXT,p_quarantine_id TEXT,p_expected_version BIGINT,
    p_actor_type TEXT,p_actor_id TEXT,p_authorization_ref TEXT,p_reason TEXT,
    p_retention_until TIMESTAMPTZ,p_command_id TEXT,p_idempotency_key TEXT,
    p_payload_hash TEXT,p_causation_id TEXT,p_correlation_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RETURN public.hermes_p3_quarantine_operate(
        'DISCARD',p_project_id,p_quarantine_id,p_expected_version,
        p_actor_type,p_actor_id,p_authorization_ref,p_reason,p_retention_until,
        p_command_id,p_idempotency_key,p_payload_hash,p_causation_id,p_correlation_id,
        '{}'::jsonb,p_fault_point
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_request_quarantine_adoption(
    p_project_id TEXT,p_quarantine_id TEXT,p_expected_version BIGINT,
    p_actor_type TEXT,p_actor_id TEXT,p_authorization_ref TEXT,p_reason TEXT,
    p_guarded_command_id TEXT,p_guarded_idempotency_key TEXT,
    p_semantic_command_type TEXT,p_guard_refs JSONB,p_retention_until TIMESTAMPTZ,
    p_command_id TEXT,p_idempotency_key TEXT,p_payload_hash TEXT,
    p_causation_id TEXT,p_correlation_id TEXT,p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RETURN public.hermes_p3_quarantine_operate(
        'REQUEST_ADOPTION',p_project_id,p_quarantine_id,p_expected_version,
        p_actor_type,p_actor_id,p_authorization_ref,p_reason,p_retention_until,
        p_command_id,p_idempotency_key,p_payload_hash,p_causation_id,p_correlation_id,
        jsonb_build_object(
            'guarded_command_id',p_guarded_command_id,
            'guarded_idempotency_key',p_guarded_idempotency_key,
            'semantic_command_type',p_semantic_command_type,
            'guard_refs',COALESCE(p_guard_refs,'{}'::jsonb)
        ),
        p_fault_point
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_mark_quarantine_adopted(
    p_project_id TEXT,p_quarantine_id TEXT,p_adoption_request_id TEXT,
    p_expected_version BIGINT,p_actor_type TEXT,p_actor_id TEXT,
    p_authorization_ref TEXT,p_reason TEXT,p_command_id TEXT,
    p_idempotency_key TEXT,p_payload_hash TEXT,p_causation_id TEXT,
    p_correlation_id TEXT,p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RETURN public.hermes_p3_quarantine_operate(
        'MARK_ADOPTED',p_project_id,p_quarantine_id,p_expected_version,
        p_actor_type,p_actor_id,p_authorization_ref,p_reason,NULL,
        p_command_id,p_idempotency_key,p_payload_hash,p_causation_id,p_correlation_id,
        jsonb_build_object('adoption_request_id',p_adoption_request_id),
        p_fault_point
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_request_quarantine_redrive(
    p_project_id TEXT,p_quarantine_id TEXT,p_expected_version BIGINT,
    p_actor_type TEXT,p_actor_id TEXT,p_authorization_ref TEXT,p_reason TEXT,
    p_redrive_command_id TEXT,p_redrive_idempotency_key TEXT,p_redrive_payload JSONB,
    p_retention_until TIMESTAMPTZ,p_command_id TEXT,p_idempotency_key TEXT,
    p_payload_hash TEXT,p_causation_id TEXT,p_correlation_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RETURN public.hermes_p3_quarantine_operate(
        'REQUEST_REDRIVE',p_project_id,p_quarantine_id,p_expected_version,
        p_actor_type,p_actor_id,p_authorization_ref,p_reason,p_retention_until,
        p_command_id,p_idempotency_key,p_payload_hash,p_causation_id,p_correlation_id,
        jsonb_build_object(
            'redrive_command_id',p_redrive_command_id,
            'redrive_idempotency_key',p_redrive_idempotency_key,
            'redrive_payload',COALESCE(p_redrive_payload,'{}'::jsonb)
        ),
        p_fault_point
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_mark_quarantine_redriven(
    p_project_id TEXT,p_quarantine_id TEXT,p_redrive_request_id TEXT,
    p_expected_version BIGINT,p_actor_type TEXT,p_actor_id TEXT,
    p_authorization_ref TEXT,p_reason TEXT,p_command_id TEXT,
    p_idempotency_key TEXT,p_payload_hash TEXT,p_causation_id TEXT,
    p_correlation_id TEXT,p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RETURN public.hermes_p3_quarantine_operate(
        'MARK_REDRIVEN',p_project_id,p_quarantine_id,p_expected_version,
        p_actor_type,p_actor_id,p_authorization_ref,p_reason,NULL,
        p_command_id,p_idempotency_key,p_payload_hash,p_causation_id,p_correlation_id,
        jsonb_build_object('redrive_request_id',p_redrive_request_id),
        p_fault_point
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_expire_quarantine(
    p_project_id TEXT,p_quarantine_id TEXT,p_expected_version BIGINT,
    p_actor_type TEXT,p_actor_id TEXT,p_reason TEXT,p_command_id TEXT,
    p_idempotency_key TEXT,p_payload_hash TEXT,p_causation_id TEXT,
    p_correlation_id TEXT,p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RETURN public.hermes_p3_quarantine_operate(
        'EXPIRE',p_project_id,p_quarantine_id,p_expected_version,
        p_actor_type,p_actor_id,NULL,p_reason,NULL,
        p_command_id,p_idempotency_key,p_payload_hash,p_causation_id,p_correlation_id,
        '{}'::jsonb,p_fault_point
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_invalidate_evidence(
    p_project_id TEXT,
    p_evidence_id TEXT,
    p_expected_version BIGINT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_producer TEXT,
    p_reason_code TEXT,
    p_reason TEXT,
    p_scope TEXT,
    p_affected_refs JSONB,
    p_dependency_refs JSONB,
    p_authorization_ref TEXT,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT,
    p_causation_id TEXT,
    p_correlation_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_command public.command_receipts%ROWTYPE;
    v_evidence public.evidence%ROWTYPE;
    v_artifact public.artifacts%ROWTYPE;
    v_task public.tasks%ROWTYPE;
    v_current public.evidence_current_states%ROWTYPE;
    v_invalidation_id TEXT := 'einv-' || gen_random_uuid()::text;
    v_event_id TEXT;
    v_response JSONB;
    v_verification RECORD;
    v_gate RECORD;
    v_context RECORD;
BEGIN
    PERFORM public.hermes_p3_qe_assert_actor('evidence', p_actor_type);
    PERFORM public.hermes_p3_qe_secret_guard(COALESCE(p_affected_refs,'{}'::jsonb));
    PERFORM public.hermes_p3_qe_secret_guard(COALESCE(p_dependency_refs,'[]'::jsonb));
    v_command := public.hermes_p3_qe_begin_command(
        p_project_id,'evidence.invalidate',
        p_command_id,p_idempotency_key,p_payload_hash
    );
    IF v_command.status = 'APPLIED' THEN
        RETURN v_command.result->'response';
    END IF;

    SELECT * INTO v_evidence FROM public.evidence WHERE evidence_id=p_evidence_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'EVIDENCE_NOT_FOUND'; END IF;
    SELECT * INTO v_artifact FROM public.artifacts WHERE artifact_id=v_evidence.artifact_id;
    SELECT * INTO v_task FROM public.tasks WHERE task_id=v_artifact.task_id;
    IF NOT FOUND OR v_task.project_id <> p_project_id THEN
        RAISE EXCEPTION 'EVIDENCE_INVALIDATION_SCOPE_MISMATCH';
    END IF;
    INSERT INTO public.evidence_current_states(evidence_id,validity_state,version)
    VALUES (p_evidence_id,'VALID',0)
    ON CONFLICT (evidence_id) DO NOTHING;
    SELECT * INTO v_current
    FROM public.evidence_current_states
    WHERE evidence_id=p_evidence_id
    FOR UPDATE;
    IF v_current.version <> p_expected_version THEN
        RAISE EXCEPTION 'EXPECTED_VERSION_CONFLICT';
    END IF;
    IF v_current.validity_state = 'INVALIDATED' OR NOT v_evidence.valid THEN
        RAISE EXCEPTION 'EVIDENCE_ALREADY_INVALIDATED';
    END IF;

    IF p_fault_point = 'after_invalidation_before_event' THEN
        RAISE EXCEPTION 'INJECTED_P3_EVIDENCE_CRASH_AFTER_INVALIDATION';
    END IF;

    v_event_id := public.hermes_p3_qe_append_event(
        p_project_id,
        p_project_id,
        p_command_id,
        'evidence.invalidated',
        p_actor_type,
        p_actor_id,
        jsonb_build_object(
            'invalidation_id',v_invalidation_id,
            'evidence_id',p_evidence_id,
            'task_id',v_task.task_id,
            'artifact_hash',v_evidence.artifact_hash,
            'entity_version',p_expected_version + 1,
            'reason_code',p_reason_code,
            'scope',p_scope,
            'required_action','REVERIFICATION_REQUIRED'
        ),
        COALESCE(p_correlation_id,p_command_id)
    );

    INSERT INTO public.evidence_invalidation_records(
        invalidation_id,evidence_id,project_id,task_id,artifact_id,artifact_hash,
        producer,reason_code,reason,scope,expected_version,resulting_version,
        payload_hash,affected_refs,dependency_refs,actor_type,actor_id,
        authorization_ref,command_id,event_id,idempotency_key,causation_id,correlation_id
    ) VALUES (
        v_invalidation_id,p_evidence_id,p_project_id,v_task.task_id,
        v_evidence.artifact_id,v_evidence.artifact_hash,p_producer,p_reason_code,
        p_reason,p_scope,p_expected_version,p_expected_version + 1,p_payload_hash,
        COALESCE(p_affected_refs,'{}'::jsonb),COALESCE(p_dependency_refs,'[]'::jsonb),
        p_actor_type,p_actor_id,p_authorization_ref,p_command_id,
        v_event_id,p_idempotency_key,p_causation_id,
        COALESCE(p_correlation_id,p_command_id)
    );

    FOR v_verification IN
        SELECT vr.verification_id, vr.task_id
        FROM public.verification_results vr
        JOIN public.verification_evidence ve ON ve.verification_id=vr.verification_id
        WHERE ve.evidence_id=p_evidence_id
    LOOP
        INSERT INTO public.evidence_dependency_stale_records(
            stale_record_id,invalidation_id,evidence_id,project_id,task_id,
            dependency_type,dependency_id,required_action,dependency_version
        ) VALUES (
            'stale-' || gen_random_uuid()::text,v_invalidation_id,p_evidence_id,
            p_project_id,v_verification.task_id,'verification_result',
            v_verification.verification_id,'REVERIFICATION_REQUIRED',NULL
        ) ON CONFLICT DO NOTHING;
    END LOOP;

    FOR v_gate IN
        SELECT gate_decision_id, version
        FROM public.human_gate_decisions
        WHERE evidence_refs ? p_evidence_id OR evidence_refs ? ('evidence:' || p_evidence_id)
    LOOP
        INSERT INTO public.evidence_dependency_stale_records(
            stale_record_id,invalidation_id,evidence_id,project_id,task_id,
            dependency_type,dependency_id,required_action,dependency_version
        ) VALUES (
            'stale-' || gen_random_uuid()::text,v_invalidation_id,p_evidence_id,
            p_project_id,v_task.task_id,'human_gate_decision',
            v_gate.gate_decision_id,'GATE_EVIDENCE_INVALID',v_gate.version
        ) ON CONFLICT DO NOTHING;
    END LOOP;

    FOR v_context IN
        SELECT resume_context_id
        FROM public.project_resume_contexts
        WHERE evidence_refs ? p_evidence_id OR evidence_refs ? ('evidence:' || p_evidence_id)
    LOOP
        INSERT INTO public.evidence_dependency_stale_records(
            stale_record_id,invalidation_id,evidence_id,project_id,task_id,
            dependency_type,dependency_id,required_action,dependency_version
        ) VALUES (
            'stale-' || gen_random_uuid()::text,v_invalidation_id,p_evidence_id,
            p_project_id,v_task.task_id,'resume_context',
            v_context.resume_context_id,'GATE_EVIDENCE_INVALID',NULL
        ) ON CONFLICT DO NOTHING;
    END LOOP;

    IF p_scope IN ('UNKNOWN','unknown','undetermined')
       OR NOT EXISTS (
            SELECT 1 FROM public.evidence_dependency_stale_records
            WHERE invalidation_id=v_invalidation_id
       ) THEN
        INSERT INTO public.evidence_dependency_stale_records(
            stale_record_id,invalidation_id,evidence_id,project_id,task_id,
            dependency_type,dependency_id,required_action,dependency_version
        ) VALUES (
            'stale-' || gen_random_uuid()::text,v_invalidation_id,p_evidence_id,
            p_project_id,v_task.task_id,'unknown_scope',
            COALESCE(p_scope,'UNKNOWN'),'REVERIFICATION_REQUIRED',NULL
        ) ON CONFLICT DO NOTHING;
    END IF;

    INSERT INTO public.reverification_requirements(
        requirement_id,invalidation_id,evidence_id,project_id,task_id,
        reason_code,required_action
    ) VALUES (
        'reverify-' || gen_random_uuid()::text,v_invalidation_id,p_evidence_id,
        p_project_id,v_task.task_id,'REVERIFICATION_REQUIRED','REVERIFICATION_REQUIRED'
    ) ON CONFLICT DO NOTHING;

    IF p_fault_point = 'after_event_before_state' THEN
        RAISE EXCEPTION 'INJECTED_P3_EVIDENCE_CRASH_AFTER_EVENT';
    END IF;

    UPDATE public.evidence_current_states
    SET validity_state='INVALIDATED',
        version=p_expected_version + 1,
        current_invalidation_id=v_invalidation_id,
        invalidated_at=clock_timestamp(),
        updated_at=clock_timestamp()
    WHERE evidence_id=p_evidence_id AND version=p_expected_version;

    v_response := jsonb_build_object(
        'result_code','EVIDENCE_INVALIDATED',
        'evidence_id',p_evidence_id,
        'invalidation_id',v_invalidation_id,
        'validity_state','INVALIDATED',
        'entity_version',p_expected_version + 1,
        'required_action','REVERIFICATION_REQUIRED',
        'event_id',v_event_id
    );
    PERFORM public.hermes_p3_qe_complete_command(
        p_command_id,'APPLIED',
        jsonb_build_object('response',v_response,'events',jsonb_build_array(v_event_id))
    );
    RETURN v_response;
END;
$$;

ALTER TABLE public.quarantine_current_states OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER TABLE public.quarantine_operations OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER TABLE public.quarantine_adoption_requests OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER TABLE public.quarantine_redrive_requests OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER TABLE public.evidence_current_states OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER TABLE public.evidence_invalidation_records OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER TABLE public.evidence_dependency_stale_records OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER TABLE public.reverification_requirements OWNER TO hermes_p3_quarantine_evidence_owner;

ALTER FUNCTION public.hermes_p3_qe_reject_append_only_change() OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_p3_qe_payload_hash(JSONB) OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_p3_qe_secret_guard(JSONB) OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_p3_qe_assert_actor(TEXT,TEXT) OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_p3_qe_begin_command(TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_p3_qe_complete_command(TEXT,TEXT,JSONB) OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_p3_qe_append_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_p3_evidence_refs_are_current(JSONB) OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_p3_qe_gate_decision_guard() OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_p3_qe_gate_application_guard() OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_p3_quarantine_operate(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_start_quarantine_review(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_discard_quarantine(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_request_quarantine_adoption(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_mark_quarantine_adopted(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_request_quarantine_redrive(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_mark_quarantine_redriven(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_expire_quarantine(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_p3_quarantine_evidence_owner;
ALTER FUNCTION public.hermes_invalidate_evidence(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_p3_quarantine_evidence_owner;

GRANT SELECT ON public.execution_quarantine_records, public.evidence, public.artifacts,
    public.tasks, public.verification_results, public.verification_evidence,
    public.human_gate_decisions, public.project_resume_contexts
TO hermes_p3_quarantine_evidence_owner;
GRANT SELECT, INSERT, UPDATE ON public.command_receipts TO hermes_p3_quarantine_evidence_owner;
GRANT SELECT, INSERT ON public.event_log, public.outbox_messages TO hermes_p3_quarantine_evidence_owner;
GRANT SELECT, INSERT, UPDATE ON public.quarantine_current_states,
    public.evidence_current_states TO hermes_p3_quarantine_evidence_owner;
GRANT SELECT, INSERT ON public.quarantine_operations,
    public.quarantine_adoption_requests, public.quarantine_redrive_requests,
    public.evidence_invalidation_records, public.evidence_dependency_stale_records,
    public.reverification_requirements TO hermes_p3_quarantine_evidence_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_p3_quarantine_evidence_owner;

GRANT SELECT ON public.quarantine_current_states, public.quarantine_operations,
    public.quarantine_adoption_requests, public.quarantine_redrive_requests,
    public.evidence_current_states, public.evidence_invalidation_records,
    public.evidence_dependency_stale_records, public.reverification_requirements
TO hermes_read_only_runtime;

REVOKE ALL ON public.quarantine_current_states, public.quarantine_operations,
    public.quarantine_adoption_requests, public.quarantine_redrive_requests,
    public.evidence_current_states, public.evidence_invalidation_records,
    public.evidence_dependency_stale_records, public.reverification_requirements
FROM PUBLIC;

REVOKE ALL ON FUNCTION public.hermes_p3_qe_reject_append_only_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_qe_payload_hash(JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_qe_secret_guard(JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_qe_assert_actor(TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_qe_begin_command(TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_qe_complete_command(TEXT,TEXT,JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_qe_append_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_evidence_refs_are_current(JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_qe_gate_decision_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_qe_gate_application_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_quarantine_operate(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_start_quarantine_review(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_discard_quarantine(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_request_quarantine_adoption(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_mark_quarantine_adopted(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_request_quarantine_redrive(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_mark_quarantine_redriven(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_expire_quarantine(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_invalidate_evidence(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.hermes_start_quarantine_review(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_discard_quarantine(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_expire_quarantine(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
TO hermes_quarantine_review_runtime;

GRANT EXECUTE ON FUNCTION public.hermes_request_quarantine_adoption(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_mark_quarantine_adopted(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
TO hermes_quarantine_adoption_runtime;

GRANT EXECUTE ON FUNCTION public.hermes_request_quarantine_redrive(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_mark_quarantine_redriven(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
TO hermes_quarantine_redrive_runtime;

GRANT EXECUTE ON FUNCTION public.hermes_invalidate_evidence(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
TO hermes_evidence_invalidation_runtime;

GRANT EXECUTE ON FUNCTION public.hermes_p3_evidence_refs_are_current(JSONB)
TO hermes_execution_runtime, hermes_control_plane_runtime, hermes_gate_request_runtime,
   hermes_gate_decision_runtime, hermes_read_only_runtime;

REVOKE INSERT, UPDATE, DELETE ON public.quarantine_current_states,
    public.quarantine_operations, public.quarantine_adoption_requests,
    public.quarantine_redrive_requests, public.evidence_current_states,
    public.evidence_invalidation_records, public.evidence_dependency_stale_records,
    public.reverification_requirements
FROM hermes_worker_runtime, hermes_verifier_runtime, hermes_scheduler_runtime,
     hermes_control_plane_runtime, hermes_read_only_runtime, hermes_execution_runtime,
     hermes_planner_runtime, hermes_diagnosis_runtime, hermes_situation_runtime,
     hermes_quarantine_review_runtime, hermes_quarantine_adoption_runtime,
     hermes_quarantine_redrive_runtime, hermes_evidence_invalidation_runtime,
     PUBLIC;

REVOKE EXECUTE ON FUNCTION public.hermes_start_quarantine_review(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_discard_quarantine(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_request_quarantine_adoption(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_mark_quarantine_adopted(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_request_quarantine_redrive(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TIMESTAMPTZ,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_mark_quarantine_redriven(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_expire_quarantine(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_invalidate_evidence(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
FROM hermes_worker_runtime, hermes_verifier_runtime, hermes_scheduler_runtime,
     hermes_planner_runtime, hermes_diagnosis_runtime, hermes_situation_runtime,
     hermes_execution_runtime, PUBLIC;

REVOKE CREATE ON SCHEMA public FROM hermes_quarantine_review_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_quarantine_adoption_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_quarantine_redrive_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_evidence_invalidation_runtime;

COMMENT ON TABLE public.quarantine_current_states IS
'P3-3 mutable expected-version pointer for immutable P2 quarantine envelopes; original payload/hash/fencing/run/request refs remain in execution_quarantine_records.';
COMMENT ON TABLE public.quarantine_operations IS
'Append-only P3-3 review/adoption/redrive/expiry operation ledger with actor, authorization, reason, causation, correlation and event/outbox links.';
COMMENT ON TABLE public.quarantine_adoption_requests IS
'Append-only guarded semantic command shell for quarantine adoption; it never writes Task PASS/FAIL or normal execution authority directly.';
COMMENT ON TABLE public.quarantine_redrive_requests IS
'Append-only redrive request ledger using new command and idempotency identity while preserving original causation.';
COMMENT ON TABLE public.evidence_invalidation_records IS
'Append-only P3-3 Evidence invalidation facts; Evidence and VerificationResult history remain immutable.';
COMMENT ON TABLE public.evidence_dependency_stale_records IS
'Append-only stale dependency facts produced by Evidence invalidation for Control Plane guarded follow-up.';
COMMENT ON TABLE public.reverification_requirements IS
'Append-only re-verification requirements; invalidation does not directly flip PASSED Tasks to FAILED.';
