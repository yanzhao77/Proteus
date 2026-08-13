-- P1 Slice 3: deterministic Diagnosis Engine authority.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_diagnosis_owner') THEN
        CREATE ROLE hermes_diagnosis_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_diagnosis_runtime') THEN
        CREATE ROLE hermes_diagnosis_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

ALTER TABLE public.evidence
    ADD COLUMN IF NOT EXISTS observed_at_sequence BIGINT NOT NULL DEFAULT 0 CHECK (observed_at_sequence >= 0),
    ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS public.diagnoses (
    diagnosis_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    situation_id TEXT NOT NULL REFERENCES public.situations(situation_id),
    situation_version BIGINT NOT NULL CHECK (situation_version >= 1),
    analysis_context_id TEXT NOT NULL REFERENCES public.analysis_contexts(analysis_context_id),
    analysis_context_hash TEXT NOT NULL CHECK (analysis_context_hash LIKE 'sha256:%'),
    observed_at_sequence BIGINT NOT NULL CHECK (observed_at_sequence > 0),
    failure_type TEXT,
    root_cause TEXT,
    confidence_basis_points INTEGER NOT NULL CHECK (confidence_basis_points BETWEEN 0 AND 10000),
    affected_components TEXT[] NOT NULL DEFAULT '{}',
    root_cause_status TEXT NOT NULL CHECK (root_cause_status IN ('CONFIRMED','PROBABLE','UNKNOWN')),
    diagnostic_method TEXT NOT NULL,
    diagnosis_rule_set_version TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK (input_hash LIKE 'sha256:%'),
    matched_rule_ids TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    CHECK (root_cause_status <> 'UNKNOWN' OR root_cause IS NULL),
    UNIQUE (
        situation_id, situation_version, analysis_context_hash,
        diagnosis_rule_set_version, input_hash
    )
);

CREATE TABLE IF NOT EXISTS public.diagnosis_findings (
    diagnosis_id TEXT NOT NULL REFERENCES public.diagnoses(diagnosis_id),
    finding_code TEXT NOT NULL,
    finding_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    task_id TEXT,
    artifact_id TEXT,
    artifact_hash TEXT,
    component TEXT,
    source_verification_id TEXT,
    source_check_id TEXT,
    evidence_refs TEXT[] NOT NULL DEFAULT '{}',
    trace_id TEXT,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (diagnosis_id, ordinal),
    UNIQUE (diagnosis_id, finding_code, source_verification_id, source_check_id, artifact_id, artifact_hash)
);

CREATE TABLE IF NOT EXISTS public.diagnosis_evidence (
    diagnosis_id TEXT NOT NULL REFERENCES public.diagnoses(diagnosis_id),
    evidence_id TEXT NOT NULL REFERENCES public.evidence(evidence_id),
    relation TEXT NOT NULL CHECK (relation IN ('SUPPORTING','CONTRADICTING')),
    reason_code TEXT NOT NULL,
    PRIMARY KEY (diagnosis_id, evidence_id),
    UNIQUE (diagnosis_id, evidence_id, relation)
);

CREATE TABLE IF NOT EXISTS public.diagnosis_hypotheses (
    hypothesis_id TEXT PRIMARY KEY,
    diagnosis_id TEXT NOT NULL REFERENCES public.diagnoses(diagnosis_id),
    description_code TEXT NOT NULL,
    confidence_basis_points INTEGER NOT NULL CHECK (confidence_basis_points BETWEEN 0 AND 10000),
    test_action_hint TEXT NOT NULL CHECK (
        test_action_hint IN ('run_deeper_test','collect_metric','inspect_dependency','reproduce_failure')
    ),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    UNIQUE (diagnosis_id, ordinal),
    UNIQUE (diagnosis_id, description_code)
);

