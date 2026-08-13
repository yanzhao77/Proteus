-- P1 Slice 6: Action Selection authority, immutable DecisionRecord and atomic reservations.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_selection_owner') THEN
        CREATE ROLE hermes_selection_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_selection_runtime') THEN
        CREATE ROLE hermes_selection_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.selection_weight_profiles (
    weight_profile_id TEXT PRIMARY KEY,
    normalizer_version TEXT NOT NULL,
    conflict_rule_version TEXT NOT NULL,
    weights JSONB NOT NULL,
    conservative_defaults JSONB NOT NULL,
    max_parallel_selected_actions INTEGER NOT NULL CHECK (max_parallel_selected_actions > 0),
    content_hash TEXT NOT NULL CHECK (content_hash LIKE 'sha256:%'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO public.selection_weight_profiles(
    weight_profile_id, normalizer_version, conflict_rule_version, weights,
    conservative_defaults, max_parallel_selected_actions, content_hash
) VALUES (
    'selection-weight-profile/1.0', 'selection-normalizer/1.0',
    'selection-conflict-rules/1.0',
    '{"expected_progress":1800,"confidence":1200,"evidence_gain":1600,"reversibility":900,"risk":-1600,"cost":-900,"time":-600,"historical_success":400}'::jsonb,
    '{"historical_success":{"basis_points":3500,"reason":"DEFAULT_NO_HISTORY"}}'::jsonb,
    2,
    'sha256:' || encode(public.digest(convert_to(
        'selection-weight-profile/1.0|selection-normalizer/1.0|selection-conflict-rules/1.0',
        'UTF8'), 'sha256'), 'hex')
) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.selection_heads (
    planning_run_id TEXT PRIMARY KEY REFERENCES public.planning_runs(planning_run_id),
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    situation_id TEXT NOT NULL REFERENCES public.situations(situation_id),
    current_decision_id TEXT,
    selection_version BIGINT NOT NULL CHECK (selection_version >= 0),
    active_reservation_count INTEGER NOT NULL DEFAULT 0 CHECK (active_reservation_count >= 0),
    input_snapshot_hash TEXT CHECK (input_snapshot_hash IS NULL OR input_snapshot_hash LIKE 'sha256:%'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.decision_records (
    decision_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    situation_id TEXT NOT NULL REFERENCES public.situations(situation_id),
    situation_version BIGINT NOT NULL CHECK (situation_version >= 1),
    analysis_context_id TEXT NOT NULL REFERENCES public.analysis_contexts(analysis_context_id),
    analysis_context_hash TEXT NOT NULL CHECK (analysis_context_hash LIKE 'sha256:%'),
    input_observed_at_sequence BIGINT NOT NULL CHECK (input_observed_at_sequence > 0),
    diagnosis_id TEXT,
    diagnosis_input_hash TEXT,
    planning_run_id TEXT NOT NULL REFERENCES public.planning_runs(planning_run_id),
    planning_input_hash TEXT NOT NULL CHECK (planning_input_hash LIKE 'sha256:%'),
    selection_version BIGINT NOT NULL CHECK (selection_version >= 1),
    input_snapshot_hash TEXT NOT NULL CHECK (input_snapshot_hash LIKE 'sha256:%'),
    candidate_refs JSONB NOT NULL,
    eligible_action_ids TEXT[] NOT NULL DEFAULT '{}',
    selected_action_ids TEXT[] NOT NULL DEFAULT '{}',
    policy_refs JSONB NOT NULL,
    risk_refs JSONB NOT NULL,
    resource_account_snapshots JSONB NOT NULL,
    score_refs JSONB NOT NULL,
    reservation_refs JSONB NOT NULL,
    weight_profile_id TEXT NOT NULL REFERENCES public.selection_weight_profiles(weight_profile_id),
    normalizer_version TEXT NOT NULL,
    conflict_rule_version TEXT NOT NULL,
    max_parallel_selected_actions INTEGER NOT NULL,
    decision_reason_codes TEXT[] NOT NULL DEFAULT '{}',
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (planning_run_id, selection_version),
    UNIQUE (planning_run_id, input_snapshot_hash)
);

CREATE TABLE IF NOT EXISTS public.decision_candidate_dispositions (
    decision_id TEXT NOT NULL REFERENCES public.decision_records(decision_id),
    action_id TEXT NOT NULL REFERENCES public.candidate_actions(action_id),
    action_content_hash TEXT NOT NULL CHECK (action_content_hash LIKE 'sha256:%'),
    disposition TEXT NOT NULL CHECK (disposition IN ('FILTERED','ELIGIBLE_NOT_SELECTED','SELECTED')),
    reason_codes TEXT[] NOT NULL,
    policy_decision_id TEXT REFERENCES public.policy_decisions(policy_decision_id),
    risk_assessment_id TEXT REFERENCES public.risk_assessments(risk_assessment_id),
    resource_account_id TEXT REFERENCES public.resource_accounts(account_id),
    reservation_required BOOLEAN NOT NULL,
    reservation_id TEXT,
    derived_read_write JSONB NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (decision_id, action_id)
);

CREATE TABLE IF NOT EXISTS public.action_scores (
    score_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES public.decision_records(decision_id),
    action_id TEXT NOT NULL REFERENCES public.candidate_actions(action_id),
    action_content_hash TEXT NOT NULL CHECK (action_content_hash LIKE 'sha256:%'),
    final_score_basis_points INTEGER NOT NULL CHECK (final_score_basis_points BETWEEN 0 AND 10000),
    weight_profile_id TEXT NOT NULL REFERENCES public.selection_weight_profiles(weight_profile_id),
    normalizer_version TEXT NOT NULL,
    score_input_hash TEXT NOT NULL CHECK (score_input_hash LIKE 'sha256:%'),
    reason_codes TEXT[] NOT NULL DEFAULT '{}',
    default_sources JSONB NOT NULL,
    weights JSONB NOT NULL,
    contributions JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (decision_id, action_id)
);

CREATE TABLE IF NOT EXISTS public.action_score_dimensions (
    score_id TEXT NOT NULL REFERENCES public.action_scores(score_id),
    dimension_name TEXT NOT NULL CHECK (dimension_name IN (
        'expected_progress','confidence','evidence_gain','reversibility',
        'risk','cost','time','historical_success'
    )),
    raw_basis_points INTEGER NOT NULL CHECK (raw_basis_points BETWEEN 0 AND 10000),
    normalized_basis_points INTEGER NOT NULL CHECK (normalized_basis_points BETWEEN 0 AND 10000),
    contribution_basis_points INTEGER NOT NULL,
    default_source TEXT,
    PRIMARY KEY (score_id, dimension_name)
);

CREATE TABLE IF NOT EXISTS public.selected_action_refs (
    decision_id TEXT NOT NULL REFERENCES public.decision_records(decision_id),
    action_id TEXT NOT NULL REFERENCES public.candidate_actions(action_id),
    selection_rank INTEGER NOT NULL CHECK (selection_rank >= 0),
    selected_intent JSONB NOT NULL,
    PRIMARY KEY (decision_id, action_id)
);

CREATE TABLE IF NOT EXISTS public.decision_reservation_mappings (
    decision_id TEXT NOT NULL REFERENCES public.decision_records(decision_id),
    action_id TEXT NOT NULL REFERENCES public.candidate_actions(action_id),
    reservation_id TEXT NOT NULL REFERENCES public.resource_reservations(reservation_id),
    account_id TEXT NOT NULL REFERENCES public.resource_accounts(account_id),
    resource_amounts JSONB NOT NULL,
    account_version BIGINT NOT NULL CHECK (account_version > 0),
    PRIMARY KEY (decision_id, action_id),
    UNIQUE (reservation_id)
);

CREATE OR REPLACE FUNCTION public.hermes_reject_selection_history_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'selection_weight_profiles','decision_records',
        'decision_candidate_dispositions','action_scores',
        'action_score_dimensions','selected_action_refs',
        'decision_reservation_mappings'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS selection_immutable ON public.%I', table_name);
        EXECUTE format(
            'CREATE TRIGGER selection_immutable BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_selection_history_change()',
            table_name
        );
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_apply_selection_decision(
    p_decision JSONB,
    p_candidate_dispositions JSONB,
    p_scores JSONB,
    p_score_dimensions JSONB,
    p_selected_refs JSONB,
    p_reservation_mappings JSONB,
    p_account_snapshots JSONB,
    p_project_id TEXT,
    p_planning_run_id TEXT,
    p_expected_situation_version BIGINT,
    p_expected_selection_version BIGINT,
    p_weight_profile_id TEXT,
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
    situation_row public.situations%ROWTYPE;
    context_row public.analysis_contexts%ROWTYPE;
    head_row public.selection_heads%ROWTYPE;
    existing_decision public.decision_records%ROWTYPE;
    v_decision_id TEXT := p_decision->>'decision_id';
    v_input_snapshot_hash TEXT := p_decision->>'input_snapshot_hash';
    v_selection_version BIGINT := (p_decision->>'selection_version')::BIGINT;
    candidate_item RECORD;
    account_item RECORD;
    reservation_item RECORD;
    dimension_item RECORD;
    selected_item RECORD;
    score_item RECORD;
    action_row public.candidate_actions%ROWTYPE;
    policy_row public.policy_decisions%ROWTYPE;
    risk_row public.risk_assessments%ROWTYPE;
    context_policy public.policy_evaluation_contexts%ROWTYPE;
    context_risk public.policy_evaluation_contexts%ROWTYPE;
    account_row public.resource_accounts%ROWTYPE;
    balance_row RECORD;
    available_amount BIGINT;
    reserve_command_id TEXT;
    reserve_request_hash TEXT;
    budget_event_id TEXT;
    budget_event_sequence BIGINT;
    budget_payload JSONB;
    decision_event_id TEXT;
    decision_event_sequence BIGINT;
    decision_payload JSONB;
    reservation_count INTEGER := 0;
    selected_count INTEGER := 0;
    nonzero_selected_without_reservation INTEGER := 0;
    dedup_reservation_ids TEXT[];
BEGIN
    IF p_actor_type <> 'action_selection' OR NULLIF(btrim(p_actor_id), '') IS NULL THEN
        RAISE EXCEPTION 'SELECTION_AUTHORITY_REQUIRED';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.command_receipts c
        WHERE c.command_id = p_command_id AND c.project_id = p_project_id
          AND c.command_type = 'selection.select_actions'
          AND c.status = 'PROCESSING'
    ) THEN RAISE EXCEPTION 'SELECTION_COMMAND_SEMANTICS_MISMATCH'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.selection_weight_profiles
        WHERE weight_profile_id = p_weight_profile_id
          AND normalizer_version = p_decision->>'normalizer_version'
          AND conflict_rule_version = p_decision->>'conflict_rule_version'
    ) THEN RAISE EXCEPTION 'SELECTION_WEIGHT_PROFILE_UNSUPPORTED'; END IF;
    IF p_fault_point = 'after_receipt_placeholder' THEN
        RAISE EXCEPTION 'INJECTED_SELECTION_CRASH_AFTER_RECEIPT';
    END IF;

    SELECT * INTO run_row FROM public.planning_runs
    WHERE planning_run_id = p_planning_run_id AND project_id = p_project_id
    FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'SELECTION_PLANNING_RUN_NOT_CURRENT'; END IF;
    SELECT * INTO current_run FROM public.current_planning_runs
    WHERE situation_id = run_row.situation_id;
    IF NOT FOUND OR current_run.planning_run_id <> p_planning_run_id THEN
        RAISE EXCEPTION 'SELECTION_PLANNING_RUN_NOT_CURRENT';
    END IF;
    SELECT * INTO situation_row FROM public.situations
    WHERE situation_id = run_row.situation_id AND project_id = p_project_id
    FOR UPDATE;
    IF NOT FOUND OR situation_row.status <> 'OPEN'
       OR situation_row.version <> p_expected_situation_version
       OR situation_row.version <> run_row.situation_version THEN
        RAISE EXCEPTION 'SELECTION_CONTEXT_STALE';
    END IF;
    SELECT * INTO context_row FROM public.analysis_contexts
    WHERE analysis_context_id = run_row.analysis_context_id
      AND context_hash = run_row.analysis_context_hash;
    IF NOT FOUND THEN RAISE EXCEPTION 'SELECTION_CONTEXT_STALE'; END IF;

    INSERT INTO public.selection_heads(
        planning_run_id, project_id, situation_id, selection_version
    ) VALUES (p_planning_run_id, p_project_id, run_row.situation_id, 0)
    ON CONFLICT DO NOTHING;
    SELECT * INTO head_row FROM public.selection_heads
    WHERE planning_run_id = p_planning_run_id FOR UPDATE;
    SELECT * INTO existing_decision FROM public.decision_records
    WHERE planning_run_id = p_planning_run_id AND input_snapshot_hash = v_input_snapshot_hash;
    IF FOUND THEN
        RETURN jsonb_build_object(
            'decision_id', existing_decision.decision_id,
            'selection_version', existing_decision.selection_version,
            'input_snapshot_hash', existing_decision.input_snapshot_hash,
            'event_id', NULL,
            'deduplicated', true
        );
    END IF;
    IF head_row.selection_version <> p_expected_selection_version THEN
        RAISE EXCEPTION 'SELECTION_VERSION_CONFLICT';
    END IF;
    IF head_row.active_reservation_count > 0
       AND head_row.input_snapshot_hash IS DISTINCT FROM v_input_snapshot_hash THEN
        RAISE EXCEPTION 'ACTIVE_DECISION_REQUIRES_RELEASE';
    END IF;
    IF v_selection_version <> p_expected_selection_version + 1 THEN
        RAISE EXCEPTION 'SELECTION_VERSION_CONFLICT';
    END IF;

    FOR candidate_item IN
        SELECT * FROM jsonb_to_recordset(COALESCE(p_candidate_dispositions, '[]'::jsonb))
        AS item(action_id TEXT, action_content_hash TEXT, disposition TEXT,
                reason_codes TEXT[], policy_decision_id TEXT, risk_assessment_id TEXT,
                resource_account_id TEXT, reservation_required BOOLEAN,
                reservation_id TEXT, derived_read_write JSONB, ordinal INTEGER)
    LOOP
        SELECT * INTO action_row FROM public.candidate_actions
        WHERE action_id = candidate_item.action_id
          AND planning_run_id = p_planning_run_id
          AND project_id = p_project_id;
        IF NOT FOUND THEN RAISE EXCEPTION 'SELECTION_ACTION_NOT_FOUND'; END IF;
        IF action_row.content_hash <> candidate_item.action_content_hash THEN
            RAISE EXCEPTION 'SELECTION_ACTION_HASH_MISMATCH';
        END IF;
        IF action_row.situation_version <> run_row.situation_version
           OR action_row.analysis_context_hash <> run_row.analysis_context_hash
           OR action_row.registry_version <> run_row.registry_version
           OR action_row.diagnosis_id IS DISTINCT FROM run_row.diagnosis_id
           OR action_row.diagnosis_input_hash IS DISTINCT FROM run_row.diagnosis_input_hash THEN
            RAISE EXCEPTION 'SELECTION_CONTEXT_STALE';
        END IF;
        IF candidate_item.policy_decision_id IS NOT NULL THEN
            SELECT * INTO policy_row FROM public.policy_decisions
            WHERE policy_decision_id = candidate_item.policy_decision_id;
            SELECT * INTO context_policy FROM public.policy_evaluation_contexts
            WHERE evaluation_context_id = policy_row.evaluation_context_id;
            IF NOT FOUND OR policy_row.action_id <> action_row.action_id
               OR policy_row.planning_run_id <> p_planning_run_id
               OR policy_row.action_content_hash <> action_row.content_hash THEN
                RAISE EXCEPTION 'POLICY_DECISION_STALE';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM public.current_policy_decisions c
                WHERE c.action_id = action_row.action_id
                  AND c.policy_decision_id = policy_row.policy_decision_id
                  AND c.action_content_hash = action_row.content_hash
                  AND c.planning_run_id = p_planning_run_id
            ) THEN RAISE EXCEPTION 'POLICY_DECISION_STALE'; END IF;
        ELSIF candidate_item.disposition <> 'FILTERED' THEN
            RAISE EXCEPTION 'POLICY_DECISION_MISSING';
        END IF;
        IF candidate_item.risk_assessment_id IS NOT NULL THEN
            SELECT * INTO risk_row FROM public.risk_assessments
            WHERE risk_assessment_id = candidate_item.risk_assessment_id;
            SELECT * INTO context_risk FROM public.policy_evaluation_contexts
            WHERE evaluation_context_id = risk_row.evaluation_context_id;
            IF NOT FOUND OR risk_row.action_id <> action_row.action_id
               OR risk_row.planning_run_id <> p_planning_run_id
               OR risk_row.action_content_hash <> action_row.content_hash
               OR context_risk.context_hash <> context_policy.context_hash THEN
                RAISE EXCEPTION 'RISK_ASSESSMENT_STALE';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM public.current_risk_assessments c
                WHERE c.action_id = action_row.action_id
                  AND c.risk_assessment_id = risk_row.risk_assessment_id
                  AND c.action_content_hash = action_row.content_hash
                  AND c.planning_run_id = p_planning_run_id
            ) THEN RAISE EXCEPTION 'RISK_ASSESSMENT_STALE'; END IF;
        ELSIF candidate_item.disposition <> 'FILTERED' THEN
            RAISE EXCEPTION 'RISK_ASSESSMENT_MISSING';
        END IF;
        IF candidate_item.disposition = 'SELECTED' THEN
            selected_count := selected_count + 1;
            IF candidate_item.reservation_required AND candidate_item.reservation_id IS NULL THEN
                nonzero_selected_without_reservation := nonzero_selected_without_reservation + 1;
            END IF;
        END IF;
    END LOOP;

    IF p_fault_point = 'after_score_disposition' THEN
        RAISE EXCEPTION 'INJECTED_SELECTION_CRASH_AFTER_SCORE_DISPOSITION';
    END IF;

    SELECT array_agg(reservation_id ORDER BY reservation_id), count(*)
    INTO dedup_reservation_ids, reservation_count
    FROM jsonb_to_recordset(COALESCE(p_reservation_mappings, '[]'::jsonb))
         AS item(reservation_id TEXT);
    reservation_count := 0;

    FOR account_item IN
        SELECT * FROM jsonb_to_recordset(COALESCE(p_account_snapshots, '[]'::jsonb))
        AS item(account_id TEXT, expected_account_version BIGINT)
        ORDER BY account_id
    LOOP
        SELECT * INTO account_row FROM public.resource_accounts
        WHERE account_id = account_item.account_id AND project_id = p_project_id
        FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'RESOURCE_ACCOUNT_NOT_FOUND'; END IF;
        IF account_row.version <> account_item.expected_account_version THEN
            RAISE EXCEPTION 'BUDGET_ACCOUNT_VERSION_CONFLICT';
        END IF;
    END LOOP;

    FOR reservation_item IN
        SELECT * FROM jsonb_to_recordset(COALESCE(p_reservation_mappings, '[]'::jsonb))
        AS item(action_id TEXT, reservation_id TEXT, account_id TEXT, resource_amounts JSONB,
                expected_account_version BIGINT, currency TEXT)
        ORDER BY account_id, action_id
    LOOP
        SELECT * INTO action_row FROM public.candidate_actions
        WHERE action_id = reservation_item.action_id
          AND planning_run_id = p_planning_run_id
          AND project_id = p_project_id;
        IF NOT FOUND THEN RAISE EXCEPTION 'SELECTION_ACTION_NOT_FOUND'; END IF;
        IF action_row.estimated_resources->'amounts' <> reservation_item.resource_amounts THEN
            RAISE EXCEPTION 'SELECTION_RESERVATION_AMOUNT_MISMATCH';
        END IF;
        SELECT * INTO account_row FROM public.resource_accounts
        WHERE account_id = reservation_item.account_id
          AND project_id = p_project_id FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'RESOURCE_ACCOUNT_NOT_FOUND'; END IF;
        IF account_row.version < reservation_item.expected_account_version THEN
            RAISE EXCEPTION 'BUDGET_ACCOUNT_VERSION_CONFLICT';
        END IF;
        IF account_row.threshold_status = 'HARD_STOP' THEN
            RAISE EXCEPTION 'BUDGET_HARD_STOP';
        END IF;
        IF account_row.currency IS DISTINCT FROM NULLIF(reservation_item.currency, '') THEN
            RAISE EXCEPTION 'BUDGET_CURRENCY_MISMATCH';
        END IF;
        IF NOT (
            (account_row.scope_type = 'project' AND account_row.scope_id = p_project_id)
            OR (account_row.scope_type = 'action' AND account_row.scope_id = action_row.action_id)
            OR (account_row.scope_type = 'task' AND account_row.scope_id = ANY(action_row.target_refs))
        ) THEN RAISE EXCEPTION 'BUDGET_ACCOUNT_SCOPE_MISMATCH'; END IF;
        FOR dimension_item IN SELECT key, value FROM jsonb_each(reservation_item.resource_amounts) LOOP
            IF dimension_item.key NOT IN (
                'llm_tokens','llm_cost_minor','agent_runs','retry_count',
                'execution_time_ms','cpu_time_ms','gpu_time_ms',
                'docker_runtime_ms','browser_runtime_ms','external_api_calls',
                'storage_bytes','human_attention_requests'
            ) THEN RAISE EXCEPTION 'BUDGET_ESTIMATE_INVALID'; END IF;
            IF jsonb_typeof(dimension_item.value) <> 'number'
               OR dimension_item.value::text !~ '^[0-9]+$' THEN
                RAISE EXCEPTION 'BUDGET_ESTIMATE_INVALID';
            END IF;
            SELECT * INTO balance_row FROM public.resource_balances
            WHERE account_id = account_row.account_id
              AND dimension = dimension_item.key FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'BUDGET_INFEASIBLE'; END IF;
            available_amount := balance_row.limit_amount
                                - balance_row.consumed_amount
                                - balance_row.reserved_amount;
            IF (dimension_item.value::text)::BIGINT > available_amount THEN
                RAISE EXCEPTION 'BUDGET_INFEASIBLE';
            END IF;
        END LOOP;
        reserve_command_id := 'cmd-reserve-' || encode(public.digest(convert_to(
            v_decision_id || '|' || reservation_item.action_id || '|' || reservation_item.reservation_id,
            'UTF8'), 'sha256'), 'hex');
        reserve_request_hash := encode(public.digest(convert_to(
            jsonb_build_object(
                'command_type', 'resource.reserve',
                'selection_command_id', p_command_id,
                'decision_id', v_decision_id,
                'action_id', reservation_item.action_id,
                'account_id', account_row.account_id,
                'reservation_id', reservation_item.reservation_id,
                'resource_amounts', reservation_item.resource_amounts,
                'expected_account_version', reservation_item.expected_account_version
            )::text, 'UTF8'), 'sha256'), 'hex');
        INSERT INTO public.command_receipts(
            command_id, project_id, command_type, idempotency_key,
            request_hash, status, result
        ) VALUES (
            reserve_command_id, p_project_id, 'resource.reserve',
            'selection:' || v_decision_id || ':' || reservation_item.action_id,
            reserve_request_hash, 'PROCESSING', '{}'::jsonb
        );

        INSERT INTO public.resource_reservations(
            reservation_id, account_id, project_id, owner_type, owner_id,
            preparation_id, currency, status, account_version, command_id
        ) VALUES (
            reservation_item.reservation_id, account_row.account_id, p_project_id,
            'decision', v_decision_id, NULL, NULLIF(reservation_item.currency, ''),
            'ACTIVE', account_row.version + 1, reserve_command_id
        );
        FOR dimension_item IN SELECT key, value FROM jsonb_each(reservation_item.resource_amounts) LOOP
            INSERT INTO public.resource_reservation_amounts(reservation_id, dimension, amount)
            VALUES (reservation_item.reservation_id, dimension_item.key,
                    (dimension_item.value::text)::BIGINT);
            UPDATE public.resource_balances
            SET reserved_amount = reserved_amount + (dimension_item.value::text)::BIGINT
            WHERE account_id = account_row.account_id
              AND dimension = dimension_item.key;
        END LOOP;
        UPDATE public.resource_accounts
        SET version = account_row.version + 1,
            threshold_status = public.hermes_accounting_status(account_row.account_id, false),
            updated_at = now()
        WHERE account_id = account_row.account_id;
        UPDATE public.project_budget_facts SET valid = false, invalidated_at = now()
        WHERE resource_account_id = account_row.account_id AND valid;
        budget_payload := jsonb_build_object(
            'reservation_id', reservation_item.reservation_id,
            'decision_id', v_decision_id,
            'action_id', reservation_item.action_id,
            'account_id', account_row.account_id,
            'entity_version', account_row.version + 1,
            'amounts', reservation_item.resource_amounts,
            'selection_command_id', p_command_id
        );
        budget_event_id := 'evt-' || gen_random_uuid()::text;
        INSERT INTO public.event_log(
            event_id, event_type, schema_version, producer_type, producer_id,
            project_id, partition_key, command_id, correlation_id,
            causation_id, payload
        ) VALUES (
            budget_event_id, 'budget.reserved', '1.0',
            'action_selection', p_actor_id, p_project_id, p_project_id,
            reserve_command_id, p_command_id, reservation_item.action_id, budget_payload
        ) RETURNING sequence INTO budget_event_sequence;
        INSERT INTO public.outbox_messages(message_id, event_id, topic, partition_key, sequence, payload)
        VALUES ('msg-' || gen_random_uuid()::text, budget_event_id,
                'hermes.runtime.events', p_project_id, budget_event_sequence, budget_payload);
        UPDATE public.command_receipts
        SET status = 'APPLIED',
            result = jsonb_build_object(
                'command_id', reserve_command_id,
                'status', 'APPLIED',
                'result_code', 'RESOURCE_RESERVED',
                'target_version', account_row.version + 1,
                'event_ids', jsonb_build_array(budget_event_id),
                'response', jsonb_build_object(
                    'reservation_id', reservation_item.reservation_id,
                    'account_id', account_row.account_id,
                    'account_version', account_row.version + 1,
                    'threshold_status', public.hermes_accounting_status(account_row.account_id, false),
                    'selection_command_id', p_command_id
                )
            ),
            completed_at = now()
        WHERE command_id = reserve_command_id AND status = 'PROCESSING';
        reservation_count := reservation_count + 1;
        IF p_fault_point = 'after_first_reservation_before_second' AND reservation_count = 1 THEN
            RAISE EXCEPTION 'INJECTED_SELECTION_CRASH_AFTER_FIRST_RESERVATION';
        END IF;
    END LOOP;
    IF p_fault_point = 'after_all_reservations_before_decision' THEN
        RAISE EXCEPTION 'INJECTED_SELECTION_CRASH_AFTER_ALL_RESERVATIONS';
    END IF;
    IF nonzero_selected_without_reservation > 0 THEN
        RAISE EXCEPTION 'SELECTION_SELECTED_RESERVATION_REQUIRED';
    END IF;

    INSERT INTO public.decision_records(
        decision_id, project_id, situation_id, situation_version,
        analysis_context_id, analysis_context_hash, input_observed_at_sequence,
        diagnosis_id, diagnosis_input_hash, planning_run_id, planning_input_hash,
        selection_version, input_snapshot_hash, candidate_refs,
        eligible_action_ids, selected_action_ids, policy_refs, risk_refs,
        resource_account_snapshots, score_refs, reservation_refs,
        weight_profile_id, normalizer_version, conflict_rule_version,
        max_parallel_selected_actions, decision_reason_codes, command_id,
        actor_type, actor_id
    ) VALUES (
        v_decision_id, p_project_id, run_row.situation_id, run_row.situation_version,
        run_row.analysis_context_id, run_row.analysis_context_hash,
        context_row.observed_at_sequence, run_row.diagnosis_id,
        run_row.diagnosis_input_hash, p_planning_run_id, run_row.input_hash,
        v_selection_version, v_input_snapshot_hash, p_decision->'candidate_refs',
        ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_decision->'eligible_action_ids','[]'::jsonb))),
        ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_decision->'selected_action_ids','[]'::jsonb))),
        p_decision->'policy_refs', p_decision->'risk_refs',
        p_account_snapshots, p_decision->'score_refs',
        p_decision->'reservation_refs', p_weight_profile_id,
        p_decision->>'normalizer_version', p_decision->>'conflict_rule_version',
        (p_decision->>'max_parallel_selected_actions')::INTEGER,
        ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_decision->'decision_reason_codes','[]'::jsonb))),
        p_command_id, p_actor_type, p_actor_id
    );

    INSERT INTO public.decision_candidate_dispositions(
        decision_id, action_id, action_content_hash, disposition, reason_codes,
        policy_decision_id, risk_assessment_id, resource_account_id,
        reservation_required, reservation_id, derived_read_write, ordinal
    )
    SELECT v_decision_id, item.action_id, item.action_content_hash, item.disposition,
           COALESCE(item.reason_codes, '{}'), item.policy_decision_id,
           item.risk_assessment_id, item.resource_account_id,
           item.reservation_required, item.reservation_id,
           COALESCE(item.derived_read_write, '{}'::jsonb), item.ordinal
    FROM jsonb_to_recordset(COALESCE(p_candidate_dispositions, '[]'::jsonb))
         AS item(action_id TEXT, action_content_hash TEXT, disposition TEXT,
                 reason_codes TEXT[], policy_decision_id TEXT, risk_assessment_id TEXT,
                 resource_account_id TEXT, reservation_required BOOLEAN,
                 reservation_id TEXT, derived_read_write JSONB, ordinal INTEGER);

    INSERT INTO public.action_scores(
        score_id, decision_id, action_id, action_content_hash,
        final_score_basis_points, weight_profile_id, normalizer_version,
        score_input_hash, reason_codes, default_sources, weights, contributions
    )
    SELECT item.score_id, v_decision_id, item.action_id, item.action_content_hash,
           item.final_score_basis_points, p_weight_profile_id,
           item.normalizer_version, item.score_input_hash,
           COALESCE(item.reason_codes, '{}'), item.default_sources,
           item.weights, item.contributions
    FROM jsonb_to_recordset(COALESCE(p_scores, '[]'::jsonb))
         AS item(score_id TEXT, action_id TEXT, action_content_hash TEXT,
                 final_score_basis_points INTEGER, normalizer_version TEXT,
                 score_input_hash TEXT, reason_codes TEXT[],
                 default_sources JSONB, weights JSONB, contributions JSONB);

    INSERT INTO public.action_score_dimensions(
        score_id, dimension_name, raw_basis_points, normalized_basis_points,
        contribution_basis_points, default_source
    )
    SELECT item.score_id, item.dimension_name, item.raw_basis_points,
           item.normalized_basis_points, item.contribution_basis_points,
           item.default_source
    FROM jsonb_to_recordset(COALESCE(p_score_dimensions, '[]'::jsonb))
         AS item(score_id TEXT, dimension_name TEXT, raw_basis_points INTEGER,
                 normalized_basis_points INTEGER, contribution_basis_points INTEGER,
                 default_source TEXT);

    INSERT INTO public.selected_action_refs(
        decision_id, action_id, selection_rank, selected_intent
    )
    SELECT v_decision_id, item.action_id, item.selection_rank, item.selected_intent
    FROM jsonb_to_recordset(COALESCE(p_selected_refs, '[]'::jsonb))
         AS item(action_id TEXT, selection_rank INTEGER, selected_intent JSONB);

    INSERT INTO public.decision_reservation_mappings(
        decision_id, action_id, reservation_id, account_id, resource_amounts,
        account_version
    )
    SELECT v_decision_id, item.action_id, item.reservation_id, item.account_id,
           item.resource_amounts, r.account_version
    FROM jsonb_to_recordset(COALESCE(p_reservation_mappings, '[]'::jsonb))
         AS item(action_id TEXT, reservation_id TEXT, account_id TEXT,
                 resource_amounts JSONB, account_version BIGINT)
    JOIN public.resource_reservations r
      ON r.reservation_id = item.reservation_id;

    IF p_fault_point = 'after_decision_before_event' THEN
        RAISE EXCEPTION 'INJECTED_SELECTION_CRASH_AFTER_DECISION';
    END IF;

    decision_payload := jsonb_build_object(
        'decision_id', v_decision_id,
        'planning_run_id', p_planning_run_id,
        'selection_version', v_selection_version,
        'input_snapshot_hash', v_input_snapshot_hash,
        'eligible_action_ids', p_decision->'eligible_action_ids',
        'selected_action_ids', p_decision->'selected_action_ids',
        'rejection_summary', p_decision->'rejection_summary',
        'score_refs', p_decision->'score_refs',
        'reservation_refs', p_decision->'reservation_refs',
        'entity_version', v_selection_version
    );
    decision_event_id := 'evt-' || gen_random_uuid()::text;
    INSERT INTO public.event_log(
        event_id, event_type, schema_version, producer_type, producer_id,
        project_id, partition_key, command_id, correlation_id,
        causation_id, task_id, payload
    ) VALUES (
        decision_event_id, 'decision.recorded', '1.0',
        'action_selection', p_actor_id, p_project_id, p_project_id,
        p_command_id, p_command_id, p_planning_run_id,
        situation_row.task_id, decision_payload
    ) RETURNING sequence INTO decision_event_sequence;
    IF p_fault_point = 'after_event_before_outbox' THEN
        RAISE EXCEPTION 'INJECTED_SELECTION_CRASH_AFTER_EVENT';
    END IF;
    INSERT INTO public.outbox_messages(message_id, event_id, topic, partition_key, sequence, payload)
    VALUES ('msg-' || gen_random_uuid()::text, decision_event_id,
            'hermes.runtime.events', p_project_id, decision_event_sequence,
            decision_payload);
    IF p_fault_point = 'after_outbox_before_receipt' THEN
        RAISE EXCEPTION 'INJECTED_SELECTION_CRASH_AFTER_OUTBOX';
    END IF;

    UPDATE public.selection_heads
    SET current_decision_id = v_decision_id,
        selection_version = v_selection_version,
        active_reservation_count = (
            SELECT count(*) FROM public.decision_reservation_mappings
            WHERE decision_id = v_decision_id
        ),
        input_snapshot_hash = v_input_snapshot_hash,
        updated_at = now()
    WHERE planning_run_id = p_planning_run_id;

    RETURN jsonb_build_object(
        'decision_id', v_decision_id,
        'selection_version', v_selection_version,
        'input_snapshot_hash', v_input_snapshot_hash,
        'event_id', decision_event_id,
        'deduplicated', false
    );
