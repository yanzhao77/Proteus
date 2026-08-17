-- P6 (ADR-0073): autonomous production trial runtime closure.
--
-- 1. candidate_actions.type CHECK extended with the worker-executable
--    'implement' action (registry 1.1).
-- 2. hermes_prepare_execution_request whitelist extended with 'implement' so
--    implementation executions can be admitted to the queue.
-- 3. action_registry_versions row for 'action-registry/1.1' (superset of 1.0).
-- 4. policy_rules row for policy.system.implement.safe_code.allow.v1
--    (mirrors the bounded code repair rule).
-- 5. hermes_emit_execution_feedback now performs task re-entry: a task whose
--    execution failed is returned to the ready pool so the planner's repair
--    candidate can be prepared/executed. Previously P2-5 tests seeded this
--    transition via raw SQL; the real recovery authority now owns it.

DO $$
BEGIN
    ALTER TABLE public.candidate_actions
        DROP CONSTRAINT IF EXISTS candidate_actions_type_check;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'candidate_actions_type_check'
          AND conrelid = 'public.candidate_actions'::regclass
    ) THEN
        ALTER TABLE public.candidate_actions ADD CONSTRAINT candidate_actions_type_check
            CHECK (type IN (
                'retry','diagnose','repair','switch_strategy','switch_agent',
                'expert_review','run_deeper_test','replan','rollback',
                'schedule_ready_task','request_resource','pause','human_gate',
                'implement'
            ));
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_prepare_execution_request(
    p_execution_request_id TEXT,
    p_queue_item_id TEXT,
    p_payload JSONB,
    p_project_id TEXT,
    p_task_id TEXT,
    p_expected_project_version BIGINT,
    p_expected_task_version BIGINT,
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
    IF sandbox_row.profile::text ~* 'secret[_-]?value|password=|private key|sk-[A-Za-z0-9]{12,}' THEN
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
$$;

INSERT INTO public.action_registry_versions(
    registry_version, planner_rule_version, resource_estimator_version,
    enabled_action_types, disabled_action_types, content_hash
) VALUES (
    'action-registry/1.1', 'planner-rules/1.0', 'resource-estimator/1.0',
    ARRAY['diagnose','run_deeper_test','repair','retry','switch_strategy',
          'schedule_ready_task','request_resource','pause','implement'],
    ARRAY['switch_agent','expert_review','replan','rollback','human_gate'],
    'sha256:' || encode(public.digest(convert_to(
        'action-registry/1.1|planner-rules/1.0|resource-estimator/1.0',
        'UTF8'), 'sha256'), 'hex')
) ON CONFLICT (registry_version) DO NOTHING;

INSERT INTO public.policy_rules(
    rule_id, policy_bundle_version, scope_type, scope_id, priority, effect,
    action_types, environment_classes, constraints, reason_codes, content_hash
) VALUES (
    'policy.system.implement.safe_code.allow.v1','policy-bundle/1.0','system','*',
    100,'ALLOW', ARRAY['implement'],ARRAY['dev','test'],
    '{"network_access":"disabled","filesystem_write":"workspace_only","production_access":"denied","secret_access":"denied","max_risk_level":"HIGH","required_mitigations":["verification_before_apply"]}'::jsonb,
    ARRAY['bounded_implementation_allowed'],
    'sha256:' || encode(public.digest(convert_to(
        'policy.system.implement.safe_code.allow.v1','UTF8'),'sha256'),'hex')
) ON CONFLICT DO NOTHING;

-- The modified hermes_emit_execution_feedback (SECURITY DEFINER, owner
-- hermes_recovery_owner) performs task re-entry, so the recovery authority
-- needs UPDATE on public.tasks (the worker authority already has it).
GRANT UPDATE ON public.tasks TO hermes_recovery_owner;
GRANT UPDATE ON public.tasks TO hermes_recovery_runtime;

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

    -- P6 (ADR-0073): task re-entry. The recovery controller returns the
    -- failed task to the ready pool inside the same authority transaction, so
    -- the planner's worker-executable repair candidate can be prepared and
    -- executed. P2-5 performed this re-entry via raw SQL seeding; this closes
    -- that gap in the real recovery command.
    UPDATE public.tasks
    SET state = 'READY', version = version + 1, updated_at = now(),
        current_artifact_id = NULL, current_artifact_hash = NULL,
        completion_worker_identity = NULL, completion_worker_run_id = NULL,
        completion_worker_context_identity = NULL
    WHERE task_id = result_row.task_id AND project_id = p_project_id
      AND state IN ('RUNNING','FAILED','COMPLETION_CLAIMED','VERIFYING',
                    'BLOCKED','RETRYING','WAITING');
    IF p_fault_point = 'after_task_reentry' THEN
        RAISE EXCEPTION 'INJECTED_RECOVERY_CRASH_AFTER_TASK_REENTRY';
    END IF;
    PERFORM public.hermes_recovery_append_event(
        p_project_id, result_row.task_id, p_command_id, 'task.recovery_reentered',
        p_actor_type, p_actor_id, p_command_id, cycle_event_id,
        jsonb_build_object('task_id', result_row.task_id),
        p_fault_point
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


-- P6 (ADR-0073): SituationAnalyzer accepts work_graph.patch.applied as a
-- work_available trigger (the patch records authoritative readiness changes).
CREATE OR REPLACE FUNCTION public.hermes_apply_situation_effect(
    p_consumer_id TEXT,
    p_event_id TEXT,
    p_partition_key TEXT,
    p_sequence BIGINT,
    p_schema_version TEXT,
    p_raw_envelope JSONB,
    p_trigger_hash TEXT,
    p_is_trigger BOOLEAN,
    p_situation_type TEXT,
    p_task_id TEXT,
    p_failure_type TEXT,
    p_severity TEXT,
    p_confidence_basis_points INTEGER,
    p_affected_artifact_refs TEXT[],
    p_affected_components TEXT[],
    p_context_refs TEXT[],
    p_constraints TEXT[],
    p_fingerprint TEXT,
    p_rule_set_version TEXT,
    p_canonicalization_version TEXT,
    p_project_version_ref TEXT,
    p_task_version_ref TEXT,
    p_verification_refs TEXT[],
    p_budget_account_version_refs TEXT[],
    p_policy_decision_refs TEXT[],
    p_work_graph_version_ref TEXT,
    p_expected_situation_version BIGINT DEFAULT NULL,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    source_event public.event_log%ROWTYPE;
    checkpoint BIGINT;
    context_id TEXT;
    context_digest TEXT;
    prior_refs TEXT[] := '{}';
    active_row public.situations%ROWTYPE;
    old_row public.situations%ROWTYPE;
    resolved_row public.situations%ROWTYPE;
    new_id TEXT;
    output_event_id TEXT;
    output_sequence BIGINT;
    output_type TEXT;
    output_payload JSONB;
    processing JSONB;
    next_version BIGINT;
BEGIN
    IF NULLIF(btrim(p_consumer_id), '') IS NULL THEN
        RAISE EXCEPTION 'SITUATION_AUTHORITY_REQUIRED';
    END IF;
    SELECT * INTO source_event FROM public.event_log
    WHERE event_id = p_event_id AND partition_key = p_partition_key
      AND sequence = p_sequence AND schema_version = p_schema_version;
    IF NOT FOUND THEN RAISE EXCEPTION 'EVENT_ENVELOPE_IDENTITY_MISMATCH'; END IF;
    IF p_raw_envelope->>'event_type' IS DISTINCT FROM source_event.event_type
       OR p_raw_envelope->>'project_id' IS DISTINCT FROM source_event.project_id
       OR p_raw_envelope->>'partition_key' IS DISTINCT FROM source_event.partition_key
       OR p_raw_envelope->'payload' IS DISTINCT FROM source_event.payload
       OR NULLIF(p_raw_envelope->>'task_id', '') IS DISTINCT FROM source_event.task_id THEN
        RAISE EXCEPTION 'EVENT_ENVELOPE_IDENTITY_MISMATCH';
    END IF;

    INSERT INTO public.consumer_checkpoints(consumer_id, partition_key, last_sequence)
    VALUES (p_consumer_id, p_partition_key, 0) ON CONFLICT DO NOTHING;
    SELECT last_sequence INTO checkpoint FROM public.consumer_checkpoints
    WHERE consumer_id = p_consumer_id AND partition_key = p_partition_key FOR UPDATE;

    SELECT processing_result INTO processing FROM public.consumer_inbox
    WHERE consumer_id = p_consumer_id AND event_id = p_event_id;
    IF FOUND THEN RETURN processing; END IF;
    IF p_sequence <> checkpoint + 1 THEN
        RAISE EXCEPTION 'CONSUMER_SEQUENCE_NOT_CONTIGUOUS';
    END IF;

    IF NOT p_is_trigger THEN
        processing := jsonb_build_object(
            'classification', 'IGNORED_NOT_A_TRIGGER', 'event_id', p_event_id
        );
    ELSE
        IF source_event.project_id IS DISTINCT FROM p_raw_envelope->>'project_id' THEN
            RAISE EXCEPTION 'SITUATION_FACT_PROJECT_MISMATCH';
        END IF;
        IF source_event.task_id IS NOT NULL
           AND source_event.task_id IS DISTINCT FROM p_task_id THEN
            RAISE EXCEPTION 'SITUATION_FACT_TASK_MISMATCH';
        END IF;
        IF split_part(p_schema_version, '.', 1) <> '1' THEN
            RAISE EXCEPTION 'SITUATION_TRIGGER_SCHEMA_INVALID';
        END IF;
        IF p_task_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.tasks t
            WHERE t.task_id = p_task_id AND t.project_id = source_event.project_id
        ) THEN
            RAISE EXCEPTION 'SITUATION_FACT_TASK_MISMATCH';
        END IF;

        -- Validate the immutable Trigger payload against its authority record.
        IF source_event.event_type = 'verification.recorded' THEN
            IF NOT EXISTS (
                SELECT 1 FROM public.verification_results v
                JOIN public.command_receipts c ON c.command_id = source_event.command_id
                WHERE v.verification_id = source_event.payload->>'verification_id'
                  AND v.authority_status = 'AUTHORITATIVE'
                  AND v.project_id = source_event.project_id
                  AND v.task_id = p_task_id
                  AND v.artifact_id = source_event.payload->>'artifact_id'
                  AND v.artifact_hash = source_event.payload->>'artifact_hash'
                  AND v.verdict = 'FAIL'
                  AND c.command_type = 'verification.record'
            ) THEN RAISE EXCEPTION 'SITUATION_CONTEXT_UNAVAILABLE'; END IF;
            IF EXISTS (
                SELECT 1 FROM unnest(COALESCE(p_context_refs, '{}')) ref
                WHERE ref <> source_event.payload->>'verification_id'
                  AND NOT EXISTS (
                      SELECT 1 FROM public.verification_evidence ve
                      WHERE ve.verification_id = source_event.payload->>'verification_id'
                        AND ve.evidence_id = ref
                  )
            ) THEN RAISE EXCEPTION 'SITUATION_CONTEXT_FUTURE_FACT'; END IF;
        ELSIF source_event.event_type = 'task.readiness_recomputed' THEN
            IF NOT EXISTS (
                SELECT 1 FROM public.command_receipts c
                WHERE c.command_id = source_event.command_id
                  AND c.project_id = source_event.project_id
                  AND c.command_type = 'task.recompute_readiness'
            ) THEN RAISE EXCEPTION 'SITUATION_CONTEXT_UNAVAILABLE'; END IF;
        ELSIF source_event.event_type IN ('budget.reserved','budget.settled','budget.released') THEN
            IF NOT EXISTS (
                SELECT 1 FROM public.resource_accounts a
                JOIN public.command_receipts c ON c.command_id = source_event.command_id
                WHERE a.account_id = source_event.payload->>'account_id'
                  AND a.project_id = source_event.project_id
                  AND a.version >= (source_event.payload->>'entity_version')::bigint
                  AND c.command_type IN ('resource.reserve','resource.settle','resource.release')
            ) THEN RAISE EXCEPTION 'SITUATION_CONTEXT_UNAVAILABLE'; END IF;
        ELSIF source_event.event_type = 'feedback.created' THEN
            IF NOT EXISTS (
                SELECT 1 FROM public.feedback_records f
                WHERE f.source_event_id = source_event.event_id
                  AND f.project_id = source_event.project_id
                  AND f.source_task_id = p_task_id
            ) THEN RAISE EXCEPTION 'SITUATION_CONTEXT_UNAVAILABLE'; END IF;
        ELSIF source_event.event_type = 'work_graph.patch.applied' THEN
            -- P6 (ADR-0073): the work graph patch is the authoritative record
            -- of readiness changes for fresh tasks (a dependency-free task
            -- becomes READY at patch time and no task.readiness_recomputed
            -- event follows). Validate the producing command.
            IF NOT EXISTS (
                SELECT 1 FROM public.command_receipts c
                WHERE c.command_id = source_event.command_id
                  AND c.project_id = source_event.project_id
                  AND c.command_type = 'work_graph.apply_patch'
            ) THEN RAISE EXCEPTION 'SITUATION_CONTEXT_UNAVAILABLE'; END IF;
        ELSE
            RAISE EXCEPTION 'SITUATION_CLASSIFICATION_UNSUPPORTED';
        END IF;

        PERFORM pg_advisory_xact_lock(hashtextextended(
            source_event.project_id || ':' || COALESCE(p_task_id, '') || ':' || p_situation_type,
            0
        ));
        SELECT COALESCE(array_agg(situation_id ORDER BY situation_id), '{}') INTO prior_refs
        FROM public.situations
        WHERE project_id = source_event.project_id
          AND task_id IS NOT DISTINCT FROM p_task_id
          AND type = p_situation_type;

        context_id := 'ctx-' || gen_random_uuid()::text;
        context_digest := 'sha256:' || encode(public.digest(convert_to(
            jsonb_build_object(
                'project_id', source_event.project_id,
                'partition_key', p_partition_key,
                'observed_at_sequence', p_sequence,
                'trigger_event_type', source_event.event_type,
                'trigger_event_schema_version', source_event.schema_version,
                'situation_type', p_situation_type,
                'failure_type', p_failure_type,
                'severity', p_severity,
                'confidence_basis_points', p_confidence_basis_points,
                'affected_components', COALESCE(p_affected_components, '{}'),
                'constraints', COALESCE(p_constraints, '{}'),
                'project_version_ref', p_project_version_ref,
                'task_id', p_task_id,
                'task_version_ref', p_task_version_ref,
                'artifact_refs', COALESCE(p_affected_artifact_refs, '{}'),
                'evidence_refs', COALESCE(p_context_refs, '{}'),
                'verification_refs', COALESCE(p_verification_refs, '{}'),
                'budget_account_version_refs', COALESCE(p_budget_account_version_refs, '{}'),
                'policy_decision_refs', COALESCE(p_policy_decision_refs, '{}'),
                'work_graph_version_ref', p_work_graph_version_ref,
                'rule_set_version', p_rule_set_version
            )::text, 'UTF8'), 'sha256'), 'hex');
        INSERT INTO public.analysis_contexts(
            analysis_context_id, project_id, trigger_event_id, partition_key,
            observed_at_sequence, trigger_event_type, trigger_event_schema_version,
            trigger_event_hash, project_version_ref, task_id, task_version_ref,
            artifact_refs, evidence_refs, verification_refs,
            budget_account_version_refs, policy_decision_refs,
            previous_situation_refs, work_graph_version_ref, rule_set_version,
            context_hash
        ) VALUES (
            context_id, source_event.project_id, p_event_id, p_partition_key,
            p_sequence, source_event.event_type, p_schema_version, p_trigger_hash,
            p_project_version_ref, p_task_id, p_task_version_ref,
            COALESCE(p_affected_artifact_refs, '{}'), COALESCE(p_context_refs, '{}'),
            COALESCE(p_verification_refs, '{}'),
            COALESCE(p_budget_account_version_refs, '{}'),
            COALESCE(p_policy_decision_refs, '{}'), prior_refs,
            p_work_graph_version_ref, p_rule_set_version, context_digest
        );
        IF p_fault_point = 'after_context_before_situation' THEN
            RAISE EXCEPTION 'INJECTED_SITUATION_CRASH_AFTER_CONTEXT';
        END IF;

        SELECT * INTO resolved_row FROM public.situations
        WHERE project_id = source_event.project_id AND fingerprint = p_fingerprint
          AND status = 'RESOLVED' ORDER BY updated_at DESC LIMIT 1;
        IF FOUND THEN
            processing := jsonb_build_object(
                'classification', 'IGNORED_ALREADY_RESOLVED',
                'event_id', p_event_id, 'situation_id', resolved_row.situation_id,
                'analysis_context_id', context_id, 'version', resolved_row.version
            );
        ELSE
            SELECT * INTO active_row FROM public.situations
            WHERE project_id = source_event.project_id AND fingerprint = p_fingerprint
              AND status = 'OPEN' FOR UPDATE;
            IF FOUND THEN
                IF p_expected_situation_version IS NOT NULL
                   AND active_row.version <> p_expected_situation_version THEN
                    RAISE EXCEPTION 'SITUATION_VERSION_CONFLICT';
                END IF;
                next_version := active_row.version + 1;
                UPDATE public.situations SET
                    trigger_event_id = p_event_id,
                    analysis_context_id = context_id,
                    severity = CASE
                        WHEN array_position(ARRAY['LOW','MEDIUM','HIGH','CRITICAL'], p_severity)
                           > array_position(ARRAY['LOW','MEDIUM','HIGH','CRITICAL'], severity)
                        THEN p_severity ELSE severity END,
                    affected_artifact_refs = ARRAY(
                        SELECT DISTINCT x FROM unnest(
                            affected_artifact_refs || COALESCE(p_affected_artifact_refs, '{}')
                        ) x ORDER BY x
                    ),
                    affected_components = ARRAY(
                        SELECT DISTINCT x FROM unnest(
                            affected_components || COALESCE(p_affected_components, '{}')
                        ) x ORDER BY x
                    ),
                    available_context_refs = ARRAY(
                        SELECT DISTINCT x FROM unnest(
                            available_context_refs || COALESCE(p_context_refs, '{}')
                        ) x ORDER BY x
                    ),
                    constraints = ARRAY(
                        SELECT DISTINCT x FROM unnest(
                            constraints || COALESCE(p_constraints, '{}')
                        ) x ORDER BY x
                    ),
                    confidence_basis_points = greatest(confidence_basis_points, p_confidence_basis_points),
                    observed_at_sequence = greatest(observed_at_sequence, p_sequence),
                    version = next_version, updated_at = now()
                WHERE situation_id = active_row.situation_id;
                INSERT INTO public.situation_versions
                SELECT situation_id, version, status, trigger_event_id,
                       analysis_context_id, failure_type, severity,
                       affected_artifact_refs, affected_components,
                       available_context_refs, constraints, history_summary,
                       confidence_basis_points, fingerprint, observed_at_sequence,
                       superseded_by, 'UPDATED', now()
                FROM public.situations WHERE situation_id = active_row.situation_id;
                new_id := active_row.situation_id;
                output_type := 'situation.updated';
            ELSE
                SELECT * INTO old_row FROM public.situations
                WHERE project_id = source_event.project_id
                  AND task_id IS NOT DISTINCT FROM p_task_id
                  AND type = p_situation_type AND status = 'OPEN'
                ORDER BY updated_at DESC LIMIT 1 FOR UPDATE;
                new_id := 'sit-' || gen_random_uuid()::text;
                IF FOUND THEN
                    UPDATE public.situations
                    SET status = 'SUPERSEDED', superseded_by = new_id,
                        version = version + 1, updated_at = now()
                    WHERE situation_id = old_row.situation_id;
                    INSERT INTO public.situation_versions
                    SELECT situation_id, version, status, trigger_event_id,
                           analysis_context_id, failure_type, severity,
                           affected_artifact_refs, affected_components,
                           available_context_refs, constraints, history_summary,
                           confidence_basis_points, fingerprint, observed_at_sequence,
                           superseded_by, 'SUPERSEDED', now()
                    FROM public.situations WHERE situation_id = old_row.situation_id;
                    IF p_fault_point = 'after_old_superseded_before_new' THEN
                        RAISE EXCEPTION 'INJECTED_SITUATION_CRASH_AFTER_SUPERSEDE';
                    END IF;
                END IF;
                INSERT INTO public.situations(
                    situation_id, project_id, task_id, type, status,
                    trigger_event_id, analysis_context_id, failure_type, severity,
                    affected_artifact_refs, affected_components,
                    available_context_refs, constraints, history_summary,
                    confidence_basis_points, fingerprint, observed_at_sequence,
                    rule_set_version, canonicalization_version, version
                ) VALUES (
                    new_id, source_event.project_id, p_task_id, p_situation_type, 'OPEN',
                    p_event_id, context_id, p_failure_type, p_severity,
                    COALESCE(p_affected_artifact_refs, '{}'),
                    COALESCE(p_affected_components, '{}'),
                    COALESCE(p_context_refs, '{}'), COALESCE(p_constraints, '{}'),
                    jsonb_build_object('attempts', 0, 'strategies_tried', '[]'::jsonb,
                                       'previous_situation_refs', prior_refs),
                    p_confidence_basis_points, p_fingerprint, p_sequence,
                    p_rule_set_version, p_canonicalization_version, 1
                );
                INSERT INTO public.situation_versions
                SELECT situation_id, version, status, trigger_event_id,
                       analysis_context_id, failure_type, severity,
                       affected_artifact_refs, affected_components,
                       available_context_refs, constraints, history_summary,
                       confidence_basis_points, fingerprint, observed_at_sequence,
                       superseded_by, 'CREATED', now()
                FROM public.situations WHERE situation_id = new_id;
                output_type := CASE WHEN old_row.situation_id IS NULL
                                    THEN 'situation.detected'
                                    ELSE 'situation.superseded' END;
            END IF;
            IF p_fault_point = 'after_situation_before_event' THEN
                RAISE EXCEPTION 'INJECTED_SITUATION_CRASH_AFTER_SITUATION';
            END IF;

            output_event_id := 'evt-' || gen_random_uuid()::text;
            output_payload := jsonb_build_object(
                'situation_id', new_id,
                'analysis_context_id', context_id,
                'fingerprint', p_fingerprint,
                'situation_type', p_situation_type,
                'source_event_id', p_event_id,
                'superseded_situation_id', old_row.situation_id
            );
            INSERT INTO public.event_log(
                event_id, event_type, schema_version, producer_type, producer_id,
                project_id, partition_key, command_id, correlation_id,
                causation_id, trace_id, task_id, payload
            ) VALUES (
                output_event_id, output_type, '1.0', 'situation_analyzer',
                p_consumer_id, source_event.project_id, source_event.partition_key,
                source_event.command_id, source_event.correlation_id,
                source_event.event_id, source_event.trace_id, p_task_id, output_payload
            ) RETURNING sequence INTO output_sequence;
            IF p_fault_point = 'after_event_before_outbox' THEN
                RAISE EXCEPTION 'INJECTED_SITUATION_CRASH_AFTER_EVENT';
            END IF;
            INSERT INTO public.outbox_messages(
                message_id, event_id, topic, partition_key, sequence, payload
            ) VALUES (
                'msg-' || gen_random_uuid()::text, output_event_id,
                'hermes.runtime.events', source_event.partition_key,
                output_sequence, output_payload
            );
            IF p_fault_point = 'after_outbox_before_inbox' THEN
                RAISE EXCEPTION 'INJECTED_SITUATION_CRASH_AFTER_OUTBOX';
            END IF;
            SELECT version INTO next_version FROM public.situations WHERE situation_id = new_id;
            processing := jsonb_build_object(
                'classification', CASE WHEN output_type = 'situation.detected' THEN 'CREATED'
                                       WHEN output_type = 'situation.updated' THEN 'UPDATED'
                                       ELSE 'SUPERSEDED' END,
                'event_id', p_event_id, 'situation_id', new_id,
                'analysis_context_id', context_id, 'version', next_version,
                'output_event_id', output_event_id
            );
        END IF;
    END IF;

    INSERT INTO public.consumer_effects(consumer_id, event_id, effect_count)
    VALUES (p_consumer_id, p_event_id, 1);
    INSERT INTO public.consumer_inbox(
        consumer_id, event_id, partition_key, sequence, schema_version,
        processing_result, raw_envelope
    ) VALUES (
        p_consumer_id, p_event_id, p_partition_key, p_sequence,
        p_schema_version, processing, p_raw_envelope
    );
    IF p_fault_point = 'after_inbox_before_checkpoint' THEN
        RAISE EXCEPTION 'INJECTED_SITUATION_CRASH_AFTER_INBOX';
    END IF;
    UPDATE public.consumer_checkpoints SET last_sequence = p_sequence, updated_at = now()
    WHERE consumer_id = p_consumer_id AND partition_key = p_partition_key
      AND last_sequence = checkpoint;
    UPDATE public.consumer_pending_gaps SET status = 'PROCESSED', last_seen_at = now()
    WHERE consumer_id = p_consumer_id AND event_id = p_event_id;
    RETURN processing;
END;
$$;

-- P6 (ADR-0073): tighten the API-key pattern in the execution secret guard.
-- The bare "sk-[A-Za-z0-9]{12,}" pattern false-positived on deterministic
-- authority ids such as "risk-<hex>" (any id ending in "sk-"), which blocked
-- legitimate executions whose admission snapshot carries a risk_assessment_id.
-- Requiring sk- to not be preceded by an alphanumeric keeps real API keys
-- detected while accepting authority ids.
CREATE OR REPLACE FUNCTION public.hermes_execution_has_secret_value(p_payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
    SELECT p_payload::text ~* '("(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value)"[[:space:]]*:|private key|(^|[^a-z0-9])sk-[a-z0-9]{12,}|password=)'
$$;

CREATE OR REPLACE FUNCTION public.hermes_recovery_secret_guard(p_payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
    SELECT p_payload::text ~* '("(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value)"[[:space:]]*:|private key|(^|[^a-z0-9])sk-[a-z0-9]{12,}|password=)'
$$;

CREATE OR REPLACE FUNCTION public.hermes_scheduler_secret_guard(p_payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
    SELECT p_payload::text ~* '("(api[_-]?token|password|credential|private[_-]?key)"[[:space:]]*:|private key|(^|[^a-z0-9])sk-[a-z0-9]{12,}|password=)'
$$;

CREATE OR REPLACE FUNCTION public.hermes_worker_execution_secret_guard(p_payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
    SELECT p_payload::text ~* '("(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value)"[[:space:]]*:|private key|(^|[^a-z0-9])sk-[a-z0-9]{12,}|password=)'
$$;

CREATE OR REPLACE FUNCTION public.hermes_capability_has_secret_value(p_payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
    SELECT p_payload::text ~* '("(api[_-]?token|password|credential|private[_-]?key)"[[:space:]]*:|private key|(^|[^a-z0-9])sk-[a-z0-9]{12,}|password=)'
$$;

CREATE OR REPLACE FUNCTION public.hermes_human_gate_secret_guard(p_payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
    SELECT p_payload::text ~* '("(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value)"[[:space:]]*:|private key|(^|[^a-z0-9])sk-[a-z0-9]{12,}|password=)'
$$;


