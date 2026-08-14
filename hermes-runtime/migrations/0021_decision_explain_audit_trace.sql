-- P3-4: Decision Explain, audit and trace immutable runtime authority.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_p3_explain_owner') THEN
        CREATE ROLE hermes_p3_explain_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_explain_capture_runtime') THEN
        CREATE ROLE hermes_explain_capture_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_explain_query_runtime') THEN
        CREATE ROLE hermes_explain_query_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_metrics_runtime') THEN
        CREATE ROLE hermes_metrics_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.decision_explain_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_version BIGINT NOT NULL CHECK (source_version >= 0),
    source_hash TEXT NOT NULL CHECK (source_hash LIKE 'sha256:%'),
    schema_version TEXT NOT NULL,
    producer_version TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL CHECK (snapshot_hash LIKE 'sha256:%'),
    ref_graph_hash TEXT NOT NULL CHECK (ref_graph_hash LIKE 'sha256:%'),
    summary JSONB NOT NULL,
    missing_links JSONB NOT NULL DEFAULT '[]'::jsonb,
    redaction_class TEXT NOT NULL CHECK (
        redaction_class IN ('PUBLIC','INTERNAL','RESTRICTED','SECRET_HANDLE')
    ),
    retention_policy TEXT NOT NULL,
    retention_until TIMESTAMPTZ NOT NULL,
    authorization_scope JSONB NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    authorization_ref TEXT NOT NULL,
    reason TEXT NOT NULL,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    event_id TEXT NOT NULL UNIQUE REFERENCES public.event_log(event_id) DEFERRABLE INITIALLY DEFERRED,
    idempotency_key TEXT NOT NULL,
    causation_id TEXT,
    correlation_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (project_id, source_type, source_id, source_version, snapshot_hash),
    CHECK (summary::text !~* '(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|private key|sk-[A-Za-z0-9]{12,}|password=)'),
    CHECK (authorization_scope::text !~* '(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|private key|sk-[A-Za-z0-9]{12,}|password=)'),
    CHECK (missing_links::text !~* '(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|private key|sk-[A-Za-z0-9]{12,}|password=)')
);

CREATE TABLE IF NOT EXISTS public.decision_explain_nodes (
    snapshot_id TEXT NOT NULL REFERENCES public.decision_explain_snapshots(snapshot_id),
    node_id TEXT NOT NULL,
    node_type TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    ref_version BIGINT NOT NULL,
    ref_hash TEXT,
    status TEXT NOT NULL CHECK (status IN ('PRESENT','MISSING','REDACTED')),
    missing_reason TEXT NOT NULL DEFAULT '',
    safe_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    sort_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (snapshot_id, node_id),
    CHECK ((status = 'MISSING' AND missing_reason <> '') OR (status <> 'MISSING' AND missing_reason = '')),
    CHECK (status = 'MISSING' OR ref_hash LIKE 'sha256:%'),
    CHECK (safe_summary::text !~* '(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|private key|sk-[A-Za-z0-9]{12,}|password=)')
);

CREATE TABLE IF NOT EXISTS public.decision_explain_edges (
    snapshot_id TEXT NOT NULL REFERENCES public.decision_explain_snapshots(snapshot_id),
    from_node_id TEXT NOT NULL,
    to_node_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    sort_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (snapshot_id, from_node_id, to_node_id, relation),
    FOREIGN KEY (snapshot_id, from_node_id)
        REFERENCES public.decision_explain_nodes(snapshot_id, node_id),
    FOREIGN KEY (snapshot_id, to_node_id)
        REFERENCES public.decision_explain_nodes(snapshot_id, node_id),
    CHECK (from_node_id <> to_node_id)
);

CREATE TABLE IF NOT EXISTS public.audit_trace_records (
    audit_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    causation_id TEXT,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_version BIGINT NOT NULL,
    aggregate_hash TEXT NOT NULL CHECK (aggregate_hash LIKE 'sha256:%'),
    action TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    authorization_ref TEXT NOT NULL,
    redaction_class TEXT NOT NULL CHECK (
        redaction_class IN ('PUBLIC','INTERNAL','RESTRICTED','SECRET_HANDLE')
    ),
    safe_summary JSONB NOT NULL,
    retention_policy TEXT NOT NULL,
    retention_until TIMESTAMPTZ NOT NULL,
    command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    event_id TEXT NOT NULL REFERENCES public.event_log(event_id) DEFERRABLE INITIALLY DEFERRED,
    idempotency_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (safe_summary::text !~* '(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|private key|sk-[A-Za-z0-9]{12,}|password=)')
);