END;
$$;

ALTER TABLE public.selection_weight_profiles OWNER TO hermes_selection_owner;
ALTER TABLE public.selection_heads OWNER TO hermes_selection_owner;
ALTER TABLE public.decision_records OWNER TO hermes_selection_owner;
ALTER TABLE public.decision_candidate_dispositions OWNER TO hermes_selection_owner;
ALTER TABLE public.action_scores OWNER TO hermes_selection_owner;
ALTER TABLE public.action_score_dimensions OWNER TO hermes_selection_owner;
ALTER TABLE public.selected_action_refs OWNER TO hermes_selection_owner;
ALTER TABLE public.decision_reservation_mappings OWNER TO hermes_selection_owner;
ALTER FUNCTION public.hermes_reject_selection_history_change() OWNER TO hermes_selection_owner;
ALTER FUNCTION public.hermes_apply_selection_decision(
    JSONB,JSONB,JSONB,JSONB,JSONB,JSONB,JSONB,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT
) OWNER TO hermes_selection_owner;

GRANT SELECT ON public.projects, public.tasks, public.situations,
    public.analysis_contexts, public.current_diagnoses, public.diagnoses,
    public.planning_runs, public.current_planning_runs, public.candidate_actions,
    public.candidate_action_targets, public.candidate_action_resource_estimates,
    public.policy_decisions, public.current_policy_decisions,
    public.policy_evaluation_contexts, public.risk_assessments,
    public.current_risk_assessments, public.resource_accounts,
    public.resource_balances, public.selection_weight_profiles,
    public.command_receipts TO hermes_selection_owner;