CREATE TABLE IF NOT EXISTS public.diagnosis_evidence_requests (
    diagnosis_id TEXT NOT NULL REFERENCES public.diagnoses(diagnosis_id),
    request_code TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    priority INTEGER NOT NULL CHECK (priority >= 0),
    PRIMARY KEY (diagnosis_id, request_code, target_ref)
);

CREATE TABLE IF NOT EXISTS public.current_diagnoses (
    situation_id TEXT PRIMARY KEY REFERENCES public.situations(situation_id),
    diagnosis_id TEXT NOT NULL REFERENCES public.diagnoses(diagnosis_id),
    situation_version BIGINT NOT NULL CHECK (situation_version >= 1),
    analysis_context_hash TEXT NOT NULL CHECK (analysis_context_hash LIKE 'sha256:%'),
    diagnosis_rule_set_version TEXT NOT NULL,
    input_hash TEXT NOT NULL CHECK (input_hash LIKE 'sha256:%'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS diagnoses_context_index
    ON public.diagnoses(analysis_context_id);
CREATE INDEX IF NOT EXISTS diagnoses_project_situation_index
    ON public.diagnoses(project_id, situation_id, situation_version);
CREATE INDEX IF NOT EXISTS diagnosis_evidence_relation_index
    ON public.diagnosis_evidence(diagnosis_id, relation);

CREATE OR REPLACE FUNCTION public.hermes_reject_diagnosis_history_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS diagnoses_immutable ON public.diagnoses;
CREATE TRIGGER diagnoses_immutable
BEFORE UPDATE OR DELETE ON public.diagnoses
FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_diagnosis_history_change();

DROP TRIGGER IF EXISTS diagnosis_findings_immutable ON public.diagnosis_findings;
CREATE TRIGGER diagnosis_findings_immutable
BEFORE UPDATE OR DELETE ON public.diagnosis_findings
FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_diagnosis_history_change();

DROP TRIGGER IF EXISTS diagnosis_evidence_immutable ON public.diagnosis_evidence;
CREATE TRIGGER diagnosis_evidence_immutable
BEFORE UPDATE OR DELETE ON public.diagnosis_evidence
FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_diagnosis_history_change();

DROP TRIGGER IF EXISTS diagnosis_hypotheses_immutable ON public.diagnosis_hypotheses;
CREATE TRIGGER diagnosis_hypotheses_immutable
BEFORE UPDATE OR DELETE ON public.diagnosis_hypotheses
FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_diagnosis_history_change();

DROP TRIGGER IF EXISTS diagnosis_evidence_requests_immutable ON public.diagnosis_evidence_requests;
CREATE TRIGGER diagnosis_evidence_requests_immutable
BEFORE UPDATE OR DELETE ON public.diagnosis_evidence_requests
FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_diagnosis_history_change();

CREATE OR REPLACE FUNCTION public.hermes_apply_diagnosis(
    p_diagnosis_id TEXT,
    p_project_id TEXT,
    p_situation_id TEXT,
    p_situation_version BIGINT,
    p_analysis_context_id TEXT,
    p_analysis_context_hash TEXT,
    p_rule_set_version TEXT,
    p_input_hash TEXT,
    p_root_cause_status TEXT,
    p_root_cause TEXT,
    p_confidence_basis_points INTEGER,
    p_diagnostic_method TEXT,
    p_matched_rule_ids TEXT[],
    p_findings JSONB,
    p_evidence JSONB,
    p_hypotheses JSONB,
    p_evidence_requests JSONB,
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
    inserted_diagnosis TEXT;
    event_id TEXT;
    event_sequence BIGINT;
    event_payload JSONB;
    max_future_evidence TEXT;
BEGIN
    IF p_actor_type <> 'diagnosis_engine' OR NULLIF(btrim(p_actor_id), '') IS NULL THEN
        RAISE EXCEPTION 'DIAGNOSIS_AUTHORITY_REQUIRED';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.command_receipts c
        WHERE c.command_id = p_command_id AND c.project_id = p_project_id
          AND c.command_type = 'diagnosis.run' AND c.status = 'PROCESSING'
    ) THEN
        RAISE EXCEPTION 'DIAGNOSIS_AUTHORITY_REQUIRED';
    END IF;

    SELECT * INTO situation_row FROM public.situations
    WHERE situation_id = p_situation_id AND project_id = p_project_id
    FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'DIAGNOSIS_SITUATION_NOT_FOUND'; END IF;
    IF situation_row.status <> 'OPEN' THEN
        RAISE EXCEPTION 'DIAGNOSIS_SITUATION_NOT_OPEN';
    END IF;
    IF situation_row.version <> p_situation_version THEN
        RAISE EXCEPTION 'DIAGNOSIS_SITUATION_VERSION_CONFLICT';
    END IF;
    IF situation_row.analysis_context_id <> p_analysis_context_id THEN
        RAISE EXCEPTION 'DIAGNOSIS_CONTEXT_NOT_FOUND';
    END IF;

    SELECT * INTO context_row FROM public.analysis_contexts
    WHERE analysis_context_id = p_analysis_context_id AND project_id = p_project_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'DIAGNOSIS_CONTEXT_NOT_FOUND'; END IF;
    IF context_row.context_hash <> p_analysis_context_hash THEN
        RAISE EXCEPTION 'DIAGNOSIS_CONTEXT_HASH_MISMATCH';
    END IF;
    IF context_row.observed_at_sequence <> situation_row.observed_at_sequence THEN
        RAISE EXCEPTION 'DIAGNOSIS_INPUT_STALE';
    END IF;

    SELECT e.evidence_id INTO max_future_evidence
    FROM jsonb_to_recordset(COALESCE(p_evidence, '[]'::jsonb))
         AS payload(evidence_id TEXT)
    JOIN public.evidence e ON e.evidence_id = payload.evidence_id
    WHERE e.observed_at_sequence > context_row.observed_at_sequence
    ORDER BY e.evidence_id LIMIT 1;
    IF max_future_evidence IS NOT NULL THEN
        RAISE EXCEPTION 'DIAGNOSIS_CONTEXT_FUTURE_FACT';
    END IF;

    INSERT INTO public.diagnoses(
        diagnosis_id, project_id, situation_id, situation_version,
        analysis_context_id, analysis_context_hash, observed_at_sequence,
        failure_type, root_cause, confidence_basis_points,
        affected_components, root_cause_status, diagnostic_method,
        diagnosis_rule_set_version, input_hash, matched_rule_ids, command_id
    ) VALUES (
        p_diagnosis_id, p_project_id, p_situation_id, p_situation_version,
        p_analysis_context_id, p_analysis_context_hash,
        context_row.observed_at_sequence, situation_row.failure_type,
        p_root_cause, p_confidence_basis_points,
        situation_row.affected_components, p_root_cause_status,
        p_diagnostic_method, p_rule_set_version, p_input_hash,
        COALESCE(p_matched_rule_ids, '{}'), p_command_id
    )
    ON CONFLICT (
        situation_id, situation_version, analysis_context_hash,
        diagnosis_rule_set_version, input_hash
    ) DO NOTHING
    RETURNING diagnosis_id INTO inserted_diagnosis;

    IF inserted_diagnosis IS NULL THEN
        SELECT diagnosis_id INTO inserted_diagnosis FROM public.diagnoses
        WHERE situation_id = p_situation_id
          AND situation_version = p_situation_version
          AND analysis_context_hash = p_analysis_context_hash
          AND diagnosis_rule_set_version = p_rule_set_version
          AND input_hash = p_input_hash;
        RETURN jsonb_build_object(
            'diagnosis_id', inserted_diagnosis,
            'root_cause_status', p_root_cause_status,
            'root_cause', p_root_cause,
            'confidence_basis_points', p_confidence_basis_points,
            'input_hash', p_input_hash,
            'event_id', NULL,
            'deduplicated', true
        );
    END IF;

    IF p_fault_point = 'after_diagnosis_before_evidence' THEN
        RAISE EXCEPTION 'INJECTED_DIAGNOSIS_CRASH_AFTER_DIAGNOSIS';
    END IF;

    INSERT INTO public.diagnosis_findings(
        diagnosis_id, finding_code, finding_type, severity, task_id,
        artifact_id, artifact_hash, component, source_verification_id,
        source_check_id, evidence_refs, trace_id, ordinal
    )
    SELECT
        inserted_diagnosis, item.finding_code, item.finding_type, item.severity,
        item.task_id, item.artifact_id, item.artifact_hash, item.component,
        item.source_verification_id, item.source_check_id,
        COALESCE(item.evidence_refs, '{}'), item.trace_id, item.ordinal
    FROM jsonb_to_recordset(COALESCE(p_findings, '[]'::jsonb)) AS item(
        finding_code TEXT, finding_type TEXT, severity TEXT, task_id TEXT,
        artifact_id TEXT, artifact_hash TEXT, component TEXT,
        source_verification_id TEXT, source_check_id TEXT,
        evidence_refs TEXT[], trace_id TEXT, ordinal INTEGER
    );

    INSERT INTO public.diagnosis_evidence(
        diagnosis_id, evidence_id, relation, reason_code
    )
    SELECT inserted_diagnosis, item.evidence_id, item.relation, item.reason_code
    FROM jsonb_to_recordset(COALESCE(p_evidence, '[]'::jsonb)) AS item(
        evidence_id TEXT, relation TEXT, reason_code TEXT
    );

    IF p_fault_point = 'after_evidence_before_hypothesis' THEN
        RAISE EXCEPTION 'INJECTED_DIAGNOSIS_CRASH_AFTER_EVIDENCE';
    END IF;

    INSERT INTO public.diagnosis_hypotheses(
        hypothesis_id, diagnosis_id, description_code,
        confidence_basis_points, test_action_hint, ordinal
    )
    SELECT
        'hyp-' || left(encode(public.digest(convert_to(
            inserted_diagnosis || ':' || item.ordinal::text || ':' || item.description_code,
            'UTF8'), 'sha256'), 'hex'), 32),
        inserted_diagnosis, item.description_code,
        item.confidence_basis_points, item.test_action_hint, item.ordinal
    FROM jsonb_to_recordset(COALESCE(p_hypotheses, '[]'::jsonb)) AS item(
        description_code TEXT, confidence_basis_points INTEGER,
        test_action_hint TEXT, ordinal INTEGER
    );

    IF p_fault_point = 'after_hypothesis_before_evidence_request' THEN
        RAISE EXCEPTION 'INJECTED_DIAGNOSIS_CRASH_AFTER_HYPOTHESIS';
    END IF;

    INSERT INTO public.diagnosis_evidence_requests(
        diagnosis_id, request_code, evidence_kind,
        target_ref, reason_code, priority
    )
    SELECT inserted_diagnosis, item.request_code, item.evidence_kind,
           item.target_ref, item.reason_code, item.priority
    FROM jsonb_to_recordset(COALESCE(p_evidence_requests, '[]'::jsonb)) AS item(
        request_code TEXT, evidence_kind TEXT, target_ref TEXT,
        reason_code TEXT, priority INTEGER
    );

    IF p_fault_point = 'after_evidence_request_before_event' THEN
        RAISE EXCEPTION 'INJECTED_DIAGNOSIS_CRASH_AFTER_EVIDENCE_REQUEST';
    END IF;

    INSERT INTO public.current_diagnoses(
        situation_id, diagnosis_id, situation_version,
        analysis_context_hash, diagnosis_rule_set_version, input_hash
    ) VALUES (
        p_situation_id, inserted_diagnosis, p_situation_version,
        p_analysis_context_hash, p_rule_set_version, p_input_hash
    )
    ON CONFLICT (situation_id) DO UPDATE SET
        diagnosis_id = EXCLUDED.diagnosis_id,
        situation_version = EXCLUDED.situation_version,
        analysis_context_hash = EXCLUDED.analysis_context_hash,
        diagnosis_rule_set_version = EXCLUDED.diagnosis_rule_set_version,
        input_hash = EXCLUDED.input_hash,
        updated_at = now()
    WHERE public.current_diagnoses.situation_version <= EXCLUDED.situation_version;

    IF p_fault_point = 'after_current_before_event' THEN
        RAISE EXCEPTION 'INJECTED_DIAGNOSIS_CRASH_AFTER_CURRENT';
    END IF;

    event_id := 'evt-' || gen_random_uuid()::text;
    event_payload := jsonb_build_object(
        'diagnosis_id', inserted_diagnosis,
        'situation_id', p_situation_id,
        'situation_version', p_situation_version,
        'analysis_context_id', p_analysis_context_id,
        'root_cause_status', p_root_cause_status,
        'confidence_basis_points', p_confidence_basis_points,
        'supporting_evidence_refs',
            COALESCE((SELECT jsonb_agg(item.evidence_id ORDER BY item.evidence_id)
                      FROM jsonb_to_recordset(COALESCE(p_evidence, '[]'::jsonb))
                           AS item(evidence_id TEXT, relation TEXT)
                      WHERE item.relation = 'SUPPORTING'), '[]'::jsonb),
        'contradicting_evidence_refs',
            COALESCE((SELECT jsonb_agg(item.evidence_id ORDER BY item.evidence_id)
                      FROM jsonb_to_recordset(COALESCE(p_evidence, '[]'::jsonb))
                           AS item(evidence_id TEXT, relation TEXT)
                      WHERE item.relation = 'CONTRADICTING'), '[]'::jsonb),
        'diagnosis_rule_set_version', p_rule_set_version,
        'input_hash', p_input_hash
    );
    INSERT INTO public.event_log(
        event_id, event_type, schema_version, producer_type, producer_id,
        project_id, partition_key, command_id, correlation_id,
        causation_id, task_id, payload
    ) VALUES (
        event_id, 'diagnosis.completed', '1.0',
        'diagnosis_engine', p_actor_id, p_project_id, p_project_id,
        p_command_id, p_command_id, situation_row.trigger_event_id,
        situation_row.task_id, event_payload
    ) RETURNING sequence INTO event_sequence;

    IF p_fault_point = 'after_event_before_outbox' THEN
        RAISE EXCEPTION 'INJECTED_DIAGNOSIS_CRASH_AFTER_EVENT';
    END IF;

    INSERT INTO public.outbox_messages(
        message_id, event_id, topic, partition_key, sequence, payload
    ) VALUES (
        'msg-' || gen_random_uuid()::text, event_id, 'hermes.runtime.events',
        p_project_id, event_sequence, event_payload
    );

    IF p_fault_point = 'after_outbox_before_receipt' THEN
        RAISE EXCEPTION 'INJECTED_DIAGNOSIS_CRASH_AFTER_OUTBOX';
    END IF;

    RETURN jsonb_build_object(
        'diagnosis_id', inserted_diagnosis,
        'root_cause_status', p_root_cause_status,
        'root_cause', p_root_cause,
        'confidence_basis_points', p_confidence_basis_points,
        'input_hash', p_input_hash,
        'event_id', event_id,
        'deduplicated', false
    );
END;
$$;

ALTER TABLE public.diagnoses OWNER TO hermes_diagnosis_owner;
ALTER TABLE public.diagnosis_findings OWNER TO hermes_diagnosis_owner;
ALTER TABLE public.diagnosis_evidence OWNER TO hermes_diagnosis_owner;
ALTER TABLE public.diagnosis_hypotheses OWNER TO hermes_diagnosis_owner;
ALTER TABLE public.diagnosis_evidence_requests OWNER TO hermes_diagnosis_owner;
ALTER TABLE public.current_diagnoses OWNER TO hermes_diagnosis_owner;
ALTER FUNCTION public.hermes_reject_diagnosis_history_change() OWNER TO hermes_diagnosis_owner;
ALTER FUNCTION public.hermes_apply_diagnosis(
    TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,INTEGER,TEXT,
    TEXT[],JSONB,JSONB,JSONB,JSONB,TEXT,TEXT,TEXT,TEXT
) OWNER TO hermes_diagnosis_owner;

GRANT SELECT ON public.projects, public.tasks, public.artifacts, public.evidence,
    public.verification_results, public.verification_check_results,
    public.verification_evidence, public.event_log, public.command_receipts,
    public.analysis_contexts, public.situations, public.situation_versions
    TO hermes_diagnosis_owner;
GRANT UPDATE ON public.situations TO hermes_diagnosis_owner;
GRANT INSERT ON public.diagnoses, public.diagnosis_findings,
    public.diagnosis_evidence, public.diagnosis_hypotheses,
    public.diagnosis_evidence_requests TO hermes_diagnosis_owner;
GRANT SELECT, INSERT, UPDATE ON public.current_diagnoses TO hermes_diagnosis_owner;
GRANT SELECT, INSERT ON public.event_log, public.outbox_messages TO hermes_diagnosis_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_diagnosis_owner;

REVOKE ALL ON public.diagnoses, public.diagnosis_findings,
    public.diagnosis_evidence, public.diagnosis_hypotheses,
    public.diagnosis_evidence_requests, public.current_diagnoses FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_reject_diagnosis_history_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_apply_diagnosis(
    TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,INTEGER,TEXT,
    TEXT[],JSONB,JSONB,JSONB,JSONB,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC;

GRANT SELECT ON public.diagnoses, public.diagnosis_findings,
    public.diagnosis_evidence, public.diagnosis_hypotheses,
    public.diagnosis_evidence_requests, public.current_diagnoses
    TO hermes_diagnosis_runtime, hermes_read_only_runtime;
GRANT SELECT ON public.projects, public.tasks, public.artifacts, public.evidence,
    public.verification_results, public.verification_check_results,
    public.verification_evidence, public.event_log, public.command_receipts,
    public.analysis_contexts, public.situations, public.situation_versions
    TO hermes_diagnosis_runtime;
GRANT SELECT, INSERT, UPDATE ON public.command_receipts TO hermes_diagnosis_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_apply_diagnosis(
    TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,INTEGER,TEXT,
    TEXT[],JSONB,JSONB,JSONB,JSONB,TEXT,TEXT,TEXT,TEXT
) TO hermes_diagnosis_runtime;

REVOKE INSERT, UPDATE, DELETE ON public.diagnoses, public.diagnosis_findings,
    public.diagnosis_evidence, public.diagnosis_hypotheses,
    public.diagnosis_evidence_requests, public.current_diagnoses
FROM hermes_diagnosis_runtime, hermes_worker_runtime, hermes_verifier_runtime,
     hermes_situation_runtime, hermes_accounting_runtime,
     hermes_control_plane_runtime, hermes_read_only_runtime;
REVOKE INSERT, UPDATE, DELETE ON public.situations, public.projects,
    public.tasks, public.artifacts, public.evidence
FROM hermes_diagnosis_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_diagnosis_runtime;

COMMENT ON TABLE public.diagnoses IS
'Immutable deterministic Diagnosis records bound to one Situation version and frozen AnalysisContext hash.';
COMMENT ON TABLE public.diagnosis_evidence IS
'Supporting or contradicting Evidence references only; Evidence content is not copied.';
COMMENT ON TABLE public.current_diagnoses IS
'Controlled current Diagnosis pointer for one Situation; writable only through Diagnosis authority.';