CREATE INDEX IF NOT EXISTS decision_explain_trace_idx
    ON public.decision_explain_snapshots(project_id, trace_id, correlation_id, created_at);
CREATE INDEX IF NOT EXISTS audit_trace_lookup_idx
    ON public.audit_trace_records(project_id, trace_id, correlation_id, created_at);

CREATE OR REPLACE FUNCTION public.hermes_p3_explain_reject_append_only_change()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'P3_EXPLAIN_HISTORY_IS_APPEND_ONLY';
END;
$$;

DROP TRIGGER IF EXISTS decision_explain_snapshots_append_only ON public.decision_explain_snapshots;
CREATE TRIGGER decision_explain_snapshots_append_only
BEFORE UPDATE OR DELETE ON public.decision_explain_snapshots
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_explain_reject_append_only_change();

DROP TRIGGER IF EXISTS decision_explain_nodes_append_only ON public.decision_explain_nodes;
CREATE TRIGGER decision_explain_nodes_append_only
BEFORE UPDATE OR DELETE ON public.decision_explain_nodes
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_explain_reject_append_only_change();

DROP TRIGGER IF EXISTS decision_explain_edges_append_only ON public.decision_explain_edges;
CREATE TRIGGER decision_explain_edges_append_only
BEFORE UPDATE OR DELETE ON public.decision_explain_edges
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_explain_reject_append_only_change();

DROP TRIGGER IF EXISTS audit_trace_records_append_only ON public.audit_trace_records;
CREATE TRIGGER audit_trace_records_append_only
BEFORE UPDATE OR DELETE ON public.audit_trace_records
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_explain_reject_append_only_change();

