-- P2-5: Structured feedback and bounded autonomous recovery loop.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_recovery_owner') THEN
        CREATE ROLE hermes_recovery_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_recovery_runtime') THEN
        CREATE ROLE hermes_recovery_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.execution_feedback_records (
    feedback_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    source_result_id TEXT NOT NULL UNIQUE REFERENCES public.execution_results(result_id),
    source_event_id TEXT NOT NULL UNIQUE REFERENCES public.event_log(event_id),
    failure_type TEXT NOT NULL CHECK (failure_type IN (
        'test_assertion_failure','build_failure','adapter_transient',
        'worker_timeout','policy_denied','budget_exhausted',
        'sandbox_violation','unknown_execution_failure'
    )),
    severity TEXT NOT NULL CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    affected_artifact_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    finding_codes TEXT[] NOT NULL DEFAULT '{}',
    root_cause TEXT,
    recommended_actions TEXT[] NOT NULL CHECK (cardinality(recommended_actions) > 0),
    recovery_level TEXT NOT NULL CHECK (recovery_level IN (
        'L0_RETRY','L1_REPAIR','L2_SWITCH_STRATEGY','L3_SWITCH_WORKER',
        'L4_COLLABORATION','L5_REPLAN','L6_HUMAN_GATE'
    )),
    payload_hash TEXT NOT NULL CHECK (payload_hash LIKE 'sha256:%'),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.recovery_cycles (
    cycle_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    feedback_id TEXT NOT NULL UNIQUE REFERENCES public.execution_feedback_records(feedback_id),
    source_result_id TEXT NOT NULL REFERENCES public.execution_results(result_id),
    strategy_key TEXT NOT NULL,
    policy_version TEXT NOT NULL DEFAULT 'recovery-policy/1.0',
    max_attempts INTEGER NOT NULL CHECK (max_attempts BETWEEN 1 AND 20),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    cycle_state TEXT NOT NULL CHECK (cycle_state IN ('OPEN','COMPLETED','EXHAUSTED','BLOCKED')),
    command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    event_id TEXT NOT NULL UNIQUE REFERENCES public.event_log(event_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.recovery_attempts (
    attempt_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL REFERENCES public.recovery_cycles(cycle_id),
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    feedback_id TEXT NOT NULL REFERENCES public.execution_feedback_records(feedback_id),
    attempt_ordinal INTEGER NOT NULL CHECK (attempt_ordinal >= 1),
    recovery_level TEXT NOT NULL CHECK (recovery_level IN (
        'L0_RETRY','L1_REPAIR','L2_SWITCH_STRATEGY','L3_SWITCH_WORKER',
        'L4_COLLABORATION','L5_REPLAN','L6_HUMAN_GATE'
    )),
    action_type TEXT NOT NULL CHECK (action_type IN (
        'retry','repair','switch_strategy','switch_worker',
        'collaboration','replan','human_gate'
    )),
    attempt_state TEXT NOT NULL CHECK (attempt_state IN (
        'PLANNED','RUNNING','SUCCEEDED','FAILED','BLOCKED'
    )),
    reason_code TEXT NOT NULL,
    selected_action_id TEXT REFERENCES public.candidate_actions(action_id),
    execution_request_id TEXT REFERENCES public.execution_requests(execution_request_id),
    result_id TEXT REFERENCES public.execution_results(result_id),
    verification_id TEXT REFERENCES public.verification_results(verification_id),
    budget_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    event_id TEXT NOT NULL UNIQUE REFERENCES public.event_log(event_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (cycle_id, attempt_ordinal)
);

CREATE TABLE IF NOT EXISTS public.recovery_collaboration_requests (
    collaboration_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL REFERENCES public.recovery_cycles(cycle_id),
    attempt_id TEXT NOT NULL UNIQUE REFERENCES public.recovery_attempts(attempt_id),
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    required_capability TEXT NOT NULL,
    objective TEXT NOT NULL,
    budget_envelope JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('REQUESTED','SATISFIED','CANCELLED')),
    command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.hermes_recovery_secret_guard(p_payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
    SELECT p_payload::text ~* '("(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value)"[[:space:]]*:|private key|sk-[A-Za-z0-9]{12,}|password=)'
$$;

CREATE OR REPLACE FUNCTION public.hermes_reject_recovery_immutable_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS execution_feedback_immutable ON public.execution_feedback_records;
CREATE TRIGGER execution_feedback_immutable
BEFORE UPDATE OR DELETE ON public.execution_feedback_records
FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_recovery_immutable_change();

CREATE OR REPLACE FUNCTION public.hermes_recovery_append_event(
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
        RAISE EXCEPTION 'INJECTED_RECOVERY_CRASH_AFTER_EVENT';
    END IF;
    INSERT INTO public.outbox_messages(message_id, event_id, topic, partition_key, sequence, payload)
    VALUES ('msg-' || gen_random_uuid()::text, v_event_id, 'hermes.runtime.events',
            p_project_id, v_sequence, p_payload);
    RETURN v_event_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_recovery_classification(
    p_error_classification TEXT,
    p_outcome TEXT
) RETURNS JSONB
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog
AS $$
DECLARE
    normalized TEXT := lower(replace(replace(COALESCE(p_error_classification,''), '-', '_'), ' ', '_'));
BEGIN
    IF p_outcome = 'SUCCEEDED' THEN
        RAISE EXCEPTION 'RECOVERY_FEEDBACK_SOURCE_NOT_FAILED';
    END IF;
    IF normalized IN ('test_assertion_failure','assertion_failure') THEN
        RETURN jsonb_build_object('failure_type','test_assertion_failure','severity','HIGH',
            'finding_codes', jsonb_build_array('TEST_ASSERTION_FAILURE'),
            'recommended_actions', jsonb_build_array('repair','retry'),
            'recovery_level','L1_REPAIR','root_cause','test_assertion_failure');
    ELSIF normalized IN ('build_failure','compile_error') THEN
        RETURN jsonb_build_object('failure_type','build_failure','severity','HIGH',
            'finding_codes', jsonb_build_array('BUILD_FAILURE'),
            'recommended_actions', jsonb_build_array('repair','retry'),
            'recovery_level','L1_REPAIR','root_cause','build_failure');
    ELSIF normalized IN ('adapter_transient','tool_transient') THEN
        RETURN jsonb_build_object('failure_type','adapter_transient','severity','MEDIUM',
            'finding_codes', jsonb_build_array('ADAPTER_TRANSIENT'),
            'recommended_actions', jsonb_build_array('retry','switch_worker'),
            'recovery_level','L0_RETRY','root_cause',NULL);
    ELSIF normalized IN ('timeout','worker_timeout') THEN
        RETURN jsonb_build_object('failure_type','worker_timeout','severity','MEDIUM',
            'finding_codes', jsonb_build_array('WORKER_TIMEOUT'),
            'recommended_actions', jsonb_build_array('retry','switch_worker'),
            'recovery_level','L0_RETRY','root_cause',NULL);
    ELSIF normalized = 'policy_denied' THEN
        RETURN jsonb_build_object('failure_type','policy_denied','severity','HIGH',
            'finding_codes', jsonb_build_array('POLICY_DENIED'),
            'recommended_actions', jsonb_build_array('switch_strategy','human_gate'),
            'recovery_level','L2_SWITCH_STRATEGY','root_cause',NULL);
    ELSIF normalized = 'budget_exhausted' THEN
        RETURN jsonb_build_object('failure_type','budget_exhausted','severity','HIGH',
            'finding_codes', jsonb_build_array('BUDGET_EXHAUSTED'),
            'recommended_actions', jsonb_build_array('switch_strategy','human_gate'),
            'recovery_level','L2_SWITCH_STRATEGY','root_cause',NULL);
    ELSIF normalized = 'sandbox_violation' THEN
        RETURN jsonb_build_object('failure_type','sandbox_violation','severity','CRITICAL',
            'finding_codes', jsonb_build_array('SANDBOX_VIOLATION'),
            'recommended_actions', jsonb_build_array('human_gate'),
            'recovery_level','L6_HUMAN_GATE','root_cause',NULL);
    END IF;
    RETURN jsonb_build_object('failure_type','unknown_execution_failure','severity','MEDIUM',
        'finding_codes', jsonb_build_array('UNKNOWN_EXECUTION_FAILURE'),
        'recommended_actions', jsonb_build_array('replan','human_gate'),
        'recovery_level','L5_REPLAN','root_cause',NULL);
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_emit_execution_feedback(
    p_project_id TEXT,
    p_result_id TEXT,
    p_feedback_id TEXT,
    p_repair_task_id TEXT,
    p_max_attempts INTEGER,
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
    result_row public.execution_results%ROWTYPE;
    request_row public.execution_requests%ROWTYPE;
    graph_version BIGINT;
    classification JSONB;
    feedback_event_id TEXT;
    cycle_event_id TEXT;
    cycle_id TEXT;
    feedback_payload JSONB;
    cycle_payload JSONB;
    recommended TEXT[];
    findings TEXT[];
    response JSONB;
BEGIN
    IF p_actor_type <> 'recovery_controller' THEN
        RAISE EXCEPTION 'RECOVERY_AUTHORITY_REQUIRED';
    END IF;
    IF p_max_attempts < 1 OR p_max_attempts > 20 THEN
        RAISE EXCEPTION 'RECOVERY_POLICY_INVALID';
    END IF;
    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key,
        request_hash, status, result
    ) VALUES (
        p_command_id, p_project_id, 'recovery.emit_feedback',
        p_idempotency_key, p_payload_hash, 'PROCESSING', '{}'::jsonb
    ) ON CONFLICT DO NOTHING;
    SELECT * INTO command_row
    FROM public.command_receipts
    WHERE project_id=p_project_id AND command_type='recovery.emit_feedback'
      AND idempotency_key=p_idempotency_key
    FOR UPDATE;
    IF NOT FOUND OR command_row.request_hash <> p_payload_hash THEN
        RAISE EXCEPTION 'RECOVERY_IDEMPOTENCY_CONFLICT';
    END IF;
    IF command_row.status='APPLIED' THEN
        RETURN command_row.result->'response';
    END IF;

    SELECT * INTO result_row
    FROM public.execution_results
    WHERE result_id=p_result_id AND project_id=p_project_id;
    IF NOT FOUND OR result_row.terminal_state <> 'FAILED' THEN
        RAISE EXCEPTION 'RECOVERY_FEEDBACK_SOURCE_NOT_FAILED';
    END IF;
    SELECT * INTO request_row
    FROM public.execution_requests
    WHERE execution_request_id=result_row.execution_request_id
      AND project_id=p_project_id;
    SELECT pgv.graph_version INTO graph_version
    FROM public.project_graph_versions pgv
    WHERE pgv.project_id=p_project_id;
    graph_version := COALESCE(graph_version, 0);

    classification := public.hermes_recovery_classification(
        result_row.error_classification, result_row.outcome
    );
    findings := ARRAY(SELECT jsonb_array_elements_text(classification->'finding_codes'));
    recommended := ARRAY(SELECT jsonb_array_elements_text(classification->'recommended_actions'));
    feedback_payload := jsonb_build_object(
        'feedback_id', p_feedback_id,
        'project_id', p_project_id,
        'source', jsonb_build_object('type','execution_result','id',p_result_id),
        'failure_type', classification->>'failure_type',
        'severity', classification->>'severity',
        'affected_task_id', result_row.task_id,
        'task_id', result_row.task_id,
        'source_task_id', result_row.task_id,
        'affected_artifact_refs', result_row.artifact_candidate_refs,
        'finding_codes', classification->'finding_codes',
        'root_cause', classification->>'root_cause',
        'evidence_refs', result_row.evidence_candidate_refs,
        'recommended_actions', classification->'recommended_actions',
        'recovery_level', classification->>'recovery_level',
        'verification_id', 'execution-result:' || p_result_id,
        'decision_id', request_row.decision_id,
        'repair_task_id', p_repair_task_id,
        'repair_title', 'Recovery repair for ' || p_feedback_id,
        'base_graph_version', graph_version,
        'result_id', p_result_id
    );
    IF public.hermes_recovery_secret_guard(feedback_payload) THEN
        RAISE EXCEPTION 'SECRET_VALUE_FORBIDDEN';
    END IF;
    feedback_event_id := public.hermes_recovery_append_event(
        p_project_id, result_row.task_id, p_command_id, 'feedback.created',
        p_actor_type, p_actor_id, p_command_id, result_row.command_id,
        feedback_payload, p_fault_point
    );
    IF p_fault_point = 'after_feedback_event' THEN
        RAISE EXCEPTION 'INJECTED_RECOVERY_CRASH_AFTER_FEEDBACK_EVENT';
    END IF;
    INSERT INTO public.execution_feedback_records(
        feedback_id, project_id, task_id, source_result_id, source_event_id,
        failure_type, severity, affected_artifact_refs, evidence_refs,
        finding_codes, root_cause, recommended_actions, recovery_level,
        payload_hash, command_id
    ) VALUES (
        p_feedback_id, p_project_id, result_row.task_id, p_result_id,
        feedback_event_id, classification->>'failure_type',
        classification->>'severity', result_row.artifact_candidate_refs,
        result_row.evidence_candidate_refs, findings, classification->>'root_cause',
        recommended, classification->>'recovery_level', p_payload_hash, p_command_id
    );
    INSERT INTO public.feedback_records(
        feedback_id, project_id, source_event_id, source_task_id,
        verification_id, decision_id, repair_task_id
    ) VALUES (
        p_feedback_id, p_project_id, feedback_event_id, result_row.task_id,
        'execution-result:' || p_result_id, request_row.decision_id,
        p_repair_task_id
    );
    IF p_fault_point = 'after_feedback_record' THEN
        RAISE EXCEPTION 'INJECTED_RECOVERY_CRASH_AFTER_FEEDBACK_RECORD';
    END IF;

    cycle_id := 'cycle-' || p_feedback_id;
    cycle_payload := jsonb_build_object(
        'cycle_id', cycle_id,
        'feedback_id', p_feedback_id,
        'source_result_id', p_result_id,
        'strategy_key', result_row.task_id || ':' || (classification->>'failure_type'),
        'policy_version', 'recovery-policy/1.0',
        'max_attempts', p_max_attempts
    );
    cycle_event_id := public.hermes_recovery_append_event(
        p_project_id, result_row.task_id, p_command_id, 'recovery.cycle_started',
        p_actor_type, p_actor_id, p_command_id, feedback_event_id,
        cycle_payload, p_fault_point
    );
    INSERT INTO public.recovery_cycles(
        cycle_id, project_id, task_id, feedback_id, source_result_id,
        strategy_key, max_attempts, cycle_state, command_id, event_id
    ) VALUES (
        cycle_id, p_project_id, result_row.task_id, p_feedback_id, p_result_id,
        result_row.task_id || ':' || (classification->>'failure_type'),
        p_max_attempts, 'OPEN', p_command_id, cycle_event_id
    );

    response := jsonb_build_object(
        'result_code', 'RECOVERY_FEEDBACK_EMITTED',
        'feedback_id', p_feedback_id,
        'cycle_id', cycle_id,
        'source_result_id', p_result_id,
        'failure_type', classification->>'failure_type',
        'severity', classification->>'severity',
        'recommended_actions', classification->'recommended_actions',
        'recovery_level', classification->>'recovery_level',
        'event_ids', jsonb_build_array(feedback_event_id, cycle_event_id)
    );
    UPDATE public.command_receipts
    SET status='APPLIED',
        result=jsonb_build_object(
            'command_id', p_command_id,
            'status', 'APPLIED',
            'result_code', 'RECOVERY_FEEDBACK_EMITTED',
            'target_version', NULL,
            'event_ids', jsonb_build_array(feedback_event_id, cycle_event_id),
            'response', response
        ),
        completed_at=now()
    WHERE command_id=p_command_id AND status='PROCESSING';
    IF p_fault_point = 'after_receipt_before_commit' THEN
        RAISE EXCEPTION 'INJECTED_RECOVERY_CRASH_AFTER_RECEIPT';
    END IF;
    RETURN response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_plan_recovery_attempt(
    p_project_id TEXT,
    p_cycle_id TEXT,
    p_attempt_id TEXT,
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
    cycle_row public.recovery_cycles%ROWTYPE;
    feedback_row public.execution_feedback_records%ROWTYPE;
    ordinal INTEGER;
    action TEXT;
    level TEXT;
    event_id TEXT;
    response JSONB;
    action_index INTEGER;
    exhausted BOOLEAN := false;
    reason_code TEXT;
    attempt_state TEXT;
BEGIN
    IF p_actor_type <> 'recovery_controller' THEN
        RAISE EXCEPTION 'RECOVERY_AUTHORITY_REQUIRED';
    END IF;
    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key,
        request_hash, status, result
    ) VALUES (
        p_command_id, p_project_id, 'recovery.plan_attempt',
        p_idempotency_key, p_payload_hash, 'PROCESSING', '{}'::jsonb
    ) ON CONFLICT DO NOTHING;
    SELECT * INTO command_row
    FROM public.command_receipts
    WHERE project_id=p_project_id AND command_type='recovery.plan_attempt'
      AND idempotency_key=p_idempotency_key
    FOR UPDATE;
    IF NOT FOUND OR command_row.request_hash <> p_payload_hash THEN
        RAISE EXCEPTION 'RECOVERY_IDEMPOTENCY_CONFLICT';
    END IF;
    IF command_row.status='APPLIED' THEN
        RETURN command_row.result->'response';
    END IF;

    SELECT * INTO cycle_row
    FROM public.recovery_cycles
    WHERE cycle_id=p_cycle_id AND project_id=p_project_id
    FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'RECOVERY_CYCLE_NOT_FOUND'; END IF;
    SELECT * INTO feedback_row
    FROM public.execution_feedback_records
    WHERE feedback_id=cycle_row.feedback_id;
    IF cycle_row.cycle_state <> 'OPEN' THEN
        RAISE EXCEPTION 'RECOVERY_CYCLE_NOT_OPEN';
    END IF;
    ordinal := cycle_row.attempt_count + 1;
    IF cycle_row.attempt_count >= cycle_row.max_attempts THEN
        exhausted := true;
        action := 'human_gate';
        level := 'L6_HUMAN_GATE';
        UPDATE public.recovery_cycles
        SET cycle_state='EXHAUSTED', updated_at=now()
        WHERE cycle_id=p_cycle_id;
    ELSE
        action_index := (cycle_row.attempt_count % cardinality(feedback_row.recommended_actions)) + 1;
        action := feedback_row.recommended_actions[action_index];
        level := CASE action
            WHEN 'retry' THEN 'L0_RETRY'
            WHEN 'repair' THEN 'L1_REPAIR'
            WHEN 'switch_strategy' THEN 'L2_SWITCH_STRATEGY'
            WHEN 'switch_worker' THEN 'L3_SWITCH_WORKER'
            WHEN 'collaboration' THEN 'L4_COLLABORATION'
            WHEN 'replan' THEN 'L5_REPLAN'
            ELSE 'L6_HUMAN_GATE' END;
        UPDATE public.recovery_cycles
        SET attempt_count=attempt_count + 1, updated_at=now()
        WHERE cycle_id=p_cycle_id;
    END IF;
    reason_code := CASE WHEN exhausted THEN 'RECOVERY_EXHAUSTED'
                        ELSE 'RECOVERY_ATTEMPT_PLANNED' END;
    attempt_state := CASE WHEN exhausted THEN 'BLOCKED' ELSE 'PLANNED' END;
    event_id := public.hermes_recovery_append_event(
        p_project_id, cycle_row.task_id, p_command_id, 'recovery.attempt_planned',
        p_actor_type, p_actor_id, p_command_id, cycle_row.event_id,
        jsonb_build_object(
            'cycle_id', p_cycle_id,
            'attempt_id', p_attempt_id,
            'attempt_ordinal', ordinal,
            'action_type', action,
            'recovery_level', level,
            'reason_code', reason_code
        ),
        p_fault_point
    );
    INSERT INTO public.recovery_attempts(
        attempt_id, cycle_id, project_id, task_id, feedback_id, attempt_ordinal,
        recovery_level, action_type, attempt_state, reason_code, command_id, event_id
    ) VALUES (
        p_attempt_id, p_cycle_id, p_project_id, cycle_row.task_id,
        cycle_row.feedback_id, ordinal, level, action,
        attempt_state,
        reason_code,
        p_command_id, event_id
    );
    IF action='collaboration' THEN
        INSERT INTO public.recovery_collaboration_requests(
            collaboration_id, cycle_id, attempt_id, project_id, task_id,
            required_capability, objective, budget_envelope, status, command_id
        ) VALUES (
            'collab-' || p_attempt_id, p_cycle_id, p_attempt_id, p_project_id,
            cycle_row.task_id, 'expert_review',
            'Provide bounded specialist evidence for ' || cycle_row.feedback_id,
            jsonb_build_object('retry_count', 1, 'human_attention_requests', 0),
            'REQUESTED', p_command_id
        );
    END IF;
    response := jsonb_build_object(
        'result_code', CASE WHEN exhausted THEN 'RECOVERY_EXHAUSTED'
                            ELSE 'RECOVERY_ATTEMPT_PLANNED' END,
        'cycle_id', p_cycle_id,
        'attempt_id', p_attempt_id,
        'attempt_ordinal', ordinal,
        'action_type', action,
        'recovery_level', level,
        'event_ids', jsonb_build_array(event_id)
    );
    UPDATE public.command_receipts
    SET status='APPLIED',
        result=jsonb_build_object(
            'command_id', p_command_id,
            'status', 'APPLIED',
            'result_code', response->>'result_code',
            'target_version', NULL,
            'event_ids', jsonb_build_array(event_id),
            'response', response
        ),
        completed_at=now()
    WHERE command_id=p_command_id AND status='PROCESSING';
    RETURN response;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_complete_recovery_attempt(
    p_project_id TEXT,
    p_attempt_id TEXT,
    p_outcome TEXT,
    p_execution_request_id TEXT,
    p_result_id TEXT,
    p_verification_id TEXT,
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
    attempt_row public.recovery_attempts%ROWTYPE;
    event_id TEXT;
    response JSONB;
BEGIN
    IF p_actor_type <> 'recovery_controller' THEN
        RAISE EXCEPTION 'RECOVERY_AUTHORITY_REQUIRED';
    END IF;
    IF p_outcome NOT IN ('SUCCEEDED','FAILED','BLOCKED') THEN
        RAISE EXCEPTION 'RECOVERY_ATTEMPT_OUTCOME_INVALID';
    END IF;
    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key,
        request_hash, status, result
    ) VALUES (
        p_command_id, p_project_id, 'recovery.complete_attempt',
        p_idempotency_key, p_payload_hash, 'PROCESSING', '{}'::jsonb
    ) ON CONFLICT DO NOTHING;
    SELECT * INTO command_row
    FROM public.command_receipts
    WHERE project_id=p_project_id AND command_type='recovery.complete_attempt'
      AND idempotency_key=p_idempotency_key
    FOR UPDATE;
    IF NOT FOUND OR command_row.request_hash <> p_payload_hash THEN
        RAISE EXCEPTION 'RECOVERY_IDEMPOTENCY_CONFLICT';
    END IF;
    IF command_row.status='APPLIED' THEN
        RETURN command_row.result->'response';
    END IF;
    SELECT * INTO attempt_row
    FROM public.recovery_attempts
    WHERE attempt_id=p_attempt_id AND project_id=p_project_id
    FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'RECOVERY_ATTEMPT_NOT_FOUND'; END IF;
    IF attempt_row.attempt_state NOT IN ('PLANNED','RUNNING','BLOCKED') THEN
        RAISE EXCEPTION 'RECOVERY_ATTEMPT_ALREADY_TERMINAL';
    END IF;
    event_id := public.hermes_recovery_append_event(
        p_project_id, attempt_row.task_id, p_command_id,
        CASE WHEN p_outcome='SUCCEEDED' THEN 'recovery.attempt_succeeded'
             WHEN p_outcome='FAILED' THEN 'recovery.attempt_failed'
             ELSE 'recovery.attempt_blocked' END,
        p_actor_type, p_actor_id, p_command_id, attempt_row.event_id,
        jsonb_build_object(
            'attempt_id', p_attempt_id,
            'cycle_id', attempt_row.cycle_id,
            'outcome', p_outcome,
            'execution_request_id', NULLIF(p_execution_request_id,''),
            'result_id', NULLIF(p_result_id,''),
            'verification_id', NULLIF(p_verification_id,'')
        ),
        p_fault_point
    );
    UPDATE public.recovery_attempts
    SET attempt_state=p_outcome,
        execution_request_id=NULLIF(p_execution_request_id,''),
        result_id=NULLIF(p_result_id,''),
        verification_id=NULLIF(p_verification_id,''),
        completed_at=now()
    WHERE attempt_id=p_attempt_id;
    IF p_outcome='SUCCEEDED' THEN
        UPDATE public.recovery_cycles
        SET cycle_state='COMPLETED', updated_at=now()
        WHERE cycle_id=attempt_row.cycle_id;
    ELSIF p_outcome='BLOCKED' THEN
        UPDATE public.recovery_cycles
        SET cycle_state='BLOCKED', updated_at=now()
        WHERE cycle_id=attempt_row.cycle_id;
    END IF;
    response := jsonb_build_object(
        'result_code', 'RECOVERY_ATTEMPT_COMPLETED',
        'attempt_id', p_attempt_id,
        'cycle_id', attempt_row.cycle_id,
        'outcome', p_outcome,
        'event_ids', jsonb_build_array(event_id)
    );
    UPDATE public.command_receipts
    SET status='APPLIED',
        result=jsonb_build_object(
            'command_id', p_command_id,
            'status', 'APPLIED',
            'result_code', 'RECOVERY_ATTEMPT_COMPLETED',
            'target_version', NULL,
            'event_ids', jsonb_build_array(event_id),
            'response', response
        ),
        completed_at=now()
    WHERE command_id=p_command_id AND status='PROCESSING';
    RETURN response;
END;
$$;

ALTER TABLE public.execution_feedback_records OWNER TO hermes_recovery_owner;
ALTER TABLE public.recovery_cycles OWNER TO hermes_recovery_owner;
ALTER TABLE public.recovery_attempts OWNER TO hermes_recovery_owner;
ALTER TABLE public.recovery_collaboration_requests OWNER TO hermes_recovery_owner;
ALTER FUNCTION public.hermes_recovery_secret_guard(JSONB) OWNER TO hermes_recovery_owner;
ALTER FUNCTION public.hermes_reject_recovery_immutable_change() OWNER TO hermes_recovery_owner;
ALTER FUNCTION public.hermes_recovery_append_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) OWNER TO hermes_recovery_owner;
ALTER FUNCTION public.hermes_recovery_classification(TEXT,TEXT) OWNER TO hermes_recovery_owner;
ALTER FUNCTION public.hermes_emit_execution_feedback(TEXT,TEXT,TEXT,TEXT,INTEGER,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_recovery_owner;
ALTER FUNCTION public.hermes_plan_recovery_attempt(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_recovery_owner;
ALTER FUNCTION public.hermes_complete_recovery_attempt(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_recovery_owner;

GRANT SELECT ON public.projects, public.tasks, public.project_graph_versions,
    public.execution_results, public.execution_requests, public.command_receipts,
    public.event_log, public.outbox_messages, public.feedback_records,
    public.candidate_actions, public.verification_results
    TO hermes_recovery_owner;
GRANT SELECT, INSERT, UPDATE ON public.command_receipts TO hermes_recovery_owner;
GRANT INSERT ON public.execution_feedback_records, public.recovery_cycles,
    public.recovery_attempts, public.recovery_collaboration_requests,
    public.feedback_records, public.event_log, public.outbox_messages,
    public.audit_records
    TO hermes_recovery_owner;
GRANT UPDATE ON public.recovery_cycles, public.recovery_attempts
    TO hermes_recovery_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_recovery_owner;

GRANT EXECUTE ON FUNCTION public.hermes_emit_execution_feedback(TEXT,TEXT,TEXT,TEXT,INTEGER,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO hermes_recovery_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_plan_recovery_attempt(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO hermes_recovery_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_complete_recovery_attempt(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO hermes_recovery_runtime;
GRANT SELECT ON public.execution_feedback_records, public.recovery_cycles,
    public.recovery_attempts, public.recovery_collaboration_requests
    TO hermes_recovery_runtime, hermes_read_only_runtime, hermes_control_plane_runtime;

REVOKE ALL ON public.execution_feedback_records, public.recovery_cycles,
    public.recovery_attempts, public.recovery_collaboration_requests FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE ON public.execution_feedback_records,
    public.recovery_cycles, public.recovery_attempts,
    public.recovery_collaboration_requests
FROM hermes_worker_runtime, hermes_scheduler_runtime, hermes_accounting_runtime,
     hermes_verifier_runtime, hermes_control_plane_runtime, hermes_read_only_runtime,
     hermes_execution_runtime, hermes_capability_runtime, hermes_selection_runtime,
     hermes_policy_runtime, hermes_risk_runtime, hermes_planner_runtime,
     hermes_diagnosis_runtime, hermes_situation_runtime, hermes_recovery_runtime;
REVOKE ALL ON FUNCTION public.hermes_recovery_secret_guard(JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_reject_recovery_immutable_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_recovery_append_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_recovery_classification(TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_emit_execution_feedback(TEXT,TEXT,TEXT,TEXT,INTEGER,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_plan_recovery_attempt(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_complete_recovery_attempt(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.hermes_recovery_append_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT)
FROM hermes_worker_runtime, hermes_scheduler_runtime, hermes_accounting_runtime,
     hermes_verifier_runtime, hermes_control_plane_runtime, hermes_read_only_runtime,
     hermes_execution_runtime, hermes_capability_runtime, hermes_selection_runtime,
     hermes_policy_runtime, hermes_risk_runtime, hermes_planner_runtime,
     hermes_diagnosis_runtime, hermes_situation_runtime, hermes_recovery_runtime,
     PUBLIC;
REVOKE CREATE ON SCHEMA public FROM hermes_recovery_runtime;

COMMENT ON TABLE public.execution_feedback_records IS
'P2-5 structured immutable Feedback facts emitted from failed execution outcomes. Feedback does not mutate Task state directly.';
COMMENT ON TABLE public.recovery_cycles IS
'P2-5 bounded autonomous recovery cycle ledger. Human Gate/P3 replay-reconcile remain out of scope.';
COMMENT ON TABLE public.recovery_attempts IS
'P2-5 recovery attempt ledger for retry/repair/switch/collaboration/replan decisions.';
