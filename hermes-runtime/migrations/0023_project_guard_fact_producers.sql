-- P6: runtime producers for project evidence and policy guard facts.
--
-- Gap closure (verified by repository reconnaissance): the Project transition
-- guard requires project_evidence_facts (verification_engine) and
-- project_policy_decision_facts (policy_engine), but P0-P5 migrations only
-- created the tables and the guard; no runtime authority function produced
-- these facts (only tests inserted them via raw SQL). P6 adds guarded
-- SECURITY DEFINER producers that mirror hermes_issue_budget_fact_authority:
-- control-plane-only actor, command receipt semantics, project version/state
-- binding, current-fact supersession and immutable history.

CREATE OR REPLACE FUNCTION public.hermes_record_project_evidence_fact_authority(
    p_evidence_fact_id TEXT,
    p_project_id TEXT,
    p_expected_project_version BIGINT,
    p_from_state TEXT,
    p_to_state TEXT,
    p_subject_ref TEXT,
    p_command_id TEXT,
    p_actor_type TEXT,
    p_reason TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    project_row public.projects%ROWTYPE;
    fact_row public.project_evidence_facts%ROWTYPE;
BEGIN
    IF p_actor_type <> 'control_plane' THEN
        RAISE EXCEPTION 'CONTROL_PLANE_AUTHORITY_REQUIRED';
    END IF;
    IF NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'COMMAND_REASON_REQUIRED';
    END IF;
    PERFORM 1 FROM public.command_receipts
    WHERE command_id = p_command_id
      AND project_id = p_project_id
      AND command_type = 'project.record_evidence_fact'
      AND status = 'PROCESSING';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PROJECT_COMMAND_SEMANTICS_MISMATCH';
    END IF;
    SELECT * INTO project_row
    FROM public.projects
    WHERE project_id = p_project_id
      AND version = p_expected_project_version
    FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PROJECT_AUTHORITY_PRECONDITION_FAILED';
    END IF;
    IF project_row.state <> p_from_state THEN
        RAISE EXCEPTION 'PROJECT_AUTHORITY_PRECONDITION_FAILED';
    END IF;
    UPDATE public.project_evidence_facts
    SET valid = false, invalidated_at = now()
    WHERE project_id = p_project_id
      AND project_version = p_expected_project_version
      AND from_state = p_from_state
      AND to_state = p_to_state
      AND authority = 'verification_engine'
      AND valid
      AND invalidated_at IS NULL
      AND superseded_by IS NULL;
    INSERT INTO public.project_evidence_facts(
        evidence_fact_id, project_id, project_version, from_state, to_state,
        result, authority, subject_ref, valid
    ) VALUES (
        p_evidence_fact_id, p_project_id, p_expected_project_version,
        p_from_state, p_to_state, 'VALID', 'verification_engine',
        p_subject_ref, true
    );
    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_record_project_policy_fact_authority(
    p_policy_decision_id TEXT,
    p_project_id TEXT,
    p_expected_project_version BIGINT,
    p_from_state TEXT,
    p_to_state TEXT,
    p_result TEXT,
    p_policy_bundle_version TEXT,
    p_input_hash TEXT,
    p_command_id TEXT,
    p_actor_type TEXT,
    p_reason TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    project_row public.projects%ROWTYPE;
    policy_row public.project_policy_decision_facts%ROWTYPE;
BEGIN
    IF p_actor_type <> 'control_plane' THEN
        RAISE EXCEPTION 'CONTROL_PLANE_AUTHORITY_REQUIRED';
    END IF;
    IF NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'COMMAND_REASON_REQUIRED';
    END IF;
    IF p_result NOT IN ('ALLOW', 'DENY', 'REQUIRE_HUMAN') THEN
        RAISE EXCEPTION 'PROJECT_POLICY_RESULT_INVALID';
    END IF;
    IF p_input_hash !~ '^sha256:' THEN
        RAISE EXCEPTION 'PROJECT_POLICY_INPUT_HASH_INVALID';
    END IF;
    PERFORM 1 FROM public.command_receipts
    WHERE command_id = p_command_id
      AND project_id = p_project_id
      AND command_type = 'project.record_policy_fact'
      AND status = 'PROCESSING';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PROJECT_COMMAND_SEMANTICS_MISMATCH';
    END IF;
    SELECT * INTO project_row
    FROM public.projects
    WHERE project_id = p_project_id
      AND version = p_expected_project_version
    FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PROJECT_AUTHORITY_PRECONDITION_FAILED';
    END IF;
    IF project_row.state <> p_from_state THEN
        RAISE EXCEPTION 'PROJECT_AUTHORITY_PRECONDITION_FAILED';
    END IF;
    UPDATE public.project_policy_decision_facts
    SET valid = false, invalidated_at = now()
    WHERE project_id = p_project_id
      AND project_version = p_expected_project_version
      AND from_state = p_from_state
      AND to_state = p_to_state
      AND authority = 'policy_engine'
      AND valid
      AND invalidated_at IS NULL
      AND superseded_by IS NULL;
    INSERT INTO public.project_policy_decision_facts(
        policy_decision_id, project_id, project_version, from_state, to_state,
        result, authority, policy_bundle_version, input_hash, valid
    ) VALUES (
        p_policy_decision_id, p_project_id, p_expected_project_version,
        p_from_state, p_to_state, p_result, 'policy_engine',
        p_policy_bundle_version, p_input_hash, true
    );
    RETURN true;
END;
$$;

ALTER FUNCTION public.hermes_record_project_evidence_fact_authority(
    TEXT, TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) OWNER TO hermes_authority_owner;
ALTER FUNCTION public.hermes_record_project_policy_fact_authority(
    TEXT, TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) OWNER TO hermes_authority_owner;

GRANT EXECUTE ON FUNCTION public.hermes_record_project_evidence_fact_authority(
    TEXT, TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) TO hermes_control_plane_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_record_project_policy_fact_authority(
    TEXT, TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) TO hermes_control_plane_runtime;

REVOKE ALL ON FUNCTION public.hermes_record_project_evidence_fact_authority(
    TEXT, TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_record_project_policy_fact_authority(
    TEXT, TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;