CREATE OR REPLACE FUNCTION public.hermes_p3_explain_secret_guard(p_payload JSONB)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF p_payload::text ~* '(api[_-]?token|password|credential|private[_-]?key|secret[_-]?value|private key|sk-[A-Za-z0-9]{12,}|password=)' THEN
        RAISE EXCEPTION 'RETENTION_REDACTION_VIOLATION';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_explain_begin_command(
    p_project_id TEXT,
    p_command_type TEXT,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT
) RETURNS public.command_receipts
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_existing public.command_receipts%ROWTYPE;
BEGIN
    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key, request_hash,
        status, result
    ) VALUES (
        p_command_id, p_project_id, p_command_type, p_idempotency_key,
        p_payload_hash, 'PROCESSING', '{}'::jsonb
    )
    ON CONFLICT (project_id, command_type, idempotency_key) DO NOTHING;

    SELECT * INTO v_existing
    FROM public.command_receipts
    WHERE project_id = p_project_id
      AND command_type = p_command_type
      AND idempotency_key = p_idempotency_key
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'COMMAND_RECEIPT_NOT_FOUND';
    END IF;
    IF v_existing.request_hash <> p_payload_hash THEN
        RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT';
    END IF;
    RETURN v_existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_explain_complete_command(
    p_command_id TEXT,
    p_status TEXT,
    p_result JSONB
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    UPDATE public.command_receipts
    SET status=p_status, result=p_result, completed_at=clock_timestamp()
    WHERE command_id=p_command_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_explain_append_event(
    p_project_id TEXT,
    p_partition_key TEXT,
    p_command_id TEXT,
    p_event_type TEXT,
    p_producer_type TEXT,
    p_producer_id TEXT,
    p_payload JSONB,
    p_correlation_id TEXT
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
        p_project_id,p_partition_key,p_command_id,p_correlation_id,p_payload
    )
    RETURNING sequence INTO v_sequence;
    INSERT INTO public.outbox_messages(message_id,event_id,topic,partition_key,sequence,payload)
    VALUES ('msg-' || gen_random_uuid()::text, v_event_id, 'hermes.runtime.events',
            p_partition_key, v_sequence, p_payload);
    RETURN v_event_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_capture_decision_explain(
    p_project_id TEXT,
    p_source_type TEXT,
    p_source_id TEXT,
    p_source_version BIGINT,
    p_expected_source_version BIGINT,
    p_source_hash TEXT,
    p_schema_version TEXT,
    p_producer_version TEXT,
    p_summary JSONB,
    p_nodes JSONB,
    p_edges JSONB,
    p_snapshot_hash TEXT,
    p_ref_graph_hash TEXT,
    p_missing_links JSONB,
    p_redaction_class TEXT,
    p_retention_policy TEXT,
    p_retention_until TIMESTAMPTZ,
    p_authorization_scope JSONB,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_authorization_ref TEXT,
    p_reason TEXT,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT,
    p_causation_id TEXT,
    p_correlation_id TEXT,
    p_trace_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_command public.command_receipts%ROWTYPE;
    v_snapshot_id TEXT := 'explain-' || gen_random_uuid()::text;
    v_event_id TEXT;
    v_audit_id TEXT := 'audit-' || gen_random_uuid()::text;
    v_response JSONB;
    v_node JSONB;
    v_edge JSONB;
    v_tenant_id TEXT := COALESCE(p_authorization_scope->>'tenant_id', p_project_id);
BEGIN
    IF p_source_version <> p_expected_source_version THEN
        RAISE EXCEPTION 'EXPLAIN_SOURCE_VERSION_MISMATCH';
    END IF;
    IF jsonb_typeof(p_nodes) <> 'array' OR jsonb_array_length(p_nodes) = 0
       OR jsonb_array_length(p_nodes) > 256 THEN
        RAISE EXCEPTION 'EXPLAIN_SNAPSHOT_CONFLICT';
    END IF;
    IF jsonb_typeof(p_edges) <> 'array' OR jsonb_array_length(p_edges) > 512 THEN
        RAISE EXCEPTION 'EXPLAIN_SNAPSHOT_CONFLICT';
    END IF;
    PERFORM public.hermes_p3_explain_secret_guard(COALESCE(p_summary,'{}'::jsonb));
    PERFORM public.hermes_p3_explain_secret_guard(COALESCE(p_nodes,'[]'::jsonb));
    PERFORM public.hermes_p3_explain_secret_guard(COALESCE(p_edges,'[]'::jsonb));
    PERFORM public.hermes_p3_explain_secret_guard(COALESCE(p_authorization_scope,'{}'::jsonb));

    v_command := public.hermes_p3_explain_begin_command(
        p_project_id,'decision_explain.capture',
        p_command_id,p_idempotency_key,p_payload_hash
    );
    IF v_command.status = 'APPLIED' THEN
        RETURN v_command.result->'response';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_edges) e
        WHERE e->>'from_node_id' = e->>'to_node_id'
    ) THEN
        RAISE EXCEPTION 'EXPLAIN_SNAPSHOT_CONFLICT';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_edges) e
        WHERE NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_nodes) n
            WHERE n->>'node_id' = e->>'from_node_id'
        )
        OR NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_nodes) n
            WHERE n->>'node_id' = e->>'to_node_id'
        )
    ) THEN
        RAISE EXCEPTION 'MISSING_IMMUTABLE_FACT_LINK';
    END IF;
    IF EXISTS (
        SELECT node_id FROM (
            SELECT n->>'node_id' AS node_id FROM jsonb_array_elements(p_nodes) n
        ) x GROUP BY node_id HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'EXPLAIN_SNAPSHOT_CONFLICT';
    END IF;

    IF p_fault_point = 'after_snapshot_before_event' THEN
        RAISE EXCEPTION 'INJECTED_P3_EXPLAIN_CRASH_AFTER_SNAPSHOT';
    END IF;

    v_event_id := public.hermes_p3_explain_append_event(
        p_project_id,
        p_project_id,
        p_command_id,
        'decision.explain_recorded',
        p_actor_type,
        p_actor_id,
        jsonb_build_object(
            'snapshot_id',v_snapshot_id,
            'source_type',p_source_type,
            'source_id',p_source_id,
            'source_version',p_source_version,
            'snapshot_hash',p_snapshot_hash,
            'ref_graph_hash',p_ref_graph_hash,
            'missing_link_count',jsonb_array_length(COALESCE(p_missing_links,'[]'::jsonb)),
            'trace_id',COALESCE(p_trace_id,p_command_id),
            'redaction_class',p_redaction_class
        ),
        COALESCE(p_correlation_id,p_command_id)
    );

    INSERT INTO public.decision_explain_snapshots(
        snapshot_id,project_id,tenant_id,source_type,source_id,source_version,
        source_hash,schema_version,producer_version,snapshot_hash,ref_graph_hash,
        summary,missing_links,redaction_class,retention_policy,retention_until,
        authorization_scope,actor_type,actor_id,authorization_ref,reason,
        command_id,event_id,idempotency_key,causation_id,correlation_id,trace_id
    ) VALUES (
        v_snapshot_id,p_project_id,v_tenant_id,p_source_type,p_source_id,
        p_source_version,p_source_hash,p_schema_version,p_producer_version,
        p_snapshot_hash,p_ref_graph_hash,COALESCE(p_summary,'{}'::jsonb),
        COALESCE(p_missing_links,'[]'::jsonb),p_redaction_class,p_retention_policy,
        p_retention_until,COALESCE(p_authorization_scope,'{}'::jsonb),
        p_actor_type,p_actor_id,p_authorization_ref,p_reason,p_command_id,
        v_event_id,p_idempotency_key,p_causation_id,
        COALESCE(p_correlation_id,p_command_id),COALESCE(p_trace_id,p_command_id)
    );

    FOR v_node IN SELECT * FROM jsonb_array_elements(p_nodes)
    LOOP
        INSERT INTO public.decision_explain_nodes(
            snapshot_id,node_id,node_type,ref_id,ref_version,ref_hash,status,
            missing_reason,safe_summary,sort_key
        ) VALUES (
            v_snapshot_id,v_node->>'node_id',v_node->>'node_type',
            COALESCE(v_node->>'ref_id',''),COALESCE((v_node->>'ref_version')::bigint,0),
            NULLIF(v_node->>'ref_hash',''),v_node->>'status',
            COALESCE(v_node->>'missing_reason',''),
            COALESCE(v_node->'safe_summary','{}'::jsonb),
            v_node->>'node_id'
        );
    END LOOP;

    FOR v_edge IN SELECT * FROM jsonb_array_elements(p_edges)
    LOOP
        INSERT INTO public.decision_explain_edges(
            snapshot_id,from_node_id,to_node_id,relation,sort_key
        ) VALUES (
            v_snapshot_id,v_edge->>'from_node_id',v_edge->>'to_node_id',
            v_edge->>'relation',
            (v_edge->>'from_node_id') || '|' || (v_edge->>'to_node_id') || '|' || (v_edge->>'relation')
        );
    END LOOP;

    IF p_fault_point = 'after_event_before_audit' THEN
        RAISE EXCEPTION 'INJECTED_P3_EXPLAIN_CRASH_AFTER_EVENT';
    END IF;

    INSERT INTO public.audit_trace_records(
        audit_id,project_id,tenant_id,trace_id,correlation_id,causation_id,
        aggregate_type,aggregate_id,aggregate_version,aggregate_hash,action,
        actor_type,actor_id,authorization_ref,redaction_class,safe_summary,
        retention_policy,retention_until,command_id,event_id,idempotency_key
    ) VALUES (
        v_audit_id,p_project_id,v_tenant_id,COALESCE(p_trace_id,p_command_id),
        COALESCE(p_correlation_id,p_command_id),p_causation_id,
        p_source_type,p_source_id,p_source_version,p_source_hash,
        'decision_explain.capture',p_actor_type,p_actor_id,p_authorization_ref,
        p_redaction_class,
        jsonb_build_object(
            'snapshot_id',v_snapshot_id,
            'snapshot_hash',p_snapshot_hash,
            'reason',p_reason,
            'missing_link_count',jsonb_array_length(COALESCE(p_missing_links,'[]'::jsonb))
        ),
        p_retention_policy,p_retention_until,p_command_id,v_event_id,p_idempotency_key
    );

    IF p_fault_point = 'after_audit_before_receipt' THEN
        RAISE EXCEPTION 'INJECTED_P3_EXPLAIN_CRASH_AFTER_AUDIT';
    END IF;

    v_response := jsonb_build_object(
        'result_code','DECISION_EXPLAIN_CAPTURED',
        'snapshot_id',v_snapshot_id,
        'snapshot_hash',p_snapshot_hash,
        'ref_graph_hash',p_ref_graph_hash,
        'missing_link_count',jsonb_array_length(COALESCE(p_missing_links,'[]'::jsonb)),
        'event_id',v_event_id,
        'audit_id',v_audit_id,
        'trace_id',COALESCE(p_trace_id,p_command_id)
    );
    PERFORM public.hermes_p3_explain_complete_command(
        p_command_id,'APPLIED',
        jsonb_build_object('response',v_response,'events',jsonb_build_array(v_event_id))
    );
    RETURN v_response;
EXCEPTION WHEN unique_violation THEN
    RAISE EXCEPTION 'EXPLAIN_SNAPSHOT_CONFLICT';
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_query_decision_explain(
    p_project_id TEXT,
    p_snapshot_id TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_authorization_scope JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_snapshot public.decision_explain_snapshots%ROWTYPE;
BEGIN
    IF p_actor_type NOT IN ('system_operator','control_plane','read_only','auditor','recovery_controller') THEN
        RAISE EXCEPTION 'AUDIT_QUERY_UNAUTHORIZED';
    END IF;
    SELECT * INTO v_snapshot
    FROM public.decision_explain_snapshots
    WHERE snapshot_id = p_snapshot_id;
    IF NOT FOUND OR v_snapshot.project_id <> p_project_id THEN
        RAISE EXCEPTION 'TRACE_SCOPE_MISMATCH';
    END IF;
    IF v_snapshot.retention_until <= clock_timestamp() THEN
        RAISE EXCEPTION 'RETENTION_REDACTION_VIOLATION';
    END IF;
    IF COALESCE(p_authorization_scope->>'tenant_id', v_snapshot.tenant_id) <> v_snapshot.tenant_id
       OR COALESCE(p_authorization_scope->>'project_id', p_project_id) <> v_snapshot.project_id THEN
        RAISE EXCEPTION 'AUDIT_QUERY_UNAUTHORIZED';
    END IF;
    RETURN jsonb_build_object(
        'snapshot',to_jsonb(v_snapshot),
        'nodes',COALESCE((
            SELECT jsonb_agg(to_jsonb(n) ORDER BY n.sort_key)
            FROM public.decision_explain_nodes n
            WHERE n.snapshot_id = p_snapshot_id
        ),'[]'::jsonb),
        'edges',COALESCE((
            SELECT jsonb_agg(to_jsonb(e) ORDER BY e.sort_key)
            FROM public.decision_explain_edges e
            WHERE e.snapshot_id = p_snapshot_id
        ),'[]'::jsonb),
        'audit',COALESCE((
            SELECT jsonb_agg(to_jsonb(a) ORDER BY a.created_at, a.audit_id)
            FROM public.audit_trace_records a
            WHERE a.command_id = v_snapshot.command_id
        ),'[]'::jsonb)
    );
END;
$$;

ALTER TABLE public.decision_explain_snapshots OWNER TO hermes_p3_explain_owner;
ALTER TABLE public.decision_explain_nodes OWNER TO hermes_p3_explain_owner;
ALTER TABLE public.decision_explain_edges OWNER TO hermes_p3_explain_owner;
ALTER TABLE public.audit_trace_records OWNER TO hermes_p3_explain_owner;
ALTER FUNCTION public.hermes_p3_explain_reject_append_only_change() OWNER TO hermes_p3_explain_owner;
ALTER FUNCTION public.hermes_p3_explain_secret_guard(JSONB) OWNER TO hermes_p3_explain_owner;
ALTER FUNCTION public.hermes_p3_explain_begin_command(TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_p3_explain_owner;
ALTER FUNCTION public.hermes_p3_explain_complete_command(TEXT,TEXT,JSONB) OWNER TO hermes_p3_explain_owner;
ALTER FUNCTION public.hermes_p3_explain_append_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) OWNER TO hermes_p3_explain_owner;
ALTER FUNCTION public.hermes_capture_decision_explain(TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,JSONB,JSONB,JSONB,TEXT,TEXT,JSONB,TEXT,TEXT,TIMESTAMPTZ,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_p3_explain_owner;
ALTER FUNCTION public.hermes_query_decision_explain(TEXT,TEXT,TEXT,TEXT,JSONB) OWNER TO hermes_p3_explain_owner;

GRANT SELECT, INSERT, UPDATE ON public.command_receipts TO hermes_p3_explain_owner;
GRANT SELECT, INSERT ON public.event_log, public.outbox_messages TO hermes_p3_explain_owner;
GRANT SELECT, INSERT, UPDATE ON public.decision_explain_snapshots TO hermes_p3_explain_owner;
GRANT SELECT, INSERT ON public.decision_explain_nodes, public.decision_explain_edges,
    public.audit_trace_records TO hermes_p3_explain_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_p3_explain_owner;

GRANT SELECT ON public.decision_explain_snapshots, public.decision_explain_nodes,
    public.decision_explain_edges, public.audit_trace_records
TO hermes_explain_query_runtime, hermes_read_only_runtime;
GRANT SELECT ON public.audit_trace_records TO hermes_metrics_runtime;

REVOKE ALL ON public.decision_explain_snapshots, public.decision_explain_nodes,
    public.decision_explain_edges, public.audit_trace_records
FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE ON public.decision_explain_snapshots,
    public.decision_explain_nodes, public.decision_explain_edges,
    public.audit_trace_records
FROM hermes_explain_capture_runtime, hermes_explain_query_runtime,
     hermes_metrics_runtime, hermes_read_only_runtime, hermes_worker_runtime,
     hermes_verifier_runtime, hermes_scheduler_runtime, hermes_planner_runtime,
     hermes_control_plane_runtime, PUBLIC;

REVOKE ALL ON FUNCTION public.hermes_p3_explain_reject_append_only_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_explain_secret_guard(JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_explain_begin_command(TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_explain_complete_command(TEXT,TEXT,JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_explain_append_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_capture_decision_explain(TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,JSONB,JSONB,JSONB,TEXT,TEXT,JSONB,TEXT,TEXT,TIMESTAMPTZ,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_query_decision_explain(TEXT,TEXT,TEXT,TEXT,JSONB) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.hermes_capture_decision_explain(TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,JSONB,JSONB,JSONB,TEXT,TEXT,JSONB,TEXT,TEXT,TIMESTAMPTZ,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
TO hermes_explain_capture_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_query_decision_explain(TEXT,TEXT,TEXT,TEXT,JSONB)
TO hermes_explain_query_runtime, hermes_read_only_runtime;

REVOKE EXECUTE ON FUNCTION public.hermes_capture_decision_explain(TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,JSONB,JSONB,JSONB,TEXT,TEXT,JSONB,TEXT,TEXT,TIMESTAMPTZ,JSONB,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
FROM hermes_worker_runtime, hermes_verifier_runtime, hermes_scheduler_runtime,
     hermes_planner_runtime, hermes_execution_runtime, hermes_control_plane_runtime,
     hermes_metrics_runtime, hermes_read_only_runtime, PUBLIC;
REVOKE EXECUTE ON FUNCTION public.hermes_query_decision_explain(TEXT,TEXT,TEXT,TEXT,JSONB)
FROM hermes_worker_runtime, hermes_verifier_runtime, hermes_scheduler_runtime,
     hermes_planner_runtime, hermes_execution_runtime, PUBLIC;

REVOKE CREATE ON SCHEMA public FROM hermes_explain_capture_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_explain_query_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_metrics_runtime;

COMMENT ON TABLE public.decision_explain_snapshots IS
'P3-4 immutable Decision Explain snapshots captured from versioned facts; query-time recomputation with newer rules is forbidden.';
COMMENT ON TABLE public.decision_explain_nodes IS
'P3-4 immutable explain reference graph nodes with explicit PRESENT/MISSING/REDACTED state.';
COMMENT ON TABLE public.decision_explain_edges IS
'P3-4 immutable explain reference graph edges; missing links are explicit and never fabricated.';
COMMENT ON TABLE public.audit_trace_records IS
'P3-4 immutable audit/trace records linking actor, authorization, command, event, correlation, causation and trace refs.';
