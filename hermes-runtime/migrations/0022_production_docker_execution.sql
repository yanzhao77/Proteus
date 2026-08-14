-- P3-5: Production Docker execution adapter and side-effect receipt authority.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_p3_docker_owner') THEN
        CREATE ROLE hermes_p3_docker_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_docker_adapter_runtime') THEN
        CREATE ROLE hermes_docker_adapter_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_side_effect_runtime') THEN
        CREATE ROLE hermes_side_effect_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.docker_process_runs (
    process_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    execution_request_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    lease_id TEXT NOT NULL,
    lease_version BIGINT NOT NULL CHECK (lease_version > 0),
    fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
    container_name TEXT NOT NULL UNIQUE,
    container_id TEXT,
    plan_hash TEXT NOT NULL CHECK (plan_hash LIKE 'sha256:%'),
    lifecycle_state TEXT NOT NULL CHECK (
        lifecycle_state IN (
            'PREPARED','SPAWNING','RUNNING','SUCCEEDED','FAILED','TIMED_OUT',
            'CANCELLED','STALE_TERMINATED','UNKNOWN'
        )
    ),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
    trace_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    causation_id TEXT,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    last_event_id TEXT NOT NULL REFERENCES public.event_log(event_id) DEFERRABLE INITIALLY DEFERRED,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (project_id, execution_request_id, run_id)
);

