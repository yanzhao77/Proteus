-- P6 execution prepare live callsite convergence.
-- Source: fresh 0001→0031 pg_get_functiondef(public.hermes_prepare_execution_request).
-- 0031 remains the canonical structured JSONB secret policy; this migration only
-- replaces the legacy sandbox profile text-regex callsite. CREATE OR REPLACE
-- preserves the existing function signature, owner, privileges, security mode,
-- volatility, parallel attributes, and hardened search_path.

CREATE OR REPLACE FUNCTION public.hermes_prepare_execution_request(p_execution_request_id text, p_queue_item_id text, p_payload jsonb, p_project_id text, p_task_id text, p_expected_project_version bigint, p_expected_task_version bigint, p_command_id text, p_idempotency_key text, p_payload_hash text, p_actor_type text, p_actor_id text, p_reason text, p_fault_point text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog'
AS $function$
DECLARE
    command_row public.command_receipts%ROWTYPE;
    project_row public.projects%ROWTYPE;
    task_row public.tasks%ROWTYPE;
    decision_row public.decision_records%ROWTYPE;
    action_row public.candidate_actions%ROWTYPE;
    selected_row public.selected_action_refs%ROWTYPE;
    policy_row public.policy_decisions%ROWTYPE;
    current_policy_row public.current_policy_decisions%ROWTYPE;
    risk_row public.risk_assessments%ROWTYPE;
    current_risk_row public.current_risk_assessments%ROWTYPE;
    reservation_row public.resource_reservations%ROWTYPE;
    mapping_row public.decision_reservation_mappings%ROWTYPE;
    capability_row public.capability_match_records%ROWTYPE;
    availability_row public.worker_template_availability%ROWTYPE;
    context_row public.context_bundles%ROWTYPE;
    sandbox_row public.sandbox_profiles%ROWTYPE;
    plan_row public.verification_plans%ROWTYPE;
    prepared_event_id TEXT;
    queued_event_id TEXT;
    prepared_sequence BIGINT;
    queued_sequence BIGINT;
    binding_id TEXT;
    binding_hash TEXT;
    result_payload JSONB;
    artifact_item JSONB;
    artifact_row public.artifacts%ROWTYPE;
    lock_item JSONB;
    action_type TEXT := p_payload->>'action_type';
    lock_scope TEXT;
BEGIN
    IF p_actor_type <> 'execution_preparer' OR NULLIF(btrim(p_actor_id), '') IS NULL THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_INCOMPLETE';
    END IF;
    IF NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_INCOMPLETE';
    END IF;
    IF public.hermes_execution_has_secret_value(p_payload) THEN
        RAISE EXCEPTION 'SECRET_VALUE_FORBIDDEN';
    END IF;
    SELECT * INTO command_row FROM public.command_receipts
    WHERE command_id = p_command_id
      AND project_id = p_project_id
      AND command_type = 'execution.prepare_request'
      AND idempotency_key = p_idempotency_key
      AND request_hash = p_payload_hash
      AND status = 'PROCESSING'
    FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_INCOMPLETE';
    END IF;
    IF p_fault_point = 'after_receipt_placeholder' THEN
        RAISE EXCEPTION 'INJECTED_EXECUTION_CRASH_AFTER_RECEIPT';
    END IF;

    IF action_type NOT IN ('diagnose','run_deeper_test','deeper_test','repair','retry','implement') THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_ACTION_ROUTE_UNSUPPORTED';
    END IF;

    SELECT * INTO project_row FROM public.projects
    WHERE project_id = p_project_id FOR SHARE;
    IF NOT FOUND OR project_row.version <> p_expected_project_version THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_VERSION_CONFLICT';
    END IF;
    IF project_row.state IN ('PAUSED','BLOCKED','WAITING_FOR_HUMAN','WAITING_FOR_RESOURCE','FAILED','CANCELLED','ACCEPTED') THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_PROJECT_STATE_BLOCKED';
    END IF;
    SELECT * INTO task_row FROM public.tasks
    WHERE task_id = p_task_id AND project_id = p_project_id FOR SHARE;
    IF NOT FOUND OR task_row.version <> p_expected_task_version THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_VERSION_CONFLICT';
    END IF;
    IF task_row.state <> 'READY' THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_TASK_NOT_READY';
    END IF;
    IF p_fault_point = 'after_authority_validation' THEN
        RAISE EXCEPTION 'INJECTED_EXECUTION_CRASH_AFTER_VALIDATION';
    END IF;

    SELECT * INTO decision_row FROM public.decision_records
    WHERE decision_id = p_payload->'decision'->>'ref_id'
      AND project_id = p_project_id
      AND selection_version = (p_payload->'decision'->>'version')::BIGINT
    FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_VERSION_CONFLICT';
    END IF;
    SELECT * INTO action_row FROM public.candidate_actions
    WHERE action_id = p_payload->'action'->>'ref_id'
      AND project_id = p_project_id
      AND content_hash = p_payload->'action'->>'content_hash'
    FOR SHARE;
    IF NOT FOUND OR action_row.type <> action_type THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_ACTION_ROUTE_UNSUPPORTED';
    END IF;
    SELECT * INTO selected_row FROM public.selected_action_refs
    WHERE decision_id = decision_row.decision_id
      AND action_id = action_row.action_id
    FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_ACTION_ROUTE_UNSUPPORTED';
    END IF;

    SELECT * INTO policy_row FROM public.policy_decisions
    WHERE policy_decision_id = p_payload->'policy'->>'ref_id'
      AND project_id = p_project_id
      AND planning_run_id = decision_row.planning_run_id
      AND action_id = action_row.action_id
      AND action_content_hash = action_row.content_hash
    FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'EXEC_ADMISSION_POLICY_NOT_ALLOW'; END IF;
    SELECT * INTO current_policy_row FROM public.current_policy_decisions
    WHERE action_id = action_row.action_id FOR SHARE;
    IF NOT FOUND OR current_policy_row.policy_decision_id <> policy_row.policy_decision_id
       OR current_policy_row.action_content_hash <> action_row.content_hash THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_VERSION_CONFLICT';
    END IF;
    IF policy_row.result <> 'ALLOW' THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_POLICY_NOT_ALLOW';
    END IF;
    IF policy_row.constraints::text ~* 'requires-human|require_human|human_gate' THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_HUMAN_GATE_BLOCKED';
    END IF;

    SELECT * INTO risk_row FROM public.risk_assessments
    WHERE risk_assessment_id = p_payload->'risk'->>'ref_id'
      AND project_id = p_project_id
      AND planning_run_id = decision_row.planning_run_id
      AND action_id = action_row.action_id
      AND action_content_hash = action_row.content_hash
    FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'EXEC_ADMISSION_RISK_UNSATISFIED'; END IF;
    SELECT * INTO current_risk_row FROM public.current_risk_assessments
    WHERE action_id = action_row.action_id FOR SHARE;
    IF NOT FOUND OR current_risk_row.risk_assessment_id <> risk_row.risk_assessment_id
       OR current_risk_row.action_content_hash <> action_row.content_hash THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_VERSION_CONFLICT';
    END IF;
    IF NOT risk_row.required_mitigations <@ risk_row.available_mitigations THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_RISK_UNSATISFIED';
    END IF;

    SELECT * INTO reservation_row FROM public.resource_reservations
    WHERE reservation_id = p_payload->'resource_reservation'->>'ref_id'
      AND project_id = p_project_id FOR SHARE;
    IF NOT FOUND OR reservation_row.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_RESERVATION_INVALID';
    END IF;
    SELECT * INTO mapping_row FROM public.decision_reservation_mappings
    WHERE decision_id = decision_row.decision_id
      AND action_id = action_row.action_id
      AND reservation_id = reservation_row.reservation_id
    FOR SHARE;
    IF NOT FOUND OR mapping_row.account_version <> reservation_row.account_version
       OR mapping_row.account_id <> reservation_row.account_id THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_RESERVATION_INVALID';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.execution_reservation_bindings
        WHERE reservation_id = reservation_row.reservation_id
           OR (project_id = p_project_id AND decision_id = decision_row.decision_id
               AND action_id = action_row.action_id)
    ) THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_RESERVATION_ALREADY_BOUND';
    END IF;

    SELECT * INTO capability_row FROM public.capability_match_records
    WHERE match_id = p_payload->'capability_match'->>'ref_id'
      AND project_id = p_project_id
      AND task_id = p_task_id
      AND decision_id = decision_row.decision_id
      AND action_id = action_row.action_id
    FOR SHARE;
    IF NOT FOUND OR capability_row.status <> 'MATCHED'
       OR capability_row.requirements_hash <> p_payload->>'capability_requirements_hash'
       OR capability_row.template_id <> p_payload->'worker_template'->>'template_id'
       OR capability_row.template_revision <> (p_payload->'worker_template'->>'revision')::BIGINT
       OR capability_row.template_content_hash <> p_payload->'worker_template'->>'content_hash'
       OR capability_row.availability_version <> (p_payload->'worker_template'->>'availability_version')::BIGINT THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_WORKER_TEMPLATE_UNAVAILABLE';
    END IF;
    SELECT * INTO availability_row FROM public.worker_template_availability
    WHERE template_id = capability_row.template_id
      AND revision = capability_row.template_revision
      AND availability_version = capability_row.availability_version
    FOR SHARE;
    IF NOT FOUND OR availability_row.availability_status <> 'AVAILABLE'
       OR availability_row.admission_status <> 'ADMISSIBLE' THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_WORKER_TEMPLATE_UNAVAILABLE';
    END IF;

    SELECT * INTO context_row FROM public.context_bundles
    WHERE bundle_id = p_payload->'context_bundle'->>'bundle_id'
      AND manifest_hash = p_payload->'context_bundle'->>'manifest_hash'
      AND project_id = p_project_id
      AND task_id = p_task_id
      AND decision_id = decision_row.decision_id
      AND action_id = action_row.action_id
      AND template_id = capability_row.template_id
      AND template_revision = capability_row.template_revision
    FOR SHARE;
    IF NOT FOUND OR context_row.selector_schema_version <> 'context-selector/1.0'
       OR context_row.builder_version <> 'context-builder/1.0' THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_CONTEXT_FREEZE_FAILED';
    END IF;

    SELECT * INTO sandbox_row FROM public.sandbox_profiles
    WHERE profile_id = p_payload->'sandbox_profile'->>'profile_id'
      AND profile_hash = p_payload->'sandbox_profile'->>'profile_hash'
      AND project_id = p_project_id
      AND task_id = p_task_id
      AND action_id = action_row.action_id
      AND template_id = capability_row.template_id
      AND template_revision = capability_row.template_revision
      AND context_bundle_hash = context_row.manifest_hash
    FOR SHARE;
    IF NOT FOUND OR sandbox_row.compiler_version <> p_payload->'sandbox_profile'->>'compiler_version'
       OR sandbox_row.target <> p_payload->'sandbox_profile'->>'target'
       OR sandbox_row.target <> 'contract-only/1.0' THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_SANDBOX_COMPILE_FAILED';
    END IF;
    -- 0032 live callsite convergence: delegate sandbox profile inspection to the
    -- canonical 0031 structured JSONB secret policy. This is not a new policy.
    IF public.hermes_execution_has_secret_value(sandbox_row.profile) THEN
        RAISE EXCEPTION 'SECRET_VALUE_FORBIDDEN';
    END IF;

    SELECT * INTO plan_row FROM public.verification_plans
    WHERE verification_plan_id = p_payload->'verification_plan'->>'ref_id'
      AND task_id = p_task_id
      AND project_id = p_project_id
      AND version = (p_payload->'verification_plan'->>'version')::BIGINT
      AND status = 'ACTIVE'
    FOR SHARE;
    IF NOT FOUND OR task_row.current_verification_plan_id IS DISTINCT FROM plan_row.verification_plan_id
       OR task_row.current_verification_plan_version IS DISTINCT FROM plan_row.version THEN
        RAISE EXCEPTION 'EXEC_ADMISSION_VERIFICATION_PLAN_MISSING';
    END IF;

    FOR artifact_item IN SELECT * FROM jsonb_array_elements(COALESCE(p_payload->'input_artifacts','[]'::jsonb)) LOOP
        SELECT * INTO artifact_row FROM public.artifacts
        WHERE artifact_id = artifact_item->>'artifact_id'
          AND task_id = artifact_item->>'task_id'
          AND content_hash = artifact_item->>'content_hash'
        FOR SHARE;
        IF NOT FOUND OR artifact_row.task_id <> p_task_id THEN
            RAISE EXCEPTION 'EXEC_ADMISSION_ARTIFACT_MISMATCH';
        END IF;
    END LOOP;

    FOR lock_item IN SELECT * FROM jsonb_array_elements(COALESCE(p_payload->'lock_intents','[]'::jsonb)) LOOP
        lock_scope := lock_item->>'scope';
        IF lock_scope IS NULL OR position(':' in lock_scope) < 2
           OR split_part(lock_scope, ':', 1) NOT IN (
               'repository','workspace','branch_ref','artifact_namespace',
               'external_environment','deployment_target'
           )
           OR lock_scope LIKE '%*%' THEN
            RAISE EXCEPTION 'EXEC_ADMISSION_LOCK_CONFLICT';
        END IF;
    END LOOP;

    binding_id := 'exec-bind-' || encode(public.digest(convert_to(
        p_execution_request_id || '|' || reservation_row.reservation_id, 'UTF8'
    ), 'sha256'), 'hex');
    binding_hash := 'sha256:' || encode(public.digest(convert_to(
        binding_id || '|' || p_payload_hash, 'UTF8'
    ), 'sha256'), 'hex');
    prepared_event_id := 'evt-' || gen_random_uuid()::text;
    queued_event_id := 'evt-' || gen_random_uuid()::text;

    INSERT INTO public.execution_requests(
        execution_request_id, project_id, task_id, decision_id, decision_version,
        decision_hash, action_id, action_version, action_type, action_content_hash,
        action_requirements_hash, policy_decision_id, policy_version, policy_hash,
        risk_assessment_id, risk_version, risk_hash, mandatory_mitigations_hash,
        reservation_id, reservation_version, reservation_hash, capability_match_id,
        capability_match_version, capability_requirements_hash, worker_template_id,
        worker_template_revision, worker_template_content_hash,
        worker_template_availability_version, context_bundle_id, context_manifest_hash,
        sandbox_profile_id, sandbox_profile_hash, sandbox_compiler_version,
        sandbox_compiler_target, verification_plan_id, verification_plan_version,
        verification_plan_hash, input_artifacts, lock_intents, lock_scope_hash,
        priority, attempt_baseline, request_state, request_version, actor_type,
        actor_id, reason, idempotency_key, payload_hash, snapshot,
        prepared_event_id, queued_event_id, command_id
    ) VALUES (
        p_execution_request_id, p_project_id, p_task_id, decision_row.decision_id,
        decision_row.selection_version, p_payload->'decision'->>'content_hash',
        action_row.action_id, (p_payload->'action'->>'version')::BIGINT,
        action_type, action_row.content_hash, p_payload->>'action_requirements_hash',
        policy_row.policy_decision_id, (p_payload->'policy'->>'version')::BIGINT,
        p_payload->'policy'->>'content_hash', risk_row.risk_assessment_id,
        (p_payload->'risk'->>'version')::BIGINT, p_payload->'risk'->>'content_hash',
        p_payload->>'mandatory_mitigations_hash', reservation_row.reservation_id,
        (p_payload->'resource_reservation'->>'version')::BIGINT,
        p_payload->'resource_reservation'->>'content_hash', capability_row.match_id,
        (p_payload->'capability_match'->>'version')::BIGINT,
        p_payload->>'capability_requirements_hash', capability_row.template_id,
        capability_row.template_revision, capability_row.template_content_hash,
        capability_row.availability_version, context_row.bundle_id,
        context_row.manifest_hash, sandbox_row.profile_id, sandbox_row.profile_hash,
        sandbox_row.compiler_version, sandbox_row.target, plan_row.verification_plan_id,
        plan_row.version, p_payload->'verification_plan'->>'content_hash',
        COALESCE(p_payload->'input_artifacts','[]'::jsonb),
        COALESCE(p_payload->'lock_intents','[]'::jsonb),
        p_payload->>'lock_scope_hash', (p_payload->>'priority')::INTEGER,
        0, 'QUEUED', 1, p_actor_type, p_actor_id, p_reason,
        p_idempotency_key, p_payload_hash, p_payload, prepared_event_id,
        queued_event_id, p_command_id
    );
    INSERT INTO public.execution_reservation_bindings(
        binding_id, execution_request_id, reservation_id, project_id, decision_id,
        action_id, reservation_version, binding_hash, command_id
    ) VALUES (
        binding_id, p_execution_request_id, reservation_row.reservation_id,
        p_project_id, decision_row.decision_id, action_row.action_id,
        reservation_row.account_version, binding_hash, p_command_id
    );
    IF p_fault_point = 'after_reservation_binding' THEN
        RAISE EXCEPTION 'INJECTED_EXECUTION_CRASH_AFTER_BINDING';
    END IF;
    IF p_fault_point = 'after_request_write' THEN
        RAISE EXCEPTION 'INJECTED_EXECUTION_CRASH_AFTER_REQUEST';
    END IF;

    INSERT INTO public.execution_queue_items(
        queue_item_id, execution_request_id, project_id, task_id, priority,
        available_at, enqueued_at, stable_order_key, request_version, payload_hash,
        queue_state, event_id, command_id
    ) VALUES (
        p_queue_item_id, p_execution_request_id, p_project_id, p_task_id,
        (p_payload->>'priority')::INTEGER, now(), now(),
        lpad((1000 - (p_payload->>'priority')::INTEGER)::TEXT, 8, '0') || ':' ||
        p_execution_request_id, 1, p_payload_hash, 'PENDING',
        queued_event_id, p_command_id
    );
    IF p_fault_point = 'after_queue_item' THEN
        RAISE EXCEPTION 'INJECTED_EXECUTION_CRASH_AFTER_QUEUE';
    END IF;

    INSERT INTO public.event_log(
        event_id, event_type, schema_version, producer_type, producer_id,
        project_id, partition_key, command_id, correlation_id, causation_id,
        task_id, payload
    ) VALUES (
        prepared_event_id, 'execution.request_prepared', '1.0',
        p_actor_type, p_actor_id, p_project_id, p_project_id, p_command_id,
        p_command_id, p_command_id, p_task_id,
        jsonb_build_object(
            'execution_request_id', p_execution_request_id,
            'project_id', p_project_id,
            'task_id', p_task_id,
            'decision_id', decision_row.decision_id,
            'action_id', action_row.action_id,
            'reservation_id', reservation_row.reservation_id,
            'payload_hash', p_payload_hash,
            'request_version', 1
        )
    ) RETURNING sequence INTO prepared_sequence;
    INSERT INTO public.event_log(
        event_id, event_type, schema_version, producer_type, producer_id,
        project_id, partition_key, command_id, correlation_id, causation_id,
        task_id, payload
    ) VALUES (
        queued_event_id, 'execution.queued', '1.0',
        p_actor_type, p_actor_id, p_project_id, p_project_id, p_command_id,
        p_command_id, prepared_event_id, p_task_id,
        jsonb_build_object(
            'execution_request_id', p_execution_request_id,
            'queue_item_id', p_queue_item_id,
            'project_id', p_project_id,
            'task_id', p_task_id,
            'decision_id', decision_row.decision_id,
            'action_id', action_row.action_id,
            'reservation_id', reservation_row.reservation_id,
            'payload_hash', p_payload_hash,
            'request_version', 1,
            'queue_state', 'PENDING'
        )
    ) RETURNING sequence INTO queued_sequence;
    IF p_fault_point = 'after_event_before_outbox' THEN
        RAISE EXCEPTION 'INJECTED_EXECUTION_CRASH_AFTER_EVENT';
    END IF;
    INSERT INTO public.outbox_messages(message_id, event_id, topic, partition_key, sequence, payload)
    SELECT 'msg-' || gen_random_uuid()::text, event_id, 'hermes.runtime.events',
           p_project_id, sequence, payload
    FROM public.event_log
    WHERE event_id IN (prepared_event_id, queued_event_id);
    IF p_fault_point = 'after_outbox_before_receipt' THEN
        RAISE EXCEPTION 'INJECTED_EXECUTION_CRASH_AFTER_OUTBOX';
    END IF;
    result_payload := jsonb_build_object(
        'execution_request_id', p_execution_request_id,
        'queue_item_id', p_queue_item_id,
        'request_state', 'QUEUED',
        'request_version', 1,
        'payload_hash', p_payload_hash,
        'reservation_id', reservation_row.reservation_id,
        'binding_id', binding_id,
        'prepared_event_id', prepared_event_id,
        'queued_event_id', queued_event_id,
        'event_ids', jsonb_build_array(prepared_event_id, queued_event_id),
        'deduplicated', false
    );
    UPDATE public.command_receipts
    SET status='APPLIED',
        result=jsonb_build_object(
            'command_id', p_command_id,
            'status', 'APPLIED',
            'result_code', 'EXECUTION_REQUEST_QUEUED',
            'target_version', 1,
            'event_ids', jsonb_build_array(prepared_event_id, queued_event_id),
            'response', result_payload
        ),
        completed_at=now()
    WHERE command_id=p_command_id AND status='PROCESSING';
    IF p_fault_point = 'after_receipt_before_commit' THEN
        RAISE EXCEPTION 'INJECTED_EXECUTION_CRASH_AFTER_RECEIPT_COMPLETE';
    END IF;
    RETURN result_payload;
END;
$function$


