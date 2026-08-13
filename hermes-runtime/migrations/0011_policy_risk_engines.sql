-- P1 Slice 5: Policy Engine and Risk Engine authority.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_policy_owner') THEN
        CREATE ROLE hermes_policy_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_policy_runtime') THEN
        CREATE ROLE hermes_policy_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_risk_owner') THEN
        CREATE ROLE hermes_risk_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_risk_runtime') THEN
        CREATE ROLE hermes_risk_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.policy_bundle_versions (
    policy_bundle_version TEXT PRIMARY KEY,
    policy_rule_version TEXT NOT NULL,
    hierarchy_order TEXT[] NOT NULL,
    merge_semantics TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (content_hash LIKE 'sha256:%'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.policy_rules (
    rule_id TEXT PRIMARY KEY,
    policy_bundle_version TEXT NOT NULL REFERENCES public.policy_bundle_versions(policy_bundle_version),
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    priority INTEGER NOT NULL,
    effect TEXT NOT NULL CHECK (effect IN ('ALLOW','DENY','REQUIRE_HUMAN')),
    action_types TEXT[] NOT NULL,
    target_patterns TEXT[] NOT NULL DEFAULT '{}',
    environment_classes TEXT[] NOT NULL DEFAULT '{}',
    required_authority TEXT[] NOT NULL DEFAULT '{}',
    constraints JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason_codes TEXT[] NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    content_hash TEXT NOT NULL CHECK (content_hash LIKE 'sha256:%'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO public.policy_bundle_versions(
    policy_bundle_version, policy_rule_version, hierarchy_order,
    merge_semantics, content_hash
) VALUES (
    'policy-bundle/1.0', 'policy-rules/1.0',
    ARRAY['runtime_emergency','system','project','user','task','tool_sandbox'],
    'deny_overrides_require_human_over_allow_constraints_intersect',
    'sha256:' || encode(public.digest(convert_to(
        'policy-bundle/1.0|policy-rules/1.0|deny_overrides',
        'UTF8'), 'sha256'), 'hex')
) ON CONFLICT DO NOTHING;

INSERT INTO public.policy_rules(
    rule_id, policy_bundle_version, scope_type, scope_id, priority, effect,
    action_types, environment_classes, constraints, reason_codes, content_hash
) VALUES
('policy.system.emergency_freeze.deny.v1','policy-bundle/1.0','runtime_emergency','*',1000,'DENY',
 ARRAY['*'],ARRAY['*'],'{}'::jsonb,ARRAY['runtime_emergency_freeze'],
 'sha256:' || encode(public.digest(convert_to('policy.system.emergency_freeze.deny.v1','UTF8'),'sha256'),'hex')),
('policy.system.read_only_diagnosis.allow.v1','policy-bundle/1.0','system','*',100,'ALLOW',
 ARRAY['diagnose','run_deeper_test'],ARRAY['dev','test','unknown'],
 '{"network_access":"disabled","filesystem_write":"none","production_access":"denied","secret_access":"denied","max_risk_level":"MEDIUM","max_external_api_calls":0}'::jsonb,
 ARRAY['read_only_diagnosis_allowed'],
 'sha256:' || encode(public.digest(convert_to('policy.system.read_only_diagnosis.allow.v1','UTF8'),'sha256'),'hex')),
('policy.system.retry.allow.v1','policy-bundle/1.0','system','*',100,'ALLOW',
 ARRAY['retry'],ARRAY['dev','test','unknown'],
 '{"network_access":"disabled","filesystem_write":"none","production_access":"denied","secret_access":"denied","max_risk_level":"MEDIUM"}'::jsonb,
 ARRAY['same_artifact_retry_allowed'],
 'sha256:' || encode(public.digest(convert_to('policy.system.retry.allow.v1','UTF8'),'sha256'),'hex')),
('policy.system.schedule_ready_task.allow.v1','policy-bundle/1.0','system','*',100,'ALLOW',
 ARRAY['schedule_ready_task'],ARRAY['dev','test','unknown'],
 '{"production_access":"denied","max_risk_level":"HIGH"}'::jsonb,
 ARRAY['schedule_ready_task_may_enter_later_checks'],
 'sha256:' || encode(public.digest(convert_to('policy.system.schedule_ready_task.allow.v1','UTF8'),'sha256'),'hex')),
('policy.system.pause.allow.v1','policy-bundle/1.0','system','*',100,'ALLOW',
 ARRAY['pause'],ARRAY['*'],
 '{"production_access":"denied","max_risk_level":"LOW"}'::jsonb,
 ARRAY['pause_candidate_may_enter_later_checks'],
 'sha256:' || encode(public.digest(convert_to('policy.system.pause.allow.v1','UTF8'),'sha256'),'hex')),
('policy.system.request_resource.human.v1','policy-bundle/1.0','system','*',100,'REQUIRE_HUMAN',
 ARRAY['request_resource'],ARRAY['*'],
 '{"required_mitigations":["human_budget_authorization"]}'::jsonb,
 ARRAY['external_budget_authorization_required'],
 'sha256:' || encode(public.digest(convert_to('policy.system.request_resource.human.v1','UTF8'),'sha256'),'hex')),
('policy.system.repair.production.human.v1','policy-bundle/1.0','system','*',400,'REQUIRE_HUMAN',
 ARRAY['repair'],ARRAY['production'],
 '{"production_access":"requires_human","required_mitigations":["human_production_change_authorization"],"max_risk_level":"HIGH"}'::jsonb,
 ARRAY['production_repair_requires_human'],
 'sha256:' || encode(public.digest(convert_to('policy.system.repair.production.human.v1','UTF8'),'sha256'),'hex')),
('policy.system.repair.safe_code.allow.v1','policy-bundle/1.0','system','*',100,'ALLOW',
 ARRAY['repair'],ARRAY['dev','test'],
 '{"network_access":"disabled","filesystem_write":"workspace_only","production_access":"denied","secret_access":"denied","max_risk_level":"HIGH","required_mitigations":["verification_before_apply"]}'::jsonb,
 ARRAY['bounded_code_repair_allowed'],
 'sha256:' || encode(public.digest(convert_to('policy.system.repair.safe_code.allow.v1','UTF8'),'sha256'),'hex'))
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.policy_evaluation_contexts (
    evaluation_context_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    planning_run_id TEXT NOT NULL REFERENCES public.planning_runs(planning_run_id),
    action_id TEXT NOT NULL REFERENCES public.candidate_actions(action_id),
    action_content_hash TEXT NOT NULL CHECK (action_content_hash LIKE 'sha256:%'),
    situation_id TEXT NOT NULL REFERENCES public.situations(situation_id),
    situation_version BIGINT NOT NULL,
    analysis_context_hash TEXT NOT NULL CHECK (analysis_context_hash LIKE 'sha256:%'),
    diagnosis_id TEXT,
    diagnosis_input_hash TEXT,
    planner_input_hash TEXT NOT NULL CHECK (planner_input_hash LIKE 'sha256:%'),
    candidate_registry_version TEXT NOT NULL,
    policy_bundle_version TEXT NOT NULL,
    risk_model_version TEXT,
    target_environment TEXT NOT NULL,
    target_classifications TEXT[] NOT NULL DEFAULT '{}',
    tool_requirements TEXT[] NOT NULL DEFAULT '{}',
    secret_availability_refs TEXT[] NOT NULL DEFAULT '{}',
    rollback_plan_refs TEXT[] NOT NULL DEFAULT '{}',
    mitigation_refs TEXT[] NOT NULL DEFAULT '{}',
    resource_estimate_hash TEXT NOT NULL CHECK (resource_estimate_hash LIKE 'sha256:%'),
    context_hash TEXT NOT NULL CHECK (context_hash LIKE 'sha256:%'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.policy_decisions (
    policy_decision_id TEXT PRIMARY KEY,
    evaluation_context_id TEXT NOT NULL REFERENCES public.policy_evaluation_contexts(evaluation_context_id),
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    planning_run_id TEXT NOT NULL REFERENCES public.planning_runs(planning_run_id),
    action_id TEXT NOT NULL REFERENCES public.candidate_actions(action_id),
    action_content_hash TEXT NOT NULL CHECK (action_content_hash LIKE 'sha256:%'),
    result TEXT NOT NULL CHECK (result IN ('ALLOW','DENY','REQUIRE_HUMAN')),
    matched_rule_ids TEXT[] NOT NULL DEFAULT '{}',
    reason_codes TEXT[] NOT NULL DEFAULT '{}',
    constraints JSONB NOT NULL DEFAULT '{}'::jsonb,
    policy_bundle_version TEXT NOT NULL,
    policy_rule_version TEXT NOT NULL,
    policy_input_hash TEXT NOT NULL CHECK (policy_input_hash LIKE 'sha256:%'),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS policy_decisions_equivalent_input
    ON public.policy_decisions(action_id, action_content_hash, policy_bundle_version, policy_input_hash);

CREATE TABLE IF NOT EXISTS public.policy_decision_rules (
    policy_decision_id TEXT NOT NULL REFERENCES public.policy_decisions(policy_decision_id),
    rule_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY(policy_decision_id, rule_id)
);

CREATE TABLE IF NOT EXISTS public.policy_constraints (
    policy_decision_id TEXT NOT NULL REFERENCES public.policy_decisions(policy_decision_id),
    constraint_type TEXT NOT NULL CHECK (constraint_type IN (
        'network_access','filesystem_write','environment','secret_access',
        'production_access','max_risk_level','required_mitigations',
        'allowed_tools','forbidden_paths','max_external_api_calls'
    )),
    constraint_value JSONB NOT NULL,
    PRIMARY KEY(policy_decision_id, constraint_type)
);

CREATE TABLE IF NOT EXISTS public.current_policy_decisions (
    action_id TEXT PRIMARY KEY REFERENCES public.candidate_actions(action_id),
    policy_decision_id TEXT NOT NULL REFERENCES public.policy_decisions(policy_decision_id),
    planning_run_id TEXT NOT NULL,
    action_content_hash TEXT NOT NULL,
    policy_bundle_version TEXT NOT NULL,
    policy_input_hash TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.risk_model_versions (
    risk_model_version TEXT PRIMARY KEY,
    risk_rule_version TEXT NOT NULL,
    factor_weights JSONB NOT NULL,
    level_thresholds JSONB NOT NULL,
    residual_risk_rules JSONB NOT NULL,
    content_hash TEXT NOT NULL CHECK (content_hash LIKE 'sha256:%'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO public.risk_model_versions(
    risk_model_version, risk_rule_version, factor_weights, level_thresholds,
    residual_risk_rules, content_hash
) VALUES (
    'risk-model/1.0','risk-rules/1.0',
    '{"environment":1600,"data_impact":1200,"irreversibility":1200,"privilege":1000,"blast_radius":1000,"network_exposure":900,"secret_exposure":1100,"supply_chain":800,"rollback_confidence":700,"worker_or_tool_trust":500}'::jsonb,
    '{"LOW":[0,2499],"MEDIUM":[2500,5499],"HIGH":[5500,7999],"CRITICAL":[8000,10000]}'::jsonb,
    '{"verified_mitigations_only":true}'::jsonb,
    'sha256:' || encode(public.digest(convert_to('risk-model/1.0|risk-rules/1.0','UTF8'),'sha256'),'hex')
) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.risk_assessments (
    risk_assessment_id TEXT PRIMARY KEY,
    evaluation_context_id TEXT NOT NULL REFERENCES public.policy_evaluation_contexts(evaluation_context_id),
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    planning_run_id TEXT NOT NULL REFERENCES public.planning_runs(planning_run_id),
    action_id TEXT NOT NULL REFERENCES public.candidate_actions(action_id),
    action_content_hash TEXT NOT NULL CHECK (action_content_hash LIKE 'sha256:%'),
    risk_score_basis_points INTEGER NOT NULL CHECK (risk_score_basis_points BETWEEN 0 AND 10000),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    factors JSONB NOT NULL,
    reason_codes TEXT[] NOT NULL DEFAULT '{}',
    required_mitigations TEXT[] NOT NULL DEFAULT '{}',
    available_mitigations TEXT[] NOT NULL DEFAULT '{}',
    residual_risk_basis_points INTEGER NOT NULL CHECK (residual_risk_basis_points BETWEEN 0 AND 10000),
    risk_model_version TEXT NOT NULL,
    risk_rule_version TEXT NOT NULL,
    risk_input_hash TEXT NOT NULL CHECK (risk_input_hash LIKE 'sha256:%'),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    assessed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS risk_assessments_equivalent_input
    ON public.risk_assessments(action_id, action_content_hash, risk_model_version, risk_input_hash);

CREATE TABLE IF NOT EXISTS public.risk_factors (
    risk_assessment_id TEXT NOT NULL REFERENCES public.risk_assessments(risk_assessment_id),
    factor_name TEXT NOT NULL,
    factor_score_basis_points INTEGER NOT NULL CHECK (factor_score_basis_points BETWEEN 0 AND 10000),
    PRIMARY KEY(risk_assessment_id, factor_name)
);

CREATE TABLE IF NOT EXISTS public.risk_mitigations (
    risk_assessment_id TEXT NOT NULL REFERENCES public.risk_assessments(risk_assessment_id),
    mitigation_ref TEXT NOT NULL,
    verified BOOLEAN NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY(risk_assessment_id, mitigation_ref)
);

CREATE TABLE IF NOT EXISTS public.current_risk_assessments (
    action_id TEXT PRIMARY KEY REFERENCES public.candidate_actions(action_id),
    risk_assessment_id TEXT NOT NULL REFERENCES public.risk_assessments(risk_assessment_id),
    planning_run_id TEXT NOT NULL,
    action_content_hash TEXT NOT NULL,
    risk_model_version TEXT NOT NULL,
    risk_input_hash TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.hermes_reject_policy_risk_history_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'policy_bundle_versions','policy_rules','policy_evaluation_contexts',
        'policy_decisions','policy_decision_rules','policy_constraints',
        'risk_model_versions','risk_assessments','risk_factors','risk_mitigations'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS policy_risk_immutable ON public.%I', table_name);
        EXECUTE format(
            'CREATE TRIGGER policy_risk_immutable BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_policy_risk_history_change()',
            table_name
        );
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_apply_policy_decision(
    p_policy_decision_id TEXT,
    p_evaluation_context_id TEXT,
    p_project_id TEXT,
    p_planning_run_id TEXT,
    p_planner_input_hash TEXT,
    p_action_id TEXT,
    p_action_content_hash TEXT,
    p_expected_situation_version BIGINT,
    p_result TEXT,
    p_matched_rule_ids TEXT[],
    p_reason_codes TEXT[],
    p_constraints JSONB,
    p_policy_bundle_version TEXT,
    p_policy_rule_version TEXT,
    p_policy_input_hash TEXT,
    p_context_hash TEXT,
    p_resource_estimate_hash TEXT,
    p_target_environment TEXT,
    p_command_id TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    run_row public.planning_runs%ROWTYPE;
    current_run public.current_planning_runs%ROWTYPE;
    action_row public.candidate_actions%ROWTYPE;
    situation_row public.situations%ROWTYPE;
    diagnosis_row public.diagnoses%ROWTYPE;
    inserted_id TEXT;
    event_id TEXT;
    event_sequence BIGINT;
    event_payload JSONB;
BEGIN
    IF p_actor_type <> 'policy_engine' OR NULLIF(btrim(p_actor_id), '') IS NULL THEN
        RAISE EXCEPTION 'POLICY_AUTHORITY_REQUIRED';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.command_receipts c
        WHERE c.command_id = p_command_id AND c.project_id = p_project_id
          AND c.command_type = 'policy.evaluate'
          AND c.status = 'PROCESSING'
    ) THEN RAISE EXCEPTION 'POLICY_AUTHORITY_REQUIRED'; END IF;
    IF NOT EXISTS (SELECT 1 FROM public.policy_bundle_versions WHERE policy_bundle_version = p_policy_bundle_version) THEN
        RAISE EXCEPTION 'POLICY_BUNDLE_VERSION_UNSUPPORTED';
    END IF;

    SELECT * INTO run_row FROM public.planning_runs
    WHERE planning_run_id = p_planning_run_id AND project_id = p_project_id
    FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'POLICY_PLANNING_RUN_NOT_CURRENT'; END IF;
    SELECT * INTO current_run FROM public.current_planning_runs
    WHERE situation_id = run_row.situation_id;
    IF NOT FOUND OR current_run.planning_run_id <> p_planning_run_id THEN
        RAISE EXCEPTION 'POLICY_PLANNING_RUN_NOT_CURRENT';
    END IF;
    IF run_row.input_hash <> p_planner_input_hash THEN
        RAISE EXCEPTION 'POLICY_CONTEXT_STALE';
    END IF;
    SELECT * INTO action_row FROM public.candidate_actions
    WHERE action_id = p_action_id AND planning_run_id = p_planning_run_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'POLICY_ACTION_NOT_FOUND'; END IF;
    IF action_row.content_hash <> p_action_content_hash THEN
        RAISE EXCEPTION 'POLICY_ACTION_HASH_MISMATCH';
    END IF;
    SELECT * INTO situation_row FROM public.situations
    WHERE situation_id = run_row.situation_id AND project_id = p_project_id;
    IF NOT FOUND OR situation_row.status <> 'OPEN'
       OR situation_row.version <> p_expected_situation_version
       OR situation_row.version <> run_row.situation_version
       OR situation_row.analysis_context_id <> run_row.analysis_context_id THEN
        RAISE EXCEPTION 'POLICY_CONTEXT_STALE';
    END IF;
    IF run_row.diagnosis_id IS NOT NULL THEN
        SELECT d.* INTO diagnosis_row
        FROM public.current_diagnoses cd JOIN public.diagnoses d ON d.diagnosis_id = cd.diagnosis_id
        WHERE cd.situation_id = run_row.situation_id;
        IF NOT FOUND OR diagnosis_row.diagnosis_id <> run_row.diagnosis_id
           OR diagnosis_row.input_hash <> run_row.diagnosis_input_hash THEN
            RAISE EXCEPTION 'POLICY_CONTEXT_STALE';
        END IF;
    END IF;
    IF p_fault_point = 'after_context_before_result' THEN
        RAISE EXCEPTION 'INJECTED_POLICY_CRASH_AFTER_CONTEXT';
    END IF;

    INSERT INTO public.policy_evaluation_contexts(
        evaluation_context_id, project_id, planning_run_id, action_id,
        action_content_hash, situation_id, situation_version,
        analysis_context_hash, diagnosis_id, diagnosis_input_hash,
        planner_input_hash, candidate_registry_version, policy_bundle_version,
        target_environment, resource_estimate_hash, context_hash
    ) VALUES (
        p_evaluation_context_id, p_project_id, p_planning_run_id, p_action_id,
        p_action_content_hash, run_row.situation_id, run_row.situation_version,
        run_row.analysis_context_hash, run_row.diagnosis_id, run_row.diagnosis_input_hash,
        run_row.input_hash, action_row.registry_version, p_policy_bundle_version,
        p_target_environment, p_resource_estimate_hash, p_context_hash
    ) ON CONFLICT DO NOTHING;

    INSERT INTO public.policy_decisions(
        policy_decision_id, evaluation_context_id, project_id, planning_run_id,
        action_id, action_content_hash, result, matched_rule_ids, reason_codes,
        constraints, policy_bundle_version, policy_rule_version,
        policy_input_hash, command_id
    ) VALUES (
        p_policy_decision_id, p_evaluation_context_id, p_project_id, p_planning_run_id,
        p_action_id, p_action_content_hash, p_result, COALESCE(p_matched_rule_ids,'{}'),
        COALESCE(p_reason_codes,'{}'), COALESCE(p_constraints,'{}'::jsonb),
        p_policy_bundle_version, p_policy_rule_version, p_policy_input_hash, p_command_id
    ) ON CONFLICT DO NOTHING RETURNING policy_decision_id INTO inserted_id;

    IF inserted_id IS NULL THEN
        SELECT policy_decision_id INTO inserted_id FROM public.policy_decisions
        WHERE action_id = p_action_id AND action_content_hash = p_action_content_hash
          AND policy_bundle_version = p_policy_bundle_version
          AND policy_input_hash = p_policy_input_hash;
        RETURN jsonb_build_object('policy_decision_id', inserted_id, 'event_id', NULL, 'deduplicated', true);
    END IF;
    IF p_fault_point = 'after_result_before_child' THEN
        RAISE EXCEPTION 'INJECTED_POLICY_CRASH_AFTER_RESULT';
    END IF;

    INSERT INTO public.policy_decision_rules(policy_decision_id, rule_id, ordinal)
    SELECT inserted_id, value, ordinality - 1
    FROM unnest(COALESCE(p_matched_rule_ids,'{}')) WITH ORDINALITY AS refs(value, ordinality);
    INSERT INTO public.policy_constraints(policy_decision_id, constraint_type, constraint_value)
    SELECT inserted_id, key, value FROM jsonb_each(COALESCE(p_constraints,'{}'::jsonb));
    IF p_fault_point = 'after_child_before_current' THEN
        RAISE EXCEPTION 'INJECTED_POLICY_CRASH_AFTER_CHILD';
    END IF;

    INSERT INTO public.current_policy_decisions(
        action_id, policy_decision_id, planning_run_id, action_content_hash,
        policy_bundle_version, policy_input_hash
    ) VALUES (
        p_action_id, inserted_id, p_planning_run_id, p_action_content_hash,
        p_policy_bundle_version, p_policy_input_hash
    ) ON CONFLICT (action_id) DO UPDATE SET
        policy_decision_id = EXCLUDED.policy_decision_id,
        planning_run_id = EXCLUDED.planning_run_id,
        action_content_hash = EXCLUDED.action_content_hash,
        policy_bundle_version = EXCLUDED.policy_bundle_version,
        policy_input_hash = EXCLUDED.policy_input_hash,
        updated_at = now();
    IF p_fault_point = 'after_current_before_event' THEN
        RAISE EXCEPTION 'INJECTED_POLICY_CRASH_AFTER_CURRENT';
    END IF;

    event_id := 'evt-' || gen_random_uuid()::text;
    event_payload := jsonb_build_object(
        'policy_decision_id', inserted_id,
        'planning_run_id', p_planning_run_id,
        'action_id', p_action_id,
        'action_content_hash', p_action_content_hash,
        'result', p_result,
        'policy_bundle_version', p_policy_bundle_version,
        'policy_input_hash', p_policy_input_hash
    );
    INSERT INTO public.event_log(
        event_id, event_type, schema_version, producer_type, producer_id,
        project_id, partition_key, command_id, correlation_id,
        causation_id, task_id, payload
    ) VALUES (
        event_id, 'policy.evaluated', '1.0', 'policy_engine', p_actor_id,
        p_project_id, p_project_id, p_command_id, p_command_id,
        action_row.action_id, situation_row.task_id, event_payload
    ) RETURNING sequence INTO event_sequence;
    IF p_fault_point = 'after_event_before_outbox' THEN
        RAISE EXCEPTION 'INJECTED_POLICY_CRASH_AFTER_EVENT';
    END IF;
    INSERT INTO public.outbox_messages(message_id, event_id, topic, partition_key, sequence, payload)
    VALUES ('msg-' || gen_random_uuid()::text, event_id, 'hermes.runtime.events',
            p_project_id, event_sequence, event_payload);
    IF p_fault_point = 'after_outbox_before_receipt' THEN
        RAISE EXCEPTION 'INJECTED_POLICY_CRASH_AFTER_OUTBOX';
    END IF;
    RETURN jsonb_build_object('policy_decision_id', inserted_id, 'event_id', event_id, 'deduplicated', false);
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_apply_risk_assessment(
    p_risk_assessment_id TEXT,
    p_evaluation_context_id TEXT,
    p_project_id TEXT,
    p_planning_run_id TEXT,
    p_planner_input_hash TEXT,
    p_action_id TEXT,
    p_action_content_hash TEXT,
    p_expected_situation_version BIGINT,
    p_risk_score_basis_points INTEGER,
    p_risk_level TEXT,
    p_factors JSONB,
    p_reason_codes TEXT[],
    p_required_mitigations TEXT[],
    p_available_mitigations TEXT[],
    p_residual_risk_basis_points INTEGER,
    p_risk_model_version TEXT,
    p_risk_rule_version TEXT,
    p_risk_input_hash TEXT,
    p_context_hash TEXT,
    p_resource_estimate_hash TEXT,
    p_target_environment TEXT,
    p_command_id TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    run_row public.planning_runs%ROWTYPE;
    current_run public.current_planning_runs%ROWTYPE;
    action_row public.candidate_actions%ROWTYPE;
    situation_row public.situations%ROWTYPE;
    diagnosis_row public.diagnoses%ROWTYPE;
    inserted_id TEXT;
    event_id TEXT;
    event_sequence BIGINT;
    event_payload JSONB;
BEGIN
    IF p_actor_type <> 'risk_engine' OR NULLIF(btrim(p_actor_id), '') IS NULL THEN
        RAISE EXCEPTION 'RISK_AUTHORITY_REQUIRED';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.command_receipts c
        WHERE c.command_id = p_command_id AND c.project_id = p_project_id
          AND c.command_type = 'risk.assess'
          AND c.status = 'PROCESSING'
    ) THEN RAISE EXCEPTION 'RISK_AUTHORITY_REQUIRED'; END IF;
    IF NOT EXISTS (SELECT 1 FROM public.risk_model_versions WHERE risk_model_version = p_risk_model_version) THEN
        RAISE EXCEPTION 'RISK_MODEL_VERSION_UNSUPPORTED';
    END IF;
    SELECT * INTO run_row FROM public.planning_runs
    WHERE planning_run_id = p_planning_run_id AND project_id = p_project_id
    FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'RISK_PLANNING_RUN_NOT_CURRENT'; END IF;
    SELECT * INTO current_run FROM public.current_planning_runs
    WHERE situation_id = run_row.situation_id;
    IF NOT FOUND OR current_run.planning_run_id <> p_planning_run_id THEN
        RAISE EXCEPTION 'RISK_PLANNING_RUN_NOT_CURRENT';
    END IF;
    IF run_row.input_hash <> p_planner_input_hash THEN
        RAISE EXCEPTION 'RISK_CONTEXT_STALE';
    END IF;
    SELECT * INTO action_row FROM public.candidate_actions
    WHERE action_id = p_action_id AND planning_run_id = p_planning_run_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'RISK_ACTION_NOT_FOUND'; END IF;
    IF action_row.content_hash <> p_action_content_hash THEN
        RAISE EXCEPTION 'RISK_ACTION_HASH_MISMATCH';
    END IF;
    SELECT * INTO situation_row FROM public.situations
    WHERE situation_id = run_row.situation_id AND project_id = p_project_id;
    IF NOT FOUND OR situation_row.status <> 'OPEN'
       OR situation_row.version <> p_expected_situation_version
       OR situation_row.version <> run_row.situation_version THEN
        RAISE EXCEPTION 'RISK_CONTEXT_STALE';
    END IF;
    IF run_row.diagnosis_id IS NOT NULL THEN
        SELECT d.* INTO diagnosis_row
        FROM public.current_diagnoses cd JOIN public.diagnoses d ON d.diagnosis_id = cd.diagnosis_id
        WHERE cd.situation_id = run_row.situation_id;
        IF NOT FOUND OR diagnosis_row.diagnosis_id <> run_row.diagnosis_id
           OR diagnosis_row.input_hash <> run_row.diagnosis_input_hash THEN
            RAISE EXCEPTION 'RISK_CONTEXT_STALE';
        END IF;
    END IF;
    IF p_fault_point = 'after_context_before_result' THEN
        RAISE EXCEPTION 'INJECTED_RISK_CRASH_AFTER_CONTEXT';
    END IF;
    INSERT INTO public.policy_evaluation_contexts(
        evaluation_context_id, project_id, planning_run_id, action_id,
        action_content_hash, situation_id, situation_version,
        analysis_context_hash, diagnosis_id, diagnosis_input_hash,
        planner_input_hash, candidate_registry_version, policy_bundle_version,
        risk_model_version, target_environment, resource_estimate_hash, context_hash
    ) VALUES (
        p_evaluation_context_id, p_project_id, p_planning_run_id, p_action_id,
        p_action_content_hash, run_row.situation_id, run_row.situation_version,
        run_row.analysis_context_hash, run_row.diagnosis_id, run_row.diagnosis_input_hash,
        run_row.input_hash, action_row.registry_version, 'policy-bundle/1.0',
        p_risk_model_version, p_target_environment, p_resource_estimate_hash, p_context_hash
    ) ON CONFLICT DO NOTHING;
    INSERT INTO public.risk_assessments(
        risk_assessment_id, evaluation_context_id, project_id, planning_run_id,
        action_id, action_content_hash, risk_score_basis_points, risk_level,
        factors, reason_codes, required_mitigations, available_mitigations,
        residual_risk_basis_points, risk_model_version, risk_rule_version,
        risk_input_hash, command_id
    ) VALUES (
        p_risk_assessment_id, p_evaluation_context_id, p_project_id, p_planning_run_id,
        p_action_id, p_action_content_hash, p_risk_score_basis_points, p_risk_level,
        p_factors, COALESCE(p_reason_codes,'{}'), COALESCE(p_required_mitigations,'{}'),
        COALESCE(p_available_mitigations,'{}'), p_residual_risk_basis_points,
        p_risk_model_version, p_risk_rule_version, p_risk_input_hash, p_command_id
    ) ON CONFLICT DO NOTHING RETURNING risk_assessment_id INTO inserted_id;
    IF inserted_id IS NULL THEN
        SELECT risk_assessment_id INTO inserted_id FROM public.risk_assessments
        WHERE action_id = p_action_id AND action_content_hash = p_action_content_hash
          AND risk_model_version = p_risk_model_version
          AND risk_input_hash = p_risk_input_hash;
        RETURN jsonb_build_object('risk_assessment_id', inserted_id, 'event_id', NULL, 'deduplicated', true);
    END IF;
    IF p_fault_point = 'after_result_before_child' THEN
        RAISE EXCEPTION 'INJECTED_RISK_CRASH_AFTER_RESULT';
    END IF;
    INSERT INTO public.risk_factors(risk_assessment_id, factor_name, factor_score_basis_points)
    SELECT inserted_id, key, (value)::integer FROM jsonb_each_text(p_factors);
    INSERT INTO public.risk_mitigations(risk_assessment_id, mitigation_ref, verified, ordinal)
    SELECT inserted_id, value, true, ordinality - 1
    FROM unnest(COALESCE(p_available_mitigations,'{}')) WITH ORDINALITY AS refs(value, ordinality);
    IF p_fault_point = 'after_child_before_current' THEN
        RAISE EXCEPTION 'INJECTED_RISK_CRASH_AFTER_CHILD';
    END IF;
    INSERT INTO public.current_risk_assessments(
        action_id, risk_assessment_id, planning_run_id, action_content_hash,
        risk_model_version, risk_input_hash
    ) VALUES (
        p_action_id, inserted_id, p_planning_run_id, p_action_content_hash,
        p_risk_model_version, p_risk_input_hash
    ) ON CONFLICT (action_id) DO UPDATE SET
        risk_assessment_id = EXCLUDED.risk_assessment_id,
        planning_run_id = EXCLUDED.planning_run_id,
        action_content_hash = EXCLUDED.action_content_hash,
        risk_model_version = EXCLUDED.risk_model_version,
        risk_input_hash = EXCLUDED.risk_input_hash,
        updated_at = now();
    IF p_fault_point = 'after_current_before_event' THEN
        RAISE EXCEPTION 'INJECTED_RISK_CRASH_AFTER_CURRENT';
    END IF;
    event_id := 'evt-' || gen_random_uuid()::text;
    event_payload := jsonb_build_object(
        'risk_assessment_id', inserted_id,
        'planning_run_id', p_planning_run_id,
        'action_id', p_action_id,
        'action_content_hash', p_action_content_hash,
        'risk_score_basis_points', p_risk_score_basis_points,
        'risk_level', p_risk_level,
        'risk_model_version', p_risk_model_version,
        'risk_input_hash', p_risk_input_hash
    );
    INSERT INTO public.event_log(
        event_id, event_type, schema_version, producer_type, producer_id,
        project_id, partition_key, command_id, correlation_id,
        causation_id, task_id, payload
    ) VALUES (
        event_id, 'risk.assessed', '1.0', 'risk_engine', p_actor_id,
        p_project_id, p_project_id, p_command_id, p_command_id,
        action_row.action_id, situation_row.task_id, event_payload
    ) RETURNING sequence INTO event_sequence;
    IF p_fault_point = 'after_event_before_outbox' THEN
        RAISE EXCEPTION 'INJECTED_RISK_CRASH_AFTER_EVENT';
    END IF;
    INSERT INTO public.outbox_messages(message_id, event_id, topic, partition_key, sequence, payload)
    VALUES ('msg-' || gen_random_uuid()::text, event_id, 'hermes.runtime.events',
            p_project_id, event_sequence, event_payload);
    IF p_fault_point = 'after_outbox_before_receipt' THEN
        RAISE EXCEPTION 'INJECTED_RISK_CRASH_AFTER_OUTBOX';
    END IF;
    RETURN jsonb_build_object('risk_assessment_id', inserted_id, 'event_id', event_id, 'deduplicated', false);
END;
$$;

ALTER TABLE public.policy_bundle_versions OWNER TO hermes_policy_owner;
ALTER TABLE public.policy_rules OWNER TO hermes_policy_owner;
ALTER TABLE public.policy_evaluation_contexts OWNER TO hermes_policy_owner;
ALTER TABLE public.policy_decisions OWNER TO hermes_policy_owner;
ALTER TABLE public.policy_decision_rules OWNER TO hermes_policy_owner;
ALTER TABLE public.policy_constraints OWNER TO hermes_policy_owner;
ALTER TABLE public.current_policy_decisions OWNER TO hermes_policy_owner;
ALTER TABLE public.risk_model_versions OWNER TO hermes_risk_owner;
ALTER TABLE public.risk_assessments OWNER TO hermes_risk_owner;
ALTER TABLE public.risk_factors OWNER TO hermes_risk_owner;
ALTER TABLE public.risk_mitigations OWNER TO hermes_risk_owner;
ALTER TABLE public.current_risk_assessments OWNER TO hermes_risk_owner;
ALTER FUNCTION public.hermes_reject_policy_risk_history_change() OWNER TO hermes_policy_owner;
ALTER FUNCTION public.hermes_apply_policy_decision(
    TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT[],TEXT[],JSONB,
    TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) OWNER TO hermes_policy_owner;
ALTER FUNCTION public.hermes_apply_risk_assessment(
    TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,INTEGER,TEXT,JSONB,TEXT[],TEXT[],
    TEXT[],INTEGER,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) OWNER TO hermes_risk_owner;

GRANT SELECT ON public.projects, public.tasks, public.situations,
    public.analysis_contexts, public.current_diagnoses, public.diagnoses,
    public.planning_runs, public.current_planning_runs, public.candidate_actions,
    public.policy_bundle_versions, public.policy_rules,
    public.command_receipts TO hermes_policy_owner;
GRANT SELECT, INSERT ON public.policy_evaluation_contexts, public.policy_decisions,
    public.policy_decision_rules, public.policy_constraints TO hermes_policy_owner;
GRANT SELECT, INSERT, UPDATE ON public.current_policy_decisions TO hermes_policy_owner;
GRANT SELECT, INSERT ON public.event_log, public.outbox_messages TO hermes_policy_owner;
GRANT UPDATE ON public.planning_runs TO hermes_policy_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_policy_owner;

GRANT SELECT ON public.projects, public.tasks, public.situations,
    public.analysis_contexts, public.current_diagnoses, public.diagnoses,
    public.planning_runs, public.current_planning_runs, public.candidate_actions,
    public.risk_model_versions, public.command_receipts TO hermes_risk_owner;
GRANT SELECT, INSERT ON public.policy_evaluation_contexts, public.risk_assessments,
    public.risk_factors, public.risk_mitigations TO hermes_risk_owner;
GRANT SELECT, INSERT, UPDATE ON public.current_risk_assessments TO hermes_risk_owner;
GRANT SELECT, INSERT ON public.event_log, public.outbox_messages TO hermes_risk_owner;
GRANT UPDATE ON public.planning_runs TO hermes_risk_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_risk_owner;

REVOKE ALL ON public.policy_bundle_versions, public.policy_rules,
    public.policy_evaluation_contexts, public.policy_decisions,
    public.policy_decision_rules, public.policy_constraints,
    public.current_policy_decisions, public.risk_model_versions,
    public.risk_assessments, public.risk_factors, public.risk_mitigations,
    public.current_risk_assessments FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_apply_policy_decision(
    TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT[],TEXT[],JSONB,
    TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_apply_risk_assessment(
    TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,INTEGER,TEXT,JSONB,TEXT[],TEXT[],
    TEXT[],INTEGER,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC;

GRANT SELECT ON public.policy_bundle_versions, public.policy_rules,
    public.policy_evaluation_contexts, public.policy_decisions,
    public.policy_decision_rules, public.policy_constraints,
    public.current_policy_decisions, public.risk_model_versions,
    public.risk_assessments, public.risk_factors, public.risk_mitigations,
    public.current_risk_assessments
    TO hermes_policy_runtime, hermes_risk_runtime, hermes_read_only_runtime;
GRANT SELECT ON public.projects, public.tasks, public.situations,
    public.analysis_contexts, public.current_diagnoses, public.diagnoses,
    public.planning_runs, public.current_planning_runs, public.candidate_actions
    TO hermes_policy_runtime, hermes_risk_runtime;
GRANT SELECT, INSERT, UPDATE ON public.command_receipts TO hermes_policy_runtime, hermes_risk_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_apply_policy_decision(
    TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT[],TEXT[],JSONB,
    TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) TO hermes_policy_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_apply_risk_assessment(
    TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,INTEGER,TEXT,JSONB,TEXT[],TEXT[],
    TEXT[],INTEGER,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) TO hermes_risk_runtime;

REVOKE INSERT, UPDATE, DELETE ON public.policy_decisions, public.policy_decision_rules,
    public.policy_constraints, public.current_policy_decisions,
    public.risk_assessments, public.risk_factors, public.risk_mitigations,
    public.current_risk_assessments, public.policy_evaluation_contexts
FROM hermes_worker_runtime, hermes_verifier_runtime, hermes_situation_runtime,
     hermes_diagnosis_runtime, hermes_accounting_runtime, hermes_planner_runtime,
     hermes_control_plane_runtime, hermes_policy_runtime, hermes_risk_runtime,
     hermes_read_only_runtime;
REVOKE INSERT, UPDATE, DELETE ON public.planning_runs, public.candidate_actions,
    public.projects, public.tasks, public.situations, public.diagnoses,
    public.resource_accounts, public.resource_balances, public.resource_reservations
FROM hermes_policy_runtime, hermes_risk_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_policy_runtime, hermes_risk_runtime;

COMMENT ON TABLE public.policy_decisions IS
'Immutable PolicyDecision records; ALLOW means only may enter later Risk/Budget/Selection checks.';
COMMENT ON TABLE public.risk_assessments IS
'Immutable RiskAssessment records; never authorizes, selects, reserves or executes CandidateActions.';