GRANT UPDATE ON public.planning_runs, public.situations TO hermes_selection_owner;
GRANT SELECT, INSERT, UPDATE ON public.selection_heads TO hermes_selection_owner;
GRANT SELECT, INSERT ON public.decision_records,
    public.decision_candidate_dispositions, public.action_scores,
    public.action_score_dimensions, public.selected_action_refs,
    public.decision_reservation_mappings TO hermes_selection_owner;
GRANT SELECT, INSERT, UPDATE ON public.resource_accounts, public.resource_balances,
    public.resource_reservations, public.resource_reservation_amounts,
    public.project_budget_facts TO hermes_selection_owner;
GRANT SELECT, INSERT ON public.event_log, public.outbox_messages TO hermes_selection_owner;
GRANT SELECT, INSERT, UPDATE ON public.command_receipts TO hermes_selection_owner;
GRANT EXECUTE ON FUNCTION public.hermes_accounting_status(TEXT, BOOLEAN)
TO hermes_selection_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_selection_owner;

REVOKE ALL ON public.selection_weight_profiles, public.selection_heads,
    public.decision_records, public.decision_candidate_dispositions,
    public.action_scores, public.action_score_dimensions,
    public.selected_action_refs, public.decision_reservation_mappings FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_reject_selection_history_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_apply_selection_decision(
    JSONB,JSONB,JSONB,JSONB,JSONB,JSONB,JSONB,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC;

GRANT SELECT ON public.selection_weight_profiles, public.selection_heads,
    public.decision_records, public.decision_candidate_dispositions,
    public.action_scores, public.action_score_dimensions,
    public.selected_action_refs, public.decision_reservation_mappings
    TO hermes_selection_runtime, hermes_read_only_runtime;
GRANT SELECT ON public.projects, public.tasks, public.situations,
    public.analysis_contexts, public.current_diagnoses, public.diagnoses,
    public.planning_runs, public.current_planning_runs, public.candidate_actions,
    public.candidate_action_targets, public.candidate_action_resource_estimates,
    public.policy_decisions, public.current_policy_decisions,
    public.policy_evaluation_contexts, public.risk_assessments,
    public.current_risk_assessments, public.resource_accounts,
    public.resource_balances TO hermes_selection_runtime;
GRANT SELECT, INSERT, UPDATE ON public.command_receipts TO hermes_selection_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_apply_selection_decision(
    JSONB,JSONB,JSONB,JSONB,JSONB,JSONB,JSONB,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT
) TO hermes_selection_runtime;

REVOKE INSERT, UPDATE, DELETE ON public.selection_weight_profiles,
    public.selection_heads, public.decision_records,
    public.decision_candidate_dispositions, public.action_scores,
    public.action_score_dimensions, public.selected_action_refs,
    public.decision_reservation_mappings, public.planning_runs,
    public.candidate_actions, public.policy_decisions, public.risk_assessments,
    public.projects, public.tasks, public.situations, public.diagnoses,
    public.resource_accounts, public.resource_balances,
    public.resource_reservations, public.resource_reservation_amounts
FROM hermes_selection_runtime, hermes_worker_runtime, hermes_verifier_runtime,
     hermes_situation_runtime, hermes_diagnosis_runtime, hermes_accounting_runtime,
     hermes_planner_runtime, hermes_policy_runtime, hermes_risk_runtime,
     hermes_control_plane_runtime, hermes_read_only_runtime;
GRANT SELECT ON public.selection_weight_profiles, public.selection_heads,
    public.decision_records, public.decision_candidate_dispositions,
    public.action_scores, public.action_score_dimensions,
    public.selected_action_refs, public.decision_reservation_mappings
    TO hermes_selection_runtime, hermes_read_only_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_selection_runtime;

COMMENT ON TABLE public.decision_records IS
'Immutable Action Selection DecisionRecord; selected refs are execution intent, not ExecutionRequest or scheduler state.';
COMMENT ON TABLE public.decision_reservation_mappings IS
'Exact immutable bridge between selected Action intent and ResourceReservation created in the same transaction.';