CREATE TABLE IF NOT EXISTS public.docker_process_observations (
    observation_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL REFERENCES public.docker_process_runs(process_id),
    project_id TEXT NOT NULL,
    execution_request_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    lease_id TEXT NOT NULL,
    lease_version BIGINT NOT NULL,
    fencing_token BIGINT NOT NULL,
    observed_state TEXT NOT NULL,
    container_id TEXT,
    plan_hash TEXT NOT NULL CHECK (plan_hash LIKE 'sha256:%'),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    event_id TEXT NOT NULL UNIQUE REFERENCES public.event_log(event_id),
    idempotency_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS public.external_side_effect_receipts (
    receipt_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    execution_request_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    process_id TEXT NOT NULL REFERENCES public.docker_process_runs(process_id),
    lease_id TEXT NOT NULL,
    lease_version BIGINT NOT NULL,
    fencing_token BIGINT NOT NULL,
    side_effect_key TEXT NOT NULL,
    action_class TEXT NOT NULL,
    target_class TEXT NOT NULL,
    reversible BOOLEAN NOT NULL,
    human_gate_authorization_ref TEXT,
    request_payload_hash TEXT NOT NULL CHECK (request_payload_hash LIKE 'sha256:%'),
    external_receipt_ref TEXT NOT NULL,
    external_receipt_hash TEXT NOT NULL CHECK (external_receipt_hash LIKE 'sha256:%'),
    observed_outcome TEXT NOT NULL CHECK (
        observed_outcome IN ('SUCCEEDED','FAILED','DENIED','UNKNOWN')
    ),
    reconciliation_state TEXT NOT NULL CHECK (
        reconciliation_state IN ('MATCHED','UNKNOWN','RECONCILE_REQUIRED','DENIED')
    ),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    causation_id TEXT,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    event_id TEXT NOT NULL UNIQUE REFERENCES public.event_log(event_id),
    idempotency_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (project_id, side_effect_key),
    CHECK (external_receipt_ref !~* '(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|private key|sk-[A-Za-z0-9]{12,}|password=)')
);

CREATE TABLE IF NOT EXISTS public.docker_process_reconcile_findings (
    finding_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    process_id TEXT REFERENCES public.docker_process_runs(process_id),
    finding_type TEXT NOT NULL CHECK (
        finding_type IN ('STALE_CONTAINER','ORPHAN_CONTAINER','EFFECT_BEFORE_RECEIPT','RECEIPT_WITHOUT_CURRENT_EXECUTION')
    ),
    finding_state TEXT NOT NULL CHECK (
        finding_state IN ('OPEN','PLANNED','BLOCKED','RESOLVED')
    ) DEFAULT 'OPEN',
    safe_summary JSONB NOT NULL,
    command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    event_id TEXT NOT NULL REFERENCES public.event_log(event_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (safe_summary::text !~* '(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|private key|sk-[A-Za-z0-9]{12,}|password=)')
);

CREATE OR REPLACE FUNCTION public.hermes_p3_docker_reject_append_only_change()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'P3_DOCKER_HISTORY_IS_APPEND_ONLY';
END;
$$;

DROP TRIGGER IF EXISTS docker_process_observations_append_only ON public.docker_process_observations;
CREATE TRIGGER docker_process_observations_append_only
BEFORE UPDATE OR DELETE ON public.docker_process_observations
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_docker_reject_append_only_change();

DROP TRIGGER IF EXISTS external_side_effect_receipts_append_only ON public.external_side_effect_receipts;
CREATE TRIGGER external_side_effect_receipts_append_only
BEFORE UPDATE OR DELETE ON public.external_side_effect_receipts
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_docker_reject_append_only_change();

DROP TRIGGER IF EXISTS docker_process_reconcile_findings_append_only ON public.docker_process_reconcile_findings;
CREATE TRIGGER docker_process_reconcile_findings_append_only
BEFORE UPDATE OR DELETE ON public.docker_process_reconcile_findings
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_docker_reject_append_only_change();

CREATE OR REPLACE FUNCTION public.hermes_p3_docker_begin_command(
    p_project_id TEXT,p_command_type TEXT,p_command_id TEXT,
    p_idempotency_key TEXT,p_payload_hash TEXT
) RETURNS public.command_receipts
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE v_existing public.command_receipts%ROWTYPE;
BEGIN
    INSERT INTO public.command_receipts(
        command_id,project_id,command_type,idempotency_key,request_hash,status,result
    ) VALUES (
        p_command_id,p_project_id,p_command_type,p_idempotency_key,p_payload_hash,'PROCESSING','{}'::jsonb
    ) ON CONFLICT (project_id, command_type, idempotency_key) DO NOTHING;
    SELECT * INTO v_existing FROM public.command_receipts
    WHERE project_id=p_project_id AND command_type=p_command_type
      AND idempotency_key=p_idempotency_key
    FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'COMMAND_RECEIPT_NOT_FOUND'; END IF;
    IF v_existing.request_hash <> p_payload_hash THEN
        RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT';
    END IF;
    RETURN v_existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_docker_complete_command(
    p_command_id TEXT,p_status TEXT,p_result JSONB
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    UPDATE public.command_receipts
    SET status=p_status,result=p_result,completed_at=clock_timestamp()
    WHERE command_id=p_command_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_docker_append_event(
    p_project_id TEXT,p_command_id TEXT,p_event_type TEXT,
    p_producer_type TEXT,p_producer_id TEXT,p_payload JSONB,p_correlation_id TEXT
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
        p_project_id,p_project_id,p_command_id,p_correlation_id,p_payload
    )
    RETURNING sequence INTO v_sequence;
    INSERT INTO public.outbox_messages(message_id,event_id,topic,partition_key,sequence,payload)
    VALUES ('msg-' || gen_random_uuid()::text,v_event_id,'hermes.runtime.events',
            p_project_id,v_sequence,p_payload);
    RETURN v_event_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_record_docker_process(
    p_project_id TEXT,p_execution_request_id TEXT,p_run_id TEXT,
    p_lease_id TEXT,p_lease_version BIGINT,p_fencing_token BIGINT,
    p_container_name TEXT,p_container_id TEXT,p_plan_hash TEXT,p_state TEXT,
    p_actor_type TEXT,p_actor_id TEXT,p_reason TEXT,p_trace_id TEXT,
    p_correlation_id TEXT,p_causation_id TEXT,p_command_id TEXT,
    p_idempotency_key TEXT,p_payload_hash TEXT,p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_command public.command_receipts%ROWTYPE;
    v_process public.docker_process_runs%ROWTYPE;
    v_process_id TEXT := 'dproc-' || gen_random_uuid()::text;
    v_observation_id TEXT := 'dobs-' || gen_random_uuid()::text;
    v_event_id TEXT;
    v_response JSONB;
BEGIN
    IF p_actor_type NOT IN ('control_plane','system_operator','scheduler') THEN
        RAISE EXCEPTION 'DOCKER_ADAPTER_AUTHORITY_UNAUTHORIZED';
    END IF;
    v_command := public.hermes_p3_docker_begin_command(
        p_project_id,'docker_process.record',p_command_id,p_idempotency_key,p_payload_hash
    );
    IF v_command.status = 'APPLIED' THEN
        RETURN v_command.result->'response';
    END IF;
    SELECT * INTO v_process
    FROM public.docker_process_runs
    WHERE project_id=p_project_id AND execution_request_id=p_execution_request_id
      AND run_id=p_run_id
    FOR UPDATE;
    IF FOUND THEN
        IF v_process.lease_id <> p_lease_id OR v_process.lease_version <> p_lease_version
           OR v_process.fencing_token <> p_fencing_token THEN
            INSERT INTO public.docker_process_reconcile_findings(
                finding_id,project_id,process_id,finding_type,finding_state,
                safe_summary,command_id,event_id
            ) VALUES (
                'dfind-' || gen_random_uuid()::text,p_project_id,v_process.process_id,
                'STALE_CONTAINER','OPEN',
                jsonb_build_object('run_id',p_run_id,'submitted_fencing_token',p_fencing_token,'current_fencing_token',v_process.fencing_token),
                p_command_id,
                public.hermes_p3_docker_append_event(
                    p_project_id,p_command_id,'docker.stale_container_detected',
                    p_actor_type,p_actor_id,jsonb_build_object('run_id',p_run_id),''
                )
            );
            RAISE EXCEPTION 'DOCKER_STALE_FENCING_TOKEN';
        END IF;
        v_process_id := v_process.process_id;
    END IF;

    v_event_id := public.hermes_p3_docker_append_event(
        p_project_id,p_command_id,'docker.process_observed',p_actor_type,p_actor_id,
        jsonb_build_object(
            'process_id',v_process_id,'execution_request_id',p_execution_request_id,
            'run_id',p_run_id,'lease_id',p_lease_id,'lease_version',p_lease_version,
            'fencing_token',p_fencing_token,'state',p_state,'container_name',p_container_name,
            'plan_hash',p_plan_hash,'trace_id',p_trace_id
        ),
        p_correlation_id
    );
    IF p_fault_point = 'after_event_before_state' THEN
        RAISE EXCEPTION 'INJECTED_P3_DOCKER_CRASH_AFTER_EVENT';
    END IF;
    IF FOUND THEN
        UPDATE public.docker_process_runs
        SET lifecycle_state=p_state, container_id=COALESCE(NULLIF(p_container_id,''),container_id),
            last_event_id=v_event_id, version=version+1, updated_at=clock_timestamp()
        WHERE process_id=v_process_id;
    ELSE
        INSERT INTO public.docker_process_runs(
            process_id,project_id,execution_request_id,run_id,lease_id,lease_version,
            fencing_token,container_name,container_id,plan_hash,lifecycle_state,
            trace_id,correlation_id,causation_id,command_id,last_event_id
        ) VALUES (
            v_process_id,p_project_id,p_execution_request_id,p_run_id,p_lease_id,
            p_lease_version,p_fencing_token,p_container_name,p_container_id,p_plan_hash,
            p_state,p_trace_id,p_correlation_id,p_causation_id,p_command_id,v_event_id
        );
    END IF;
    INSERT INTO public.docker_process_observations(
        observation_id,process_id,project_id,execution_request_id,run_id,lease_id,
        lease_version,fencing_token,observed_state,container_id,plan_hash,
        actor_type,actor_id,reason,command_id,event_id,idempotency_key
    ) VALUES (
        v_observation_id,v_process_id,p_project_id,p_execution_request_id,p_run_id,
        p_lease_id,p_lease_version,p_fencing_token,p_state,p_container_id,p_plan_hash,
        p_actor_type,p_actor_id,p_reason,p_command_id,v_event_id,p_idempotency_key
    );
    v_response := jsonb_build_object(
        'result_code','DOCKER_PROCESS_RECORDED',
        'process_id',v_process_id,'observation_id',v_observation_id,
        'lifecycle_state',p_state,'event_id',v_event_id
    );
    PERFORM public.hermes_p3_docker_complete_command(
        p_command_id,'APPLIED',jsonb_build_object('response',v_response,'events',jsonb_build_array(v_event_id))
    );
    RETURN v_response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_record_external_side_effect_receipt(
    p_project_id TEXT,p_execution_request_id TEXT,p_run_id TEXT,
    p_lease_id TEXT,p_lease_version BIGINT,p_fencing_token BIGINT,
    p_side_effect_key TEXT,p_action_class TEXT,p_target_class TEXT,p_reversible BOOLEAN,
    p_human_gate_authorization_ref TEXT,p_request_payload_hash TEXT,
    p_external_receipt_ref TEXT,p_external_receipt_hash TEXT,p_observed_outcome TEXT,
    p_actor_type TEXT,p_actor_id TEXT,p_trace_id TEXT,p_correlation_id TEXT,
    p_causation_id TEXT,p_command_id TEXT,p_idempotency_key TEXT,
    p_payload_hash TEXT,p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_command public.command_receipts%ROWTYPE;
    v_process public.docker_process_runs%ROWTYPE;
    v_existing public.external_side_effect_receipts%ROWTYPE;
    v_receipt_id TEXT := 'sfx-' || gen_random_uuid()::text;
    v_event_id TEXT;
    v_state TEXT := 'MATCHED';
    v_response JSONB;
BEGIN
    IF p_actor_type NOT IN ('control_plane','system_operator') THEN
        RAISE EXCEPTION 'SIDE_EFFECT_AUTHORITY_UNAUTHORIZED';
    END IF;
    IF NOT p_reversible AND COALESCE(p_human_gate_authorization_ref,'') = '' THEN
        RAISE EXCEPTION 'SIDE_EFFECT_IRREVERSIBLE_REQUIRES_GATE';
    END IF;
    v_command := public.hermes_p3_docker_begin_command(
        p_project_id,'external_side_effect.receipt',p_command_id,p_idempotency_key,p_payload_hash
    );
    IF v_command.status = 'APPLIED' THEN
        RETURN v_command.result->'response';
    END IF;
    SELECT * INTO v_process
    FROM public.docker_process_runs
    WHERE project_id=p_project_id AND execution_request_id=p_execution_request_id
      AND run_id=p_run_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'RECEIPT_WITHOUT_CURRENT_EXECUTION';
    END IF;
    IF v_process.lease_id <> p_lease_id OR v_process.lease_version <> p_lease_version
       OR v_process.fencing_token <> p_fencing_token THEN
        RAISE EXCEPTION 'DOCKER_STALE_FENCING_TOKEN';
    END IF;
    SELECT * INTO v_existing
    FROM public.external_side_effect_receipts
    WHERE project_id=p_project_id AND side_effect_key=p_side_effect_key
    FOR UPDATE;
    IF FOUND THEN
        IF v_existing.request_payload_hash <> p_request_payload_hash
           OR v_existing.external_receipt_hash <> p_external_receipt_hash THEN
            RAISE EXCEPTION 'SIDE_EFFECT_IDEMPOTENCY_CONFLICT';
        END IF;
        RETURN jsonb_build_object(
            'result_code','SIDE_EFFECT_RECEIPT_RECORDED',
            'receipt_id',v_existing.receipt_id,
            'reconciliation_state',v_existing.reconciliation_state,
            'event_id',v_existing.event_id
        );
    END IF;
    IF p_observed_outcome = 'UNKNOWN' THEN
        v_state := 'RECONCILE_REQUIRED';
    END IF;
    IF p_fault_point = 'after_effect_before_receipt' THEN
        v_state := 'RECONCILE_REQUIRED';
        INSERT INTO public.docker_process_reconcile_findings(
            finding_id,project_id,process_id,finding_type,finding_state,
            safe_summary,command_id,event_id
        ) VALUES (
            'dfind-' || gen_random_uuid()::text,p_project_id,v_process.process_id,
            'EFFECT_BEFORE_RECEIPT','OPEN',
            jsonb_build_object('side_effect_key',p_side_effect_key,'outcome','UNKNOWN'),
            p_command_id,
            public.hermes_p3_docker_append_event(
                p_project_id,p_command_id,'execution.side_effect_unknown',
                p_actor_type,p_actor_id,jsonb_build_object('side_effect_key',p_side_effect_key),p_correlation_id
            )
        );
        RAISE EXCEPTION 'SIDE_EFFECT_RECEIPT_UNKNOWN_RECONCILE_REQUIRED';
    END IF;
    v_event_id := public.hermes_p3_docker_append_event(
        p_project_id,p_command_id,'execution.side_effect_receipted',
        p_actor_type,p_actor_id,
        jsonb_build_object(
            'receipt_id',v_receipt_id,'side_effect_key',p_side_effect_key,
            'run_id',p_run_id,'lease_id',p_lease_id,'fencing_token',p_fencing_token,
            'request_payload_hash',p_request_payload_hash,'external_receipt_hash',p_external_receipt_hash,
            'observed_outcome',p_observed_outcome,'reconciliation_state',v_state,
            'trace_id',p_trace_id
        ),
        p_correlation_id
    );
    INSERT INTO public.external_side_effect_receipts(
        receipt_id,project_id,execution_request_id,run_id,process_id,lease_id,
        lease_version,fencing_token,side_effect_key,action_class,target_class,
        reversible,human_gate_authorization_ref,request_payload_hash,
        external_receipt_ref,external_receipt_hash,observed_outcome,
        reconciliation_state,actor_type,actor_id,trace_id,correlation_id,
        causation_id,command_id,event_id,idempotency_key
    ) VALUES (
        v_receipt_id,p_project_id,p_execution_request_id,p_run_id,v_process.process_id,
        p_lease_id,p_lease_version,p_fencing_token,p_side_effect_key,p_action_class,
        p_target_class,p_reversible,p_human_gate_authorization_ref,
        p_request_payload_hash,p_external_receipt_ref,p_external_receipt_hash,
        p_observed_outcome,v_state,p_actor_type,p_actor_id,p_trace_id,
        p_correlation_id,p_causation_id,p_command_id,v_event_id,p_idempotency_key
    );
    v_response := jsonb_build_object(
        'result_code','SIDE_EFFECT_RECEIPT_RECORDED',
        'receipt_id',v_receipt_id,'reconciliation_state',v_state,'event_id',v_event_id
    );
    PERFORM public.hermes_p3_docker_complete_command(
        p_command_id,'APPLIED',jsonb_build_object('response',v_response,'events',jsonb_build_array(v_event_id))
    );
    RETURN v_response;
END;
$$;

ALTER TABLE public.docker_process_runs OWNER TO hermes_p3_docker_owner;
ALTER TABLE public.docker_process_observations OWNER TO hermes_p3_docker_owner;
ALTER TABLE public.external_side_effect_receipts OWNER TO hermes_p3_docker_owner;
ALTER TABLE public.docker_process_reconcile_findings OWNER TO hermes_p3_docker_owner;
ALTER FUNCTION public.hermes_p3_docker_reject_append_only_change() OWNER TO hermes_p3_docker_owner;
ALTER FUNCTION public.hermes_p3_docker_begin_command(TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_p3_docker_owner;
ALTER FUNCTION public.hermes_p3_docker_complete_command(TEXT,TEXT,JSONB) OWNER TO hermes_p3_docker_owner;
ALTER FUNCTION public.hermes_p3_docker_append_event(TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) OWNER TO hermes_p3_docker_owner;
ALTER FUNCTION public.hermes_record_docker_process(TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_p3_docker_owner;
ALTER FUNCTION public.hermes_record_external_side_effect_receipt(TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_p3_docker_owner;

GRANT SELECT, INSERT, UPDATE ON public.command_receipts TO hermes_p3_docker_owner;
GRANT SELECT, INSERT ON public.event_log, public.outbox_messages TO hermes_p3_docker_owner;
GRANT SELECT, INSERT, UPDATE ON public.docker_process_runs TO hermes_p3_docker_owner;
GRANT SELECT, INSERT ON public.docker_process_observations,
    public.external_side_effect_receipts, public.docker_process_reconcile_findings
TO hermes_p3_docker_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_p3_docker_owner;

GRANT SELECT ON public.docker_process_runs, public.docker_process_observations,
    public.external_side_effect_receipts, public.docker_process_reconcile_findings
TO hermes_read_only_runtime;

REVOKE ALL ON public.docker_process_runs, public.docker_process_observations,
    public.external_side_effect_receipts, public.docker_process_reconcile_findings
FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE ON public.docker_process_runs,
    public.docker_process_observations, public.external_side_effect_receipts,
    public.docker_process_reconcile_findings
FROM hermes_docker_adapter_runtime, hermes_side_effect_runtime,
     hermes_worker_runtime, hermes_verifier_runtime, hermes_scheduler_runtime,
     hermes_execution_runtime, hermes_control_plane_runtime, hermes_read_only_runtime,
     PUBLIC;

REVOKE ALL ON FUNCTION public.hermes_p3_docker_reject_append_only_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_docker_begin_command(TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_docker_complete_command(TEXT,TEXT,JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_docker_append_event(TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_record_docker_process(TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_record_external_side_effect_receipt(TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.hermes_record_docker_process(TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
TO hermes_docker_adapter_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_record_external_side_effect_receipt(TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
TO hermes_side_effect_runtime;
REVOKE EXECUTE ON FUNCTION public.hermes_record_docker_process(TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
    public.hermes_record_external_side_effect_receipt(TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
FROM hermes_worker_runtime, hermes_verifier_runtime, hermes_scheduler_runtime,
     hermes_execution_runtime, hermes_control_plane_runtime, hermes_read_only_runtime,
     PUBLIC;

REVOKE CREATE ON SCHEMA public FROM hermes_docker_adapter_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_side_effect_runtime;

COMMENT ON TABLE public.docker_process_runs IS
'P3-5 current Docker process manager state bound to ExecutionRequest, AgentRun, Lease and fencing token; Docker is external and cannot write Hermes authority directly.';
COMMENT ON TABLE public.docker_process_observations IS
'Append-only Docker process lifecycle observations with Event/Outbox/Receipt links.';
COMMENT ON TABLE public.external_side_effect_receipts IS
'Append-only external side-effect receipt facts; they are not Project/Task authority and require current fencing plus Gate for irreversible effects.';
COMMENT ON TABLE public.docker_process_reconcile_findings IS
'Append-only findings for stale/orphan/unknown Docker or side-effect outcomes; repair remains guarded by owning authorities.';
