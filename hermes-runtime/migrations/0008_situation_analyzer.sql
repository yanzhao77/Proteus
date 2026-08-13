-- P1 Slice 2: deterministic Situation analysis and lifecycle authority.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_situation_owner') THEN
        CREATE ROLE hermes_situation_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_situation_runtime') THEN
        CREATE ROLE hermes_situation_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.analysis_contexts (
    analysis_context_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    trigger_event_id TEXT NOT NULL UNIQUE REFERENCES public.event_log(event_id),
    partition_key TEXT NOT NULL,
    observed_at_sequence BIGINT NOT NULL CHECK (observed_at_sequence > 0),
    trigger_event_type TEXT NOT NULL,
    trigger_event_schema_version TEXT NOT NULL,
    trigger_event_hash TEXT NOT NULL CHECK (trigger_event_hash LIKE 'sha256:%'),
    project_version_ref TEXT,
    task_id TEXT,
    task_version_ref TEXT,
    artifact_refs TEXT[] NOT NULL DEFAULT '{}',
    evidence_refs TEXT[] NOT NULL DEFAULT '{}',
    verification_refs TEXT[] NOT NULL DEFAULT '{}',
    budget_account_version_refs TEXT[] NOT NULL DEFAULT '{}',
    policy_decision_refs TEXT[] NOT NULL DEFAULT '{}',
    previous_situation_refs TEXT[] NOT NULL DEFAULT '{}',
    work_graph_version_ref TEXT,
    rule_set_version TEXT NOT NULL,
    context_hash TEXT NOT NULL CHECK (context_hash LIKE 'sha256:%'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (project_id, task_id) REFERENCES public.tasks(project_id, task_id)
);

CREATE TABLE IF NOT EXISTS public.situations (
    situation_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT,
    type TEXT NOT NULL CHECK (type IN (
        'verification_failed', 'work_available', 'budget_pressure',
        'policy_blocked', 'state_conflict', 'resource_missing', 'agent_stalled'
    )),
    status TEXT NOT NULL CHECK (status IN ('OPEN', 'SUPERSEDED', 'RESOLVED')),
    trigger_event_id TEXT NOT NULL REFERENCES public.event_log(event_id),
    analysis_context_id TEXT NOT NULL REFERENCES public.analysis_contexts(analysis_context_id),
    failure_type TEXT,
    severity TEXT NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    affected_artifact_refs TEXT[] NOT NULL DEFAULT '{}',
    affected_components TEXT[] NOT NULL DEFAULT '{}',
    available_context_refs TEXT[] NOT NULL DEFAULT '{}',
    constraints TEXT[] NOT NULL DEFAULT '{}',
    history_summary JSONB NOT NULL DEFAULT '{"attempts":0,"strategies_tried":[],"previous_situation_refs":[]}'::jsonb,
    confidence_basis_points INTEGER NOT NULL CHECK (
        confidence_basis_points BETWEEN 0 AND 10000
    ),
    fingerprint TEXT NOT NULL CHECK (fingerprint LIKE 'sha256:%'),
    observed_at_sequence BIGINT NOT NULL CHECK (observed_at_sequence > 0),
    rule_set_version TEXT NOT NULL,
    canonicalization_version TEXT NOT NULL,
    version BIGINT NOT NULL CHECK (version >= 1),
    superseded_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    FOREIGN KEY (project_id, task_id) REFERENCES public.tasks(project_id, task_id),
    CHECK ((status = 'SUPERSEDED') = (superseded_by IS NOT NULL)),
    CHECK ((status = 'RESOLVED') = (resolved_at IS NOT NULL))
);

ALTER TABLE public.situations
    DROP CONSTRAINT IF EXISTS situations_superseded_by_fkey;
ALTER TABLE public.situations
    ADD CONSTRAINT situations_superseded_by_fkey
    FOREIGN KEY (superseded_by) REFERENCES public.situations(situation_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE UNIQUE INDEX IF NOT EXISTS situations_one_open_fingerprint_per_project
    ON public.situations(project_id, fingerprint) WHERE status = 'OPEN';
CREATE INDEX IF NOT EXISTS situations_lifecycle_scope
    ON public.situations(project_id, task_id, type, status);
CREATE INDEX IF NOT EXISTS situations_context_index
    ON public.situations(analysis_context_id);

CREATE TABLE IF NOT EXISTS public.situation_versions (
    situation_id TEXT NOT NULL REFERENCES public.situations(situation_id),
    version BIGINT NOT NULL CHECK (version >= 1),
    status TEXT NOT NULL CHECK (status IN ('OPEN', 'SUPERSEDED', 'RESOLVED')),
    trigger_event_id TEXT NOT NULL REFERENCES public.event_log(event_id),
    analysis_context_id TEXT NOT NULL REFERENCES public.analysis_contexts(analysis_context_id),
    failure_type TEXT,
    severity TEXT NOT NULL,
    affected_artifact_refs TEXT[] NOT NULL,
    affected_components TEXT[] NOT NULL,
    available_context_refs TEXT[] NOT NULL,
    constraints TEXT[] NOT NULL,
    history_summary JSONB NOT NULL,
    confidence_basis_points INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    observed_at_sequence BIGINT NOT NULL,
    superseded_by TEXT,
    change_type TEXT NOT NULL CHECK (
        change_type IN ('CREATED', 'UPDATED', 'SUPERSEDED', 'RESOLVED')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (situation_id, version)
);

CREATE OR REPLACE FUNCTION public.hermes_reject_situation_history_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS analysis_contexts_immutable ON public.analysis_contexts;
CREATE TRIGGER analysis_contexts_immutable
BEFORE UPDATE OR DELETE ON public.analysis_contexts
FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_situation_history_change();

DROP TRIGGER IF EXISTS situation_versions_immutable ON public.situation_versions;
CREATE TRIGGER situation_versions_immutable
BEFORE UPDATE OR DELETE ON public.situation_versions
FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_situation_history_change();

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

CREATE OR REPLACE FUNCTION public.hermes_resolve_situation(
    p_situation_id TEXT,
    p_project_id TEXT,
    p_expected_version BIGINT,
    p_command_id TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_reason TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    current_row public.situations%ROWTYPE;
    event_id TEXT;
    event_sequence BIGINT;
    event_payload JSONB;
BEGIN
    IF p_actor_type NOT IN ('control_plane', 'system_operator')
       OR NULLIF(btrim(p_actor_id), '') IS NULL
       OR NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'SITUATION_AUTHORITY_REQUIRED';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.command_receipts c
        WHERE c.command_id = p_command_id AND c.project_id = p_project_id
          AND c.command_type = 'situation.resolve' AND c.status = 'PROCESSING'
    ) THEN RAISE EXCEPTION 'SITUATION_AUTHORITY_REQUIRED'; END IF;
    SELECT * INTO current_row FROM public.situations
    WHERE situation_id = p_situation_id AND project_id = p_project_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'SITUATION_CONTEXT_UNAVAILABLE'; END IF;
    IF current_row.status = 'RESOLVED' THEN
        RETURN jsonb_build_object(
            'situation_id', current_row.situation_id,
            'version', current_row.version,
            'status', current_row.status
        );
    END IF;
    IF current_row.status <> 'OPEN' THEN
        RAISE EXCEPTION 'SITUATION_SUPERSEDE_CONFLICT';
    END IF;
    IF current_row.version <> p_expected_version THEN
        RAISE EXCEPTION 'SITUATION_VERSION_CONFLICT';
    END IF;
    UPDATE public.situations SET status = 'RESOLVED', version = version + 1,
        resolved_at = now(), updated_at = now()
    WHERE situation_id = p_situation_id;
    INSERT INTO public.situation_versions
    SELECT situation_id, version, status, trigger_event_id,
           analysis_context_id, failure_type, severity,
           affected_artifact_refs, affected_components,
           available_context_refs, constraints, history_summary,
           confidence_basis_points, fingerprint, observed_at_sequence,
           superseded_by, 'RESOLVED', now()
    FROM public.situations WHERE situation_id = p_situation_id;
    event_id := 'evt-' || gen_random_uuid()::text;
    event_payload := jsonb_build_object(
        'situation_id', p_situation_id, 'reason', p_reason,
        'resolved_by', jsonb_build_object('type', p_actor_type, 'id', p_actor_id)
    );
    INSERT INTO public.event_log(
        event_id,event_type,schema_version,producer_type,producer_id,
        project_id,partition_key,command_id,correlation_id,payload
    ) VALUES (
        event_id,'situation.resolved','1.0','control_plane',p_actor_id,
        p_project_id,p_project_id,p_command_id,p_command_id,event_payload
    ) RETURNING sequence INTO event_sequence;
    INSERT INTO public.outbox_messages(
        message_id,event_id,topic,partition_key,sequence,payload
    ) VALUES (
        'msg-' || gen_random_uuid()::text,event_id,'hermes.runtime.events',
        p_project_id,event_sequence,event_payload
    );
    RETURN jsonb_build_object(
        'situation_id', p_situation_id,
        'version', current_row.version + 1,
        'status', 'RESOLVED', 'event_id', event_id
    );
END;
$$;

ALTER TABLE public.analysis_contexts OWNER TO hermes_situation_owner;
ALTER TABLE public.situations OWNER TO hermes_situation_owner;
ALTER TABLE public.situation_versions OWNER TO hermes_situation_owner;
ALTER FUNCTION public.hermes_reject_situation_history_change() OWNER TO hermes_situation_owner;
ALTER FUNCTION public.hermes_apply_situation_effect(
    TEXT,TEXT,TEXT,BIGINT,TEXT,JSONB,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TEXT,
    INTEGER,TEXT[],TEXT[],TEXT[],TEXT[],TEXT,TEXT,TEXT,TEXT,TEXT,TEXT[],
    TEXT[],TEXT[],TEXT,BIGINT,TEXT
) OWNER TO hermes_situation_owner;
ALTER FUNCTION public.hermes_resolve_situation(
    TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT
) OWNER TO hermes_situation_owner;

GRANT SELECT ON public.event_log, public.command_receipts, public.tasks,
    public.projects, public.verification_results, public.verification_evidence,
    public.feedback_records, public.resource_accounts TO hermes_situation_owner;
GRANT SELECT, INSERT ON public.analysis_contexts, public.situation_versions
    TO hermes_situation_owner;
GRANT SELECT, INSERT, UPDATE ON public.situations TO hermes_situation_owner;
GRANT SELECT, INSERT ON public.event_log, public.outbox_messages,
    public.consumer_effects, public.consumer_inbox TO hermes_situation_owner;
GRANT SELECT, INSERT, UPDATE ON public.consumer_checkpoints,
    public.consumer_pending_gaps TO hermes_situation_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_situation_owner;

REVOKE ALL ON public.analysis_contexts, public.situations,
    public.situation_versions FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_reject_situation_history_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_apply_situation_effect(
    TEXT,TEXT,TEXT,BIGINT,TEXT,JSONB,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TEXT,
    INTEGER,TEXT[],TEXT[],TEXT[],TEXT[],TEXT,TEXT,TEXT,TEXT,TEXT,TEXT[],
    TEXT[],TEXT[],TEXT,BIGINT,TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_resolve_situation(
    TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC;

GRANT SELECT ON public.analysis_contexts, public.situations,
    public.situation_versions TO hermes_situation_runtime, hermes_read_only_runtime;
GRANT SELECT ON public.event_log, public.consumer_inbox,
    public.consumer_checkpoints, public.consumer_pending_gaps
    TO hermes_situation_runtime;
GRANT SELECT, INSERT, UPDATE ON public.command_receipts
    TO hermes_situation_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_consumer_park_gap(
    TEXT,TEXT,TEXT,BIGINT,JSONB,INTEGER
) TO hermes_situation_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_apply_situation_effect(
    TEXT,TEXT,TEXT,BIGINT,TEXT,JSONB,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TEXT,
    INTEGER,TEXT[],TEXT[],TEXT[],TEXT[],TEXT,TEXT,TEXT,TEXT,TEXT,TEXT[],
    TEXT[],TEXT[],TEXT,BIGINT,TEXT
) TO hermes_situation_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_resolve_situation(
    TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT
) TO hermes_situation_runtime;

REVOKE INSERT, UPDATE, DELETE ON public.analysis_contexts, public.situations,
    public.situation_versions FROM hermes_situation_runtime,
    hermes_worker_runtime, hermes_verifier_runtime, hermes_accounting_runtime,
    hermes_control_plane_runtime, hermes_read_only_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_situation_runtime;

COMMENT ON TABLE public.analysis_contexts IS
'Immutable, sequence-bounded authoritative inputs used by deterministic Situation rules.';
COMMENT ON TABLE public.situations IS
'Current Situation authority; mutation is restricted to guarded lifecycle functions.';
COMMENT ON TABLE public.situation_versions IS
'Append-only Situation lifecycle snapshots.';
