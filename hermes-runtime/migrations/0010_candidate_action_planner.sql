-- P1 Slice 4: Candidate Action Planner and versioned Action Registry.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_planner_owner') THEN
        CREATE ROLE hermes_planner_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_planner_runtime') THEN
        CREATE ROLE hermes_planner_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.action_registry_versions (
    registry_version TEXT PRIMARY KEY,
    planner_rule_version TEXT NOT NULL,
    resource_estimator_version TEXT NOT NULL,
    enabled_action_types TEXT[] NOT NULL,
    disabled_action_types TEXT[] NOT NULL,
    content_hash TEXT NOT NULL CHECK (content_hash LIKE 'sha256:%'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.planning_runs (
    planning_run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    situation_id TEXT NOT NULL REFERENCES public.situations(situation_id),
    situation_version BIGINT NOT NULL CHECK (situation_version >= 1),
    analysis_context_id TEXT NOT NULL REFERENCES public.analysis_contexts(analysis_context_id),
    analysis_context_hash TEXT NOT NULL CHECK (analysis_context_hash LIKE 'sha256:%'),
    diagnosis_id TEXT REFERENCES public.diagnoses(diagnosis_id),
    diagnosis_input_hash TEXT CHECK (diagnosis_input_hash IS NULL OR diagnosis_input_hash LIKE 'sha256:%'),
    registry_version TEXT NOT NULL,
    planner_rule_version TEXT NOT NULL,
    resource_estimator_version TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK (input_hash LIKE 'sha256:%'),
    candidate_count INTEGER NOT NULL CHECK (candidate_count BETWEEN 1 AND 5),
    single_candidate_reason_code TEXT,
    created_by TEXT NOT NULL,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS planning_runs_equivalent_input
    ON public.planning_runs(
        situation_id, situation_version, analysis_context_hash,
        COALESCE(diagnosis_id, ''), COALESCE(diagnosis_input_hash, ''),
        registry_version, planner_rule_version, input_hash
    );

INSERT INTO public.action_registry_versions(
    registry_version, planner_rule_version, resource_estimator_version,
    enabled_action_types, disabled_action_types, content_hash
) VALUES (
    'action-registry/1.0', 'planner-rules/1.0', 'resource-estimator/1.0',
    ARRAY['diagnose','run_deeper_test','repair','retry','switch_strategy',
          'schedule_ready_task','request_resource','pause'],
    ARRAY['switch_agent','expert_review','replan','rollback','human_gate'],
    'sha256:' || encode(public.digest(convert_to(
        'action-registry/1.0|planner-rules/1.0|resource-estimator/1.0',
        'UTF8'), 'sha256'), 'hex')
) ON CONFLICT (registry_version) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.candidate_actions (
    action_id TEXT PRIMARY KEY,
    planning_run_id TEXT NOT NULL REFERENCES public.planning_runs(planning_run_id),
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    situation_id TEXT NOT NULL REFERENCES public.situations(situation_id),
    situation_version BIGINT NOT NULL CHECK (situation_version >= 1),
    analysis_context_id TEXT NOT NULL REFERENCES public.analysis_contexts(analysis_context_id),
    analysis_context_hash TEXT NOT NULL CHECK (analysis_context_hash LIKE 'sha256:%'),
    diagnosis_id TEXT REFERENCES public.diagnoses(diagnosis_id),
    diagnosis_input_hash TEXT CHECK (diagnosis_input_hash IS NULL OR diagnosis_input_hash LIKE 'sha256:%'),
    type TEXT NOT NULL CHECK (type IN (
        'retry','diagnose','repair','switch_strategy','switch_agent',
        'expert_review','run_deeper_test','replan','rollback',
        'schedule_ready_task','request_resource','pause','human_gate'
    )),
    reason_code TEXT NOT NULL,
    target_refs TEXT[] NOT NULL DEFAULT '{}',
    required_capabilities TEXT[] NOT NULL DEFAULT '{}',
    parameters JSONB NOT NULL,
    expected_outputs TEXT[] NOT NULL DEFAULT '{}',
    preconditions TEXT[] NOT NULL DEFAULT '{}',
    estimated_resources JSONB NOT NULL,
    planner_confidence_basis_points INTEGER NOT NULL CHECK (planner_confidence_basis_points BETWEEN 0 AND 10000),
    expected_progress_basis_points INTEGER NOT NULL CHECK (expected_progress_basis_points BETWEEN 0 AND 10000),
    evidence_gain_basis_points INTEGER NOT NULL CHECK (evidence_gain_basis_points BETWEEN 0 AND 10000),
    reversibility_basis_points INTEGER NOT NULL CHECK (reversibility_basis_points BETWEEN 0 AND 10000),
    registry_version TEXT NOT NULL,
    planner_rule_version TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    content_hash TEXT NOT NULL CHECK (content_hash LIKE 'sha256:%'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (expected_progress_basis_points > 0 OR evidence_gain_basis_points > 0),
    UNIQUE (planning_run_id, ordinal),
    UNIQUE (planning_run_id, content_hash)
);

CREATE TABLE IF NOT EXISTS public.candidate_action_targets (
    action_id TEXT NOT NULL REFERENCES public.candidate_actions(action_id),
    target_ref TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (action_id, target_ref)
);

CREATE TABLE IF NOT EXISTS public.candidate_action_capabilities (
    action_id TEXT NOT NULL REFERENCES public.candidate_actions(action_id),
    capability TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (action_id, capability)
);

CREATE TABLE IF NOT EXISTS public.candidate_action_preconditions (
    action_id TEXT NOT NULL REFERENCES public.candidate_actions(action_id),
    precondition TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (action_id, precondition)
);

CREATE TABLE IF NOT EXISTS public.candidate_action_expected_outputs (
    action_id TEXT NOT NULL REFERENCES public.candidate_actions(action_id),
    expected_output TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (action_id, expected_output)
);

CREATE TABLE IF NOT EXISTS public.candidate_action_resource_estimates (
    action_id TEXT NOT NULL REFERENCES public.candidate_actions(action_id),
    dimension TEXT NOT NULL CHECK (dimension IN (
        'llm_tokens','llm_cost_minor','agent_runs','retry_count',
        'execution_time_ms','cpu_time_ms','gpu_time_ms',
        'docker_runtime_ms','browser_runtime_ms','external_api_calls',
        'storage_bytes','human_attention_requests'
    )),
    amount BIGINT NOT NULL CHECK (amount >= 0),
    currency TEXT CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
    estimator_version TEXT NOT NULL,
    PRIMARY KEY (action_id, dimension)
);

CREATE TABLE IF NOT EXISTS public.current_planning_runs (
    situation_id TEXT PRIMARY KEY REFERENCES public.situations(situation_id),
    planning_run_id TEXT NOT NULL REFERENCES public.planning_runs(planning_run_id),
    situation_version BIGINT NOT NULL CHECK (situation_version >= 1),
    analysis_context_hash TEXT NOT NULL CHECK (analysis_context_hash LIKE 'sha256:%'),
    diagnosis_id TEXT,
    diagnosis_input_hash TEXT,
    registry_version TEXT NOT NULL,
    planner_rule_version TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK (input_hash LIKE 'sha256:%'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.hermes_reject_planning_history_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'action_registry_versions','planning_runs','candidate_actions',
        'candidate_action_targets','candidate_action_capabilities',
        'candidate_action_preconditions','candidate_action_expected_outputs',
        'candidate_action_resource_estimates'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS planning_immutable ON public.%I', table_name);
        EXECUTE format(
            'CREATE TRIGGER planning_immutable BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_planning_history_change()',
            table_name
        );
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_apply_planning_run(
    p_planning_run_id TEXT,
    p_project_id TEXT,
    p_situation_id TEXT,
    p_situation_version BIGINT,
    p_analysis_context_id TEXT,
    p_analysis_context_hash TEXT,
    p_diagnosis_id TEXT,
    p_diagnosis_input_hash TEXT,
    p_registry_version TEXT,
    p_planner_rule_version TEXT,
    p_resource_estimator_version TEXT,
    p_input_hash TEXT,
    p_candidate_count INTEGER,
    p_single_candidate_reason_code TEXT,
    p_candidates JSONB,
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
    situation_row public.situations%ROWTYPE;
    context_row public.analysis_contexts%ROWTYPE;
    diagnosis_row public.diagnoses%ROWTYPE;
    inserted_run TEXT;
    event_id TEXT;
    event_sequence BIGINT;
    event_payload JSONB;
BEGIN
    IF p_actor_type <> 'action_planner' OR NULLIF(btrim(p_actor_id), '') IS NULL THEN
        RAISE EXCEPTION 'PLANNER_AUTHORITY_REQUIRED';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.command_receipts c
        WHERE c.command_id = p_command_id AND c.project_id = p_project_id
          AND c.command_type = 'planner.plan_candidates'
          AND c.status = 'PROCESSING'
    ) THEN
        RAISE EXCEPTION 'PLANNER_AUTHORITY_REQUIRED';
    END IF;

    SELECT * INTO situation_row FROM public.situations
    WHERE situation_id = p_situation_id AND project_id = p_project_id
    FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'PLANNER_SITUATION_NOT_FOUND'; END IF;
    IF situation_row.status <> 'OPEN' THEN
        RAISE EXCEPTION 'PLANNER_SITUATION_NOT_OPEN';
    END IF;
    IF situation_row.version <> p_situation_version THEN
        RAISE EXCEPTION 'PLANNER_SITUATION_VERSION_CONFLICT';
    END IF;
    IF situation_row.analysis_context_id <> p_analysis_context_id THEN
        RAISE EXCEPTION 'PLANNER_CONTEXT_NOT_FOUND';
    END IF;

    SELECT * INTO context_row FROM public.analysis_contexts
    WHERE analysis_context_id = p_analysis_context_id AND project_id = p_project_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'PLANNER_CONTEXT_NOT_FOUND'; END IF;
    IF context_row.context_hash <> p_analysis_context_hash THEN
        RAISE EXCEPTION 'PLANNER_CONTEXT_HASH_MISMATCH';
    END IF;

    IF situation_row.type = 'verification_failed' THEN
        IF p_diagnosis_id IS NULL OR p_diagnosis_input_hash IS NULL THEN
            RAISE EXCEPTION 'PLANNER_DIAGNOSIS_REQUIRED';
        END IF;
        SELECT d.* INTO diagnosis_row
        FROM public.current_diagnoses cd
        JOIN public.diagnoses d ON d.diagnosis_id = cd.diagnosis_id
        WHERE cd.situation_id = p_situation_id;
        IF NOT FOUND OR diagnosis_row.diagnosis_id <> p_diagnosis_id THEN
            RAISE EXCEPTION 'PLANNER_DIAGNOSIS_NOT_CURRENT';
        END IF;
        IF diagnosis_row.situation_version <> p_situation_version
           OR diagnosis_row.analysis_context_hash <> p_analysis_context_hash THEN
            RAISE EXCEPTION 'PLANNER_DIAGNOSIS_NOT_CURRENT';
        END IF;
        IF diagnosis_row.input_hash <> p_diagnosis_input_hash THEN
            RAISE EXCEPTION 'PLANNER_DIAGNOSIS_INPUT_MISMATCH';
        END IF;
    ELSIF situation_row.type = 'work_available' AND p_diagnosis_id IS NOT NULL THEN
        RAISE EXCEPTION 'PLANNER_DIAGNOSIS_NOT_ALLOWED';
    END IF;

    INSERT INTO public.planning_runs(
        planning_run_id, project_id, situation_id, situation_version,
        analysis_context_id, analysis_context_hash, diagnosis_id,
        diagnosis_input_hash, registry_version, planner_rule_version,
        resource_estimator_version, input_hash, candidate_count,
        single_candidate_reason_code, created_by, command_id
    ) VALUES (
        p_planning_run_id, p_project_id, p_situation_id, p_situation_version,
        p_analysis_context_id, p_analysis_context_hash, p_diagnosis_id,
        p_diagnosis_input_hash, p_registry_version, p_planner_rule_version,
        p_resource_estimator_version, p_input_hash, p_candidate_count,
        p_single_candidate_reason_code, p_actor_id, p_command_id
    )
    ON CONFLICT DO NOTHING
    RETURNING planning_run_id INTO inserted_run;

    IF inserted_run IS NULL THEN
        SELECT planning_run_id INTO inserted_run FROM public.planning_runs
        WHERE situation_id = p_situation_id
          AND situation_version = p_situation_version
          AND analysis_context_hash = p_analysis_context_hash
          AND COALESCE(diagnosis_id, '') = COALESCE(p_diagnosis_id, '')
          AND COALESCE(diagnosis_input_hash, '') = COALESCE(p_diagnosis_input_hash, '')
          AND registry_version = p_registry_version
          AND planner_rule_version = p_planner_rule_version
          AND input_hash = p_input_hash;
        RETURN jsonb_build_object(
            'planning_run_id', inserted_run,
            'candidate_count', p_candidate_count,
            'event_id', NULL,
            'deduplicated', true
        );
    END IF;

    IF p_fault_point = 'after_planning_run_before_candidate' THEN
        RAISE EXCEPTION 'INJECTED_PLANNER_CRASH_AFTER_RUN';
    END IF;

    INSERT INTO public.candidate_actions(
        action_id, planning_run_id, project_id, situation_id, situation_version,
        analysis_context_id, analysis_context_hash, diagnosis_id,
        diagnosis_input_hash, type, reason_code, target_refs,
        required_capabilities, parameters, expected_outputs, preconditions,
        estimated_resources, planner_confidence_basis_points,
        expected_progress_basis_points, evidence_gain_basis_points,
        reversibility_basis_points, registry_version, planner_rule_version,
        ordinal, content_hash
    )
    SELECT
        item.action_id, inserted_run, p_project_id, p_situation_id,
        p_situation_version, p_analysis_context_id, p_analysis_context_hash,
        p_diagnosis_id, p_diagnosis_input_hash, item.type, item.reason_code,
        COALESCE(item.target_refs, '{}'), COALESCE(item.required_capabilities, '{}'),
        item.parameters, COALESCE(item.expected_outputs, '{}'),
        COALESCE(item.preconditions, '{}'), item.estimated_resources,
        item.planner_confidence_basis_points,
        item.expected_progress_basis_points, item.evidence_gain_basis_points,
        item.reversibility_basis_points, p_registry_version,
        p_planner_rule_version, item.ordinal, item.content_hash
    FROM jsonb_to_recordset(COALESCE(p_candidates, '[]'::jsonb)) AS item(
        action_id TEXT, type TEXT, reason_code TEXT, target_refs TEXT[],
        required_capabilities TEXT[], parameters JSONB,
        expected_outputs TEXT[], preconditions TEXT[],
        estimated_resources JSONB, planner_confidence_basis_points INTEGER,
        expected_progress_basis_points INTEGER, evidence_gain_basis_points INTEGER,
        reversibility_basis_points INTEGER, ordinal INTEGER, content_hash TEXT
    );

    IF p_fault_point = 'after_candidate_before_child' THEN
        RAISE EXCEPTION 'INJECTED_PLANNER_CRASH_AFTER_CANDIDATE';
    END IF;

    INSERT INTO public.candidate_action_targets(action_id, target_ref, ordinal)
    SELECT item.action_id, target.value, target.ordinal - 1
    FROM jsonb_to_recordset(COALESCE(p_candidates, '[]'::jsonb))
         AS item(action_id TEXT, target_refs TEXT[])
    CROSS JOIN LATERAL unnest(COALESCE(item.target_refs, '{}'))
         WITH ORDINALITY AS target(value, ordinal);

    INSERT INTO public.candidate_action_capabilities(action_id, capability, ordinal)
    SELECT item.action_id, capability.value, capability.ordinal - 1
    FROM jsonb_to_recordset(COALESCE(p_candidates, '[]'::jsonb))
         AS item(action_id TEXT, required_capabilities TEXT[])
    CROSS JOIN LATERAL unnest(COALESCE(item.required_capabilities, '{}'))
         WITH ORDINALITY AS capability(value, ordinal);

    INSERT INTO public.candidate_action_preconditions(action_id, precondition, ordinal)
    SELECT item.action_id, precondition.value, precondition.ordinal - 1
    FROM jsonb_to_recordset(COALESCE(p_candidates, '[]'::jsonb))
         AS item(action_id TEXT, preconditions TEXT[])
    CROSS JOIN LATERAL unnest(COALESCE(item.preconditions, '{}'))
         WITH ORDINALITY AS precondition(value, ordinal);

    INSERT INTO public.candidate_action_expected_outputs(action_id, expected_output, ordinal)
    SELECT item.action_id, output.value, output.ordinal - 1
    FROM jsonb_to_recordset(COALESCE(p_candidates, '[]'::jsonb))
         AS item(action_id TEXT, expected_outputs TEXT[])
    CROSS JOIN LATERAL unnest(COALESCE(item.expected_outputs, '{}'))
         WITH ORDINALITY AS output(value, ordinal);

    INSERT INTO public.candidate_action_resource_estimates(
        action_id, dimension, amount, currency, estimator_version
    )
    SELECT item.action_id, resource.key, (resource.value)::bigint,
           NULLIF(item.estimated_resources->>'currency', ''),
           item.estimated_resources->>'estimator_version'
    FROM jsonb_to_recordset(COALESCE(p_candidates, '[]'::jsonb))
         AS item(action_id TEXT, estimated_resources JSONB)
    CROSS JOIN LATERAL jsonb_each_text(item.estimated_resources->'amounts') AS resource(key, value);

    IF p_fault_point = 'after_child_before_current' THEN
        RAISE EXCEPTION 'INJECTED_PLANNER_CRASH_AFTER_CHILD';
    END IF;

    INSERT INTO public.current_planning_runs(
        situation_id, planning_run_id, situation_version,
        analysis_context_hash, diagnosis_id, diagnosis_input_hash,
        registry_version, planner_rule_version, input_hash
    ) VALUES (
        p_situation_id, inserted_run, p_situation_version,
        p_analysis_context_hash, p_diagnosis_id, p_diagnosis_input_hash,
        p_registry_version, p_planner_rule_version, p_input_hash
    )
    ON CONFLICT (situation_id) DO UPDATE SET
        planning_run_id = EXCLUDED.planning_run_id,
        situation_version = EXCLUDED.situation_version,
        analysis_context_hash = EXCLUDED.analysis_context_hash,
        diagnosis_id = EXCLUDED.diagnosis_id,
        diagnosis_input_hash = EXCLUDED.diagnosis_input_hash,
        registry_version = EXCLUDED.registry_version,
        planner_rule_version = EXCLUDED.planner_rule_version,
        input_hash = EXCLUDED.input_hash,
        updated_at = now()
    WHERE public.current_planning_runs.situation_version <= EXCLUDED.situation_version;

    IF p_fault_point = 'after_current_before_event' THEN
        RAISE EXCEPTION 'INJECTED_PLANNER_CRASH_AFTER_CURRENT';
    END IF;

    event_id := 'evt-' || gen_random_uuid()::text;
    event_payload := jsonb_build_object(
        'planning_run_id', inserted_run,
        'situation_id', p_situation_id,
        'situation_version', p_situation_version,
        'analysis_context_id', p_analysis_context_id,
        'diagnosis_id', p_diagnosis_id,
        'registry_version', p_registry_version,
        'planner_rule_version', p_planner_rule_version,
        'input_hash', p_input_hash,
        'candidate_count', p_candidate_count,
        'candidate_action_ids',
            COALESCE((SELECT jsonb_agg(item.action_id ORDER BY item.ordinal)
                      FROM jsonb_to_recordset(COALESCE(p_candidates, '[]'::jsonb))
                           AS item(action_id TEXT, ordinal INTEGER)), '[]'::jsonb)
    );
    INSERT INTO public.event_log(
        event_id, event_type, schema_version, producer_type, producer_id,
        project_id, partition_key, command_id, correlation_id,
        causation_id, task_id, payload
    ) VALUES (
        event_id, 'action.candidates_planned', '1.0',
        'action_planner', p_actor_id, p_project_id, p_project_id,
        p_command_id, p_command_id, situation_row.trigger_event_id,
        situation_row.task_id, event_payload
    ) RETURNING sequence INTO event_sequence;

    IF p_fault_point = 'after_event_before_outbox' THEN
        RAISE EXCEPTION 'INJECTED_PLANNER_CRASH_AFTER_EVENT';
    END IF;

    INSERT INTO public.outbox_messages(
        message_id, event_id, topic, partition_key, sequence, payload
    ) VALUES (
        'msg-' || gen_random_uuid()::text, event_id,
        'hermes.runtime.events', p_project_id, event_sequence, event_payload
    );

    IF p_fault_point = 'after_outbox_before_receipt' THEN
        RAISE EXCEPTION 'INJECTED_PLANNER_CRASH_AFTER_OUTBOX';
    END IF;

    RETURN jsonb_build_object(
        'planning_run_id', inserted_run,
        'candidate_count', p_candidate_count,
        'event_id', event_id,
        'deduplicated', false
    );
END;
$$;

ALTER TABLE public.action_registry_versions OWNER TO hermes_planner_owner;
ALTER TABLE public.planning_runs OWNER TO hermes_planner_owner;
ALTER TABLE public.candidate_actions OWNER TO hermes_planner_owner;
ALTER TABLE public.candidate_action_targets OWNER TO hermes_planner_owner;
ALTER TABLE public.candidate_action_capabilities OWNER TO hermes_planner_owner;
ALTER TABLE public.candidate_action_preconditions OWNER TO hermes_planner_owner;
ALTER TABLE public.candidate_action_expected_outputs OWNER TO hermes_planner_owner;
ALTER TABLE public.candidate_action_resource_estimates OWNER TO hermes_planner_owner;
ALTER TABLE public.current_planning_runs OWNER TO hermes_planner_owner;
ALTER FUNCTION public.hermes_reject_planning_history_change() OWNER TO hermes_planner_owner;
ALTER FUNCTION public.hermes_apply_planning_run(
    TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,
    INTEGER,TEXT,JSONB,TEXT,TEXT,TEXT,TEXT
) OWNER TO hermes_planner_owner;

GRANT SELECT ON public.projects, public.tasks, public.artifacts, public.evidence,
    public.verification_results, public.verification_check_results,
    public.verification_evidence, public.event_log, public.command_receipts,
    public.analysis_contexts, public.situations, public.situation_versions,
    public.diagnoses, public.diagnosis_hypotheses,
    public.diagnosis_evidence_requests, public.current_diagnoses,
    public.resource_accounts, public.resource_balances
    TO hermes_planner_owner;
GRANT UPDATE ON public.situations TO hermes_planner_owner;
GRANT INSERT ON public.planning_runs, public.candidate_actions,
    public.candidate_action_targets, public.candidate_action_capabilities,
    public.candidate_action_preconditions,
    public.candidate_action_expected_outputs,
    public.candidate_action_resource_estimates TO hermes_planner_owner;
GRANT SELECT, INSERT ON public.action_registry_versions TO hermes_planner_owner;
GRANT SELECT, INSERT, UPDATE ON public.current_planning_runs TO hermes_planner_owner;
GRANT SELECT, INSERT ON public.event_log, public.outbox_messages TO hermes_planner_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_planner_owner;

REVOKE ALL ON public.action_registry_versions, public.planning_runs,
    public.candidate_actions, public.candidate_action_targets,
    public.candidate_action_capabilities,
    public.candidate_action_preconditions,
    public.candidate_action_expected_outputs,
    public.candidate_action_resource_estimates,
    public.current_planning_runs FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_reject_planning_history_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_apply_planning_run(
    TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,
    INTEGER,TEXT,JSONB,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC;

GRANT SELECT ON public.action_registry_versions, public.planning_runs,
    public.candidate_actions, public.candidate_action_targets,
    public.candidate_action_capabilities,
    public.candidate_action_preconditions,
    public.candidate_action_expected_outputs,
    public.candidate_action_resource_estimates,
    public.current_planning_runs
    TO hermes_planner_runtime, hermes_read_only_runtime;
GRANT SELECT ON public.projects, public.tasks, public.artifacts, public.evidence,
    public.verification_results, public.verification_check_results,
    public.verification_evidence, public.event_log, public.command_receipts,
    public.analysis_contexts, public.situations, public.situation_versions,
    public.diagnoses, public.diagnosis_hypotheses,
    public.diagnosis_evidence_requests, public.current_diagnoses,
    public.resource_accounts, public.resource_balances
    TO hermes_planner_runtime;
GRANT SELECT, INSERT, UPDATE ON public.command_receipts TO hermes_planner_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_apply_planning_run(
    TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,
    INTEGER,TEXT,JSONB,TEXT,TEXT,TEXT,TEXT
) TO hermes_planner_runtime;

REVOKE INSERT, UPDATE, DELETE ON public.action_registry_versions,
    public.planning_runs, public.candidate_actions,
    public.candidate_action_targets, public.candidate_action_capabilities,
    public.candidate_action_preconditions,
    public.candidate_action_expected_outputs,
    public.candidate_action_resource_estimates, public.current_planning_runs
FROM hermes_planner_runtime, hermes_worker_runtime, hermes_verifier_runtime,
     hermes_situation_runtime, hermes_diagnosis_runtime,
     hermes_accounting_runtime, hermes_control_plane_runtime,
     hermes_read_only_runtime;
REVOKE INSERT, UPDATE, DELETE ON public.situations, public.diagnoses,
    public.projects, public.tasks, public.artifacts, public.evidence,
    public.resource_accounts, public.resource_balances,
    public.resource_reservations
FROM hermes_planner_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_planner_runtime;

COMMENT ON TABLE public.planning_runs IS
'Immutable PlanningRun records that enumerate candidates without selecting, authorizing or reserving resources.';
COMMENT ON TABLE public.candidate_actions IS
'Immutable CandidateAction records; not selected, allowed, queued, leased or executed.';
COMMENT ON TABLE public.candidate_action_resource_estimates IS
'Deterministic resource estimates only; not ResourceReservations.';
