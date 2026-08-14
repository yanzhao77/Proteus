-- P3-2: Checkpoint + Replay + Reconcile authority overlay.
-- Hermes remains authoritative relational state + Event Log + Outbox, not full
-- Event Sourcing. Replay writes isolated generations/projections only.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_replay_reconcile_owner') THEN
        CREATE ROLE hermes_replay_reconcile_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_replay_runtime') THEN
        CREATE ROLE hermes_replay_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_reconcile_runtime') THEN
        CREATE ROLE hermes_reconcile_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_reconcile_apply_runtime') THEN
        CREATE ROLE hermes_reconcile_apply_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_checkpoint_hash(
    p_consumer_id TEXT,
    p_stream_name TEXT,
    p_partition_key TEXT,
    p_generation_id TEXT,
    p_last_sequence BIGINT,
    p_consumer_version TEXT,
    p_schema_version TEXT,
    p_projection_digest TEXT,
    p_previous_checkpoint_id TEXT
) RETURNS TEXT
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
    SELECT 'sha256:' || encode(public.digest(convert_to(concat_ws('|',
        p_consumer_id, p_stream_name, p_partition_key, p_generation_id,
        p_last_sequence::text, p_consumer_version, p_schema_version,
        p_projection_digest, COALESCE(p_previous_checkpoint_id, '')
    ), 'UTF8'), 'sha256'), 'hex')
$$;

ALTER TABLE public.consumer_checkpoints
    ADD COLUMN IF NOT EXISTS stream_name TEXT NOT NULL DEFAULT 'hermes.runtime.events',
    ADD COLUMN IF NOT EXISTS generation_id TEXT NOT NULL DEFAULT 'generation-production',
    ADD COLUMN IF NOT EXISTS consumer_version TEXT NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS checkpoint_schema_version TEXT NOT NULL DEFAULT '1.0',
    ADD COLUMN IF NOT EXISTS projection_digest TEXT NOT NULL DEFAULT 'sha256:empty',
    ADD COLUMN IF NOT EXISTS checkpoint_hash TEXT,
    ADD COLUMN IF NOT EXISTS checkpoint_version BIGINT NOT NULL DEFAULT 1 CHECK (checkpoint_version >= 1),
    ADD COLUMN IF NOT EXISTS checkpoint_status TEXT NOT NULL DEFAULT 'CURRENT'
        CHECK (checkpoint_status IN ('CURRENT','CORRUPT','SUPERSEDED','REPLAY_CANDIDATE')),
    ADD COLUMN IF NOT EXISTS previous_checkpoint_id TEXT,
    ADD COLUMN IF NOT EXISTS advanced_at TIMESTAMPTZ NOT NULL DEFAULT now();

UPDATE public.consumer_checkpoints
SET checkpoint_hash = public.hermes_p3_checkpoint_hash(
        consumer_id, stream_name, partition_key, generation_id, last_sequence,
        consumer_version, checkpoint_schema_version, projection_digest,
        previous_checkpoint_id
    )
WHERE checkpoint_hash IS NULL;

ALTER TABLE public.consumer_checkpoints
    ALTER COLUMN checkpoint_hash SET NOT NULL;

CREATE OR REPLACE FUNCTION public.hermes_p3_set_checkpoint_hash()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF TG_OP = 'INSERT'
       OR NEW.checkpoint_hash IS NULL
       OR NEW.checkpoint_hash = OLD.checkpoint_hash THEN
        NEW.checkpoint_hash := public.hermes_p3_checkpoint_hash(
            NEW.consumer_id, NEW.stream_name, NEW.partition_key, NEW.generation_id,
            NEW.last_sequence, NEW.consumer_version, NEW.checkpoint_schema_version,
            NEW.projection_digest, NEW.previous_checkpoint_id
        );
    END IF;
    IF TG_OP = 'UPDATE'
       AND NEW.last_sequence < OLD.last_sequence
       AND NEW.last_sequence <> 0
       AND NOT pg_has_role(session_user, 'pg_database_owner', 'MEMBER') THEN
        RAISE EXCEPTION 'CHECKPOINT_CANNOT_REWIND';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS consumer_checkpoints_p3_hash ON public.consumer_checkpoints;
CREATE TRIGGER consumer_checkpoints_p3_hash
BEFORE INSERT OR UPDATE ON public.consumer_checkpoints
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_set_checkpoint_hash();

CREATE TABLE IF NOT EXISTS public.consumer_checkpoint_versions (
    checkpoint_id TEXT PRIMARY KEY,
    consumer_id TEXT NOT NULL,
    stream_name TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    generation_id TEXT NOT NULL,
    last_sequence BIGINT NOT NULL CHECK (last_sequence >= 0),
    previous_checkpoint_id TEXT,
    consumer_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    projection_digest TEXT NOT NULL CHECK (projection_digest LIKE 'sha256:%'),
    checkpoint_hash TEXT NOT NULL CHECK (checkpoint_hash LIKE 'sha256:%'),
    checkpoint_version BIGINT NOT NULL CHECK (checkpoint_version >= 1),
    status TEXT NOT NULL CHECK (status IN ('CURRENT','CORRUPT','SUPERSEDED','REPLAY_CANDIDATE')),
    command_id TEXT REFERENCES public.command_receipts(command_id),
    event_id TEXT REFERENCES public.event_log(event_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (consumer_id, stream_name, partition_key, generation_id, checkpoint_version)
);

CREATE TABLE IF NOT EXISTS public.replay_generation_pointers (
    consumer_id TEXT NOT NULL,
    stream_name TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    current_generation_id TEXT NOT NULL,
    pointer_version BIGINT NOT NULL DEFAULT 1 CHECK (pointer_version >= 1),
    activated_by_session_id TEXT,
    activated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (consumer_id, stream_name, partition_key)
);

CREATE TABLE IF NOT EXISTS public.replay_generations (
    generation_id TEXT PRIMARY KEY,
    consumer_id TEXT NOT NULL,
    stream_name TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    source_generation_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('BUILDING','VERIFIED','ACTIVATED','FAILED','SUPERSEDED')
    ),
    start_sequence BIGINT NOT NULL CHECK (start_sequence >= 1),
    end_sequence BIGINT NOT NULL CHECK (end_sequence >= start_sequence),
    event_count BIGINT NOT NULL DEFAULT 0 CHECK (event_count >= 0),
    projection_digest TEXT NOT NULL DEFAULT 'sha256:empty' CHECK (projection_digest LIKE 'sha256:%'),
    failure_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    verified_at TIMESTAMPTZ,
    activated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.replay_sessions (
    replay_session_id TEXT PRIMARY KEY,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    consumer_id TEXT NOT NULL,
    stream_name TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    source_generation_id TEXT NOT NULL,
    target_generation_id TEXT NOT NULL REFERENCES public.replay_generations(generation_id),
    start_sequence BIGINT NOT NULL CHECK (start_sequence >= 1),
    end_sequence BIGINT NOT NULL CHECK (end_sequence >= start_sequence),
    consumer_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    replay_mode TEXT NOT NULL CHECK (
        replay_mode IN ('READ_MODEL_REBUILD','IDEMPOTENT_CONSUMER_REPLAY','AUTHORITY_AUDIT')
    ),
    dry_run BOOLEAN NOT NULL DEFAULT false,
    status TEXT NOT NULL CHECK (
        status IN ('REQUESTED','VALIDATED','RUNNING','VERIFIED','ACTIVATED','FAILED','CANCELLED','SUPERSEDED')
    ),
    version BIGINT NOT NULL CHECK (version >= 1),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    authorization_ref TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK (payload_hash LIKE 'sha256:%'),
    result_digest TEXT NOT NULL DEFAULT 'sha256:empty' CHECK (result_digest LIKE 'sha256:%'),
    event_count BIGINT NOT NULL DEFAULT 0 CHECK (event_count >= 0),
    failure_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    verified_at TIMESTAMPTZ,
    activated_at TIMESTAMPTZ,
    UNIQUE (consumer_id, stream_name, partition_key, target_generation_id)
);

CREATE TABLE IF NOT EXISTS public.replay_shadow_projection_events (
    generation_id TEXT NOT NULL REFERENCES public.replay_generations(generation_id),
    event_id TEXT NOT NULL REFERENCES public.event_log(event_id),
    partition_key TEXT NOT NULL,
    sequence BIGINT NOT NULL,
    event_type TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    event_digest TEXT NOT NULL CHECK (event_digest LIKE 'sha256:%'),
    processing_result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (generation_id, event_id),
    UNIQUE (generation_id, partition_key, sequence)
);

CREATE TABLE IF NOT EXISTS public.reconcile_findings (
    finding_id TEXT PRIMARY KEY,
    finding_kind TEXT NOT NULL CHECK (
        finding_kind IN (
            'CHECKPOINT_AHEAD','CHECKPOINT_CORRUPT','EVENT_GAP','OUTBOX_MISSING',
            'OUTBOX_ORPHANED','INBOX_EFFECT_MISSING','EFFECT_WITHOUT_CHECKPOINT',
            'READ_MODEL_DRIFT','UNSUPPORTED_SCHEMA','DLQ_PENDING',
            'AUTHORITY_EVENT_MISMATCH'
        )
    ),
    scope_id TEXT NOT NULL,
    scope_hash TEXT NOT NULL CHECK (scope_hash LIKE 'sha256:%'),
    consumer_id TEXT,
    stream_name TEXT,
    partition_key TEXT,
    event_id TEXT,
    observed_sequence BIGINT,
    observed_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    finding_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (
        status IN ('OPEN','PLANNED','RESOLVED','BLOCKED','SUPERSEDED')
    ),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version >= 1),
    command_id TEXT REFERENCES public.command_receipts(command_id),
    event_id_recorded TEXT REFERENCES public.event_log(event_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS reconcile_findings_one_open_scope
    ON public.reconcile_findings(finding_kind, scope_hash)
    WHERE status IN ('OPEN','PLANNED','BLOCKED');

CREATE TABLE IF NOT EXISTS public.reconcile_plans (
    plan_id TEXT PRIMARY KEY,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    authorization_ref TEXT NOT NULL,
    dry_run BOOLEAN NOT NULL,
    status TEXT NOT NULL DEFAULT 'PLANNED' CHECK (
        status IN ('PLANNED','APPLIED','STALE','FAILED','SUPERSEDED')
    ),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version >= 1),
    observed_versions JSONB NOT NULL,
    repair_actions JSONB NOT NULL,
    plan_hash TEXT NOT NULL CHECK (plan_hash LIKE 'sha256:%'),
    expires_at TIMESTAMPTZ NOT NULL,
    applied_at TIMESTAMPTZ,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.reconcile_plan_findings (
    plan_id TEXT NOT NULL REFERENCES public.reconcile_plans(plan_id),
    finding_id TEXT NOT NULL REFERENCES public.reconcile_findings(finding_id),
    finding_version BIGINT NOT NULL,
    PRIMARY KEY (plan_id, finding_id)
);

CREATE TABLE IF NOT EXISTS public.reconcile_plan_repairs (
    repair_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES public.reconcile_plans(plan_id),
    repair_action TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PLANNED','APPLIED','BLOCKED','FAILED')),
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.hermes_p3_reject_history_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS consumer_checkpoint_versions_immutable ON public.consumer_checkpoint_versions;
CREATE TRIGGER consumer_checkpoint_versions_immutable
BEFORE UPDATE OR DELETE ON public.consumer_checkpoint_versions
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_reject_history_change();

DROP TRIGGER IF EXISTS replay_shadow_projection_events_immutable ON public.replay_shadow_projection_events;
CREATE TRIGGER replay_shadow_projection_events_immutable
BEFORE UPDATE OR DELETE ON public.replay_shadow_projection_events
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_reject_history_change();

DROP TRIGGER IF EXISTS reconcile_plan_findings_immutable ON public.reconcile_plan_findings;
CREATE TRIGGER reconcile_plan_findings_immutable
BEFORE UPDATE OR DELETE ON public.reconcile_plan_findings
FOR EACH ROW EXECUTE FUNCTION public.hermes_p3_reject_history_change();

CREATE OR REPLACE FUNCTION public.hermes_p3_payload_hash(p_payload JSONB)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
    SELECT 'sha256:' || encode(public.digest(convert_to(p_payload::text, 'UTF8'), 'sha256'), 'hex')
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_append_event(
    p_command_id TEXT,
    p_project_id TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_event_type TEXT,
    p_payload JSONB,
    p_fault_point TEXT DEFAULT NULL
) RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_event_id TEXT;
    v_sequence BIGINT;
BEGIN
    v_event_id := 'evt-' || gen_random_uuid()::text;
    INSERT INTO public.event_log(
        event_id,event_type,schema_version,producer_type,producer_id,
        project_id,partition_key,command_id,correlation_id,payload
    ) VALUES (
        v_event_id,p_event_type,'1.0',p_actor_type,p_actor_id,
        p_project_id,p_project_id,p_command_id,p_command_id,p_payload
    ) RETURNING sequence INTO v_sequence;
    IF p_fault_point = 'after_event_before_outbox' THEN
        RAISE EXCEPTION 'INJECTED_P3_REPLAY_CRASH_AFTER_EVENT';
    END IF;
    INSERT INTO public.outbox_messages(message_id,event_id,topic,partition_key,sequence,payload)
    VALUES ('msg-' || gen_random_uuid()::text,v_event_id,'hermes.runtime.events',
            p_project_id,v_sequence,p_payload);
    IF p_fault_point = 'after_outbox_before_receipt' THEN
        RAISE EXCEPTION 'INJECTED_P3_REPLAY_CRASH_AFTER_OUTBOX';
    END IF;
    RETURN v_event_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_complete_command(
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
    SET status = p_status, result = p_result, completed_at = now()
    WHERE command_id = p_command_id AND status = 'PROCESSING';
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_assert_authority(
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_authorization_ref TEXT
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF p_actor_type NOT IN ('system_operator','control_plane','recovery_controller')
       OR NULLIF(btrim(p_actor_id), '') IS NULL
       OR NULLIF(btrim(p_authorization_ref), '') IS NULL THEN
        RAISE EXCEPTION 'RECONCILE_AUTHORITY_MISMATCH';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_request_replay_session(
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_replay_session_id TEXT,
    p_consumer_id TEXT,
    p_stream_name TEXT,
    p_partition_key TEXT,
    p_source_generation_id TEXT,
    p_target_generation_id TEXT,
    p_start_sequence BIGINT,
    p_end_sequence BIGINT,
    p_consumer_version TEXT,
    p_schema_version TEXT,
    p_replay_mode TEXT,
    p_dry_run BOOLEAN,
    p_expected_checkpoint_version BIGINT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_reason TEXT,
    p_authorization_ref TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_hash TEXT;
    v_existing public.command_receipts%ROWTYPE;
    v_checkpoint public.consumer_checkpoints%ROWTYPE;
    v_result JSONB;
    v_event_id TEXT;
BEGIN
    PERFORM public.hermes_p3_assert_authority(p_actor_type,p_actor_id,p_authorization_ref);
    IF p_start_sequence < 1 OR p_end_sequence < p_start_sequence THEN
        RAISE EXCEPTION 'REPLAY_RANGE_INVALID';
    END IF;
    IF p_replay_mode NOT IN ('READ_MODEL_REBUILD','IDEMPOTENT_CONSUMER_REPLAY','AUTHORITY_AUDIT') THEN
        RAISE EXCEPTION 'REPLAY_MODE_UNSUPPORTED';
    END IF;
    v_hash := public.hermes_p3_payload_hash(jsonb_build_object(
        'command_type','replay.request','replay_session_id',p_replay_session_id,
        'consumer_id',p_consumer_id,'stream_name',p_stream_name,
        'partition_key',p_partition_key,'source_generation_id',p_source_generation_id,
        'target_generation_id',p_target_generation_id,'start_sequence',p_start_sequence,
        'end_sequence',p_end_sequence,'consumer_version',p_consumer_version,
        'schema_version',p_schema_version,'replay_mode',p_replay_mode,
        'dry_run',p_dry_run,'expected_checkpoint_version',p_expected_checkpoint_version
    ));
    INSERT INTO public.command_receipts(
        command_id,project_id,command_type,idempotency_key,request_hash,status,result
    ) VALUES (p_command_id,p_partition_key,'replay.request',p_idempotency_key,v_hash,'PROCESSING','{}'::jsonb)
    ON CONFLICT DO NOTHING;
    IF NOT FOUND THEN
        SELECT * INTO v_existing FROM public.command_receipts WHERE command_id = p_command_id;
        IF v_existing.request_hash <> v_hash THEN RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT'; END IF;
        IF v_existing.status = 'APPLIED' THEN RETURN v_existing.result; END IF;
        RAISE EXCEPTION 'COMMAND_ALREADY_PROCESSING';
    END IF;

    SELECT * INTO v_checkpoint FROM public.consumer_checkpoints
    WHERE consumer_id = p_consumer_id AND partition_key = p_partition_key FOR UPDATE;
    IF FOUND AND v_checkpoint.checkpoint_version <> p_expected_checkpoint_version THEN
        RAISE EXCEPTION 'CHECKPOINT_VERSION_CONFLICT';
    END IF;
    IF NOT FOUND AND p_expected_checkpoint_version <> 0 THEN
        RAISE EXCEPTION 'CHECKPOINT_NOT_FOUND';
    END IF;

    INSERT INTO public.replay_generations(
        generation_id,consumer_id,stream_name,partition_key,source_generation_id,
        status,start_sequence,end_sequence
    ) VALUES (
        p_target_generation_id,p_consumer_id,p_stream_name,p_partition_key,
        p_source_generation_id,'BUILDING',p_start_sequence,p_end_sequence
    );
    INSERT INTO public.replay_sessions(
        replay_session_id,command_id,consumer_id,stream_name,partition_key,
        source_generation_id,target_generation_id,start_sequence,end_sequence,
        consumer_version,schema_version,replay_mode,dry_run,status,version,
        actor_type,actor_id,reason,authorization_ref,payload_hash
    ) VALUES (
        p_replay_session_id,p_command_id,p_consumer_id,p_stream_name,p_partition_key,
        p_source_generation_id,p_target_generation_id,p_start_sequence,p_end_sequence,
        p_consumer_version,p_schema_version,p_replay_mode,p_dry_run,'REQUESTED',1,
        p_actor_type,p_actor_id,p_reason,p_authorization_ref,v_hash
    );
    v_result := jsonb_build_object(
        'result_code','REPLAY_REQUESTED','replay_session_id',p_replay_session_id,
        'target_generation_id',p_target_generation_id,'version',1
    );
    v_event_id := public.hermes_p3_append_event(
        p_command_id,p_partition_key,p_actor_type,p_actor_id,'replay.requested',
        v_result
    );
    PERFORM public.hermes_p3_complete_command(p_command_id,'APPLIED',v_result || jsonb_build_object('event_id',v_event_id));
    RETURN v_result || jsonb_build_object('event_id',v_event_id);
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_execute_replay_session(
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_replay_session_id TEXT,
    p_expected_replay_version BIGINT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_session public.replay_sessions%ROWTYPE;
    v_hash TEXT;
    v_existing public.command_receipts%ROWTYPE;
    v_sequence BIGINT;
    v_event public.event_log%ROWTYPE;
    v_count BIGINT := 0;
    v_digest TEXT;
    v_result JSONB;
    v_event_id TEXT;
BEGIN
    SELECT * INTO v_session FROM public.replay_sessions
    WHERE replay_session_id = p_replay_session_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'REPLAY_SESSION_NOT_FOUND'; END IF;
    IF v_session.version <> p_expected_replay_version THEN RAISE EXCEPTION 'REPLAY_VERSION_CONFLICT'; END IF;
    IF v_session.status NOT IN ('REQUESTED','VALIDATED') THEN RAISE EXCEPTION 'REPLAY_STATE_CONFLICT'; END IF;
    v_hash := public.hermes_p3_payload_hash(jsonb_build_object(
        'command_type','replay.execute','replay_session_id',p_replay_session_id,
        'expected_replay_version',p_expected_replay_version
    ));
    INSERT INTO public.command_receipts(
        command_id,project_id,command_type,idempotency_key,request_hash,status,result
    ) VALUES (p_command_id,v_session.partition_key,'replay.execute',p_idempotency_key,v_hash,'PROCESSING','{}'::jsonb)
    ON CONFLICT DO NOTHING;
    IF NOT FOUND THEN
        SELECT * INTO v_existing FROM public.command_receipts WHERE command_id = p_command_id;
        IF v_existing.request_hash <> v_hash THEN RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT'; END IF;
        IF v_existing.status = 'APPLIED' THEN RETURN v_existing.result; END IF;
        RAISE EXCEPTION 'COMMAND_ALREADY_PROCESSING';
    END IF;

    UPDATE public.replay_sessions SET status='RUNNING', updated_at=now()
    WHERE replay_session_id = p_replay_session_id;
    IF p_fault_point = 'after_generation_before_processing' THEN
        RAISE EXCEPTION 'INJECTED_REPLAY_CRASH_AFTER_GENERATION';
    END IF;

    FOR v_sequence IN v_session.start_sequence..v_session.end_sequence LOOP
        SELECT * INTO v_event FROM public.event_log
        WHERE partition_key = v_session.partition_key AND sequence = v_sequence;
        IF NOT FOUND THEN
            UPDATE public.replay_sessions
            SET status='FAILED', version=version+1, failure_code='EVENT_GAP_DETECTED', updated_at=now()
            WHERE replay_session_id = p_replay_session_id;
            UPDATE public.replay_generations
            SET status='FAILED', failure_code='EVENT_GAP_DETECTED'
            WHERE generation_id = v_session.target_generation_id;
            v_result := jsonb_build_object(
                'result_code','REPLAY_FAILED','reason_code','EVENT_GAP_DETECTED',
                'replay_session_id',p_replay_session_id,
                'target_generation_id',v_session.target_generation_id,
                'failed_at_sequence',v_sequence,'version',v_session.version + 1
            );
            v_event_id := public.hermes_p3_append_event(
                p_command_id,v_session.partition_key,v_session.actor_type,v_session.actor_id,
                'replay.failed',v_result,p_fault_point
            );
            PERFORM public.hermes_p3_complete_command(p_command_id,'APPLIED',v_result || jsonb_build_object('event_id',v_event_id));
            RETURN v_result || jsonb_build_object('event_id',v_event_id);
        END IF;
        IF split_part(v_event.schema_version, '.', 1) <> '1' THEN
            PERFORM public.hermes_consumer_quarantine(
                v_session.consumer_id,v_event.event_id,v_event.partition_key,v_event.sequence,
                public.hermes_event_envelope(v_event.event_id),'UNSUPPORTED_SCHEMA',
                'unsupported schema during replay'
            );
            UPDATE public.replay_sessions
            SET status='FAILED', version=version+1, failure_code='EVENT_SCHEMA_UNSUPPORTED', updated_at=now()
            WHERE replay_session_id = p_replay_session_id;
            UPDATE public.replay_generations
            SET status='FAILED', failure_code='EVENT_SCHEMA_UNSUPPORTED'
            WHERE generation_id = v_session.target_generation_id;
            v_result := jsonb_build_object(
                'result_code','REPLAY_FAILED','reason_code','EVENT_SCHEMA_UNSUPPORTED',
                'replay_session_id',p_replay_session_id,
                'target_generation_id',v_session.target_generation_id,
                'failed_event_id',v_event.event_id,'version',v_session.version + 1
            );
            v_event_id := public.hermes_p3_append_event(
                p_command_id,v_session.partition_key,v_session.actor_type,v_session.actor_id,
                'replay.failed',v_result,p_fault_point
            );
            PERFORM public.hermes_p3_complete_command(p_command_id,'APPLIED',v_result || jsonb_build_object('event_id',v_event_id));
            RETURN v_result || jsonb_build_object('event_id',v_event_id);
        END IF;
        INSERT INTO public.replay_shadow_projection_events(
            generation_id,event_id,partition_key,sequence,event_type,schema_version,
            event_digest,processing_result
        ) VALUES (
            v_session.target_generation_id,v_event.event_id,v_event.partition_key,
            v_event.sequence,v_event.event_type,v_event.schema_version,
            public.hermes_p3_payload_hash(public.hermes_event_envelope(v_event.event_id)),
            jsonb_build_object('classification','REPLAYED','event_id',v_event.event_id)
        ) ON CONFLICT DO NOTHING;
        v_count := v_count + 1;
        IF p_fault_point = 'during_replay_sequence' AND v_sequence = v_session.start_sequence THEN
            RAISE EXCEPTION 'INJECTED_REPLAY_CRASH_DURING_SEQUENCE';
        END IF;
    END LOOP;

    v_digest := public.hermes_p3_payload_hash(jsonb_build_object(
        'generation_id',v_session.target_generation_id,
        'events',(SELECT jsonb_agg(jsonb_build_object('event_id',event_id,'sequence',sequence,'digest',event_digest) ORDER BY sequence)
                  FROM public.replay_shadow_projection_events
                  WHERE generation_id = v_session.target_generation_id)
    ));
    IF p_fault_point = 'after_replay_before_verify' THEN
        RAISE EXCEPTION 'INJECTED_REPLAY_CRASH_AFTER_REPLAY';
    END IF;
    UPDATE public.replay_generations
    SET status='VERIFIED', event_count=v_count, projection_digest=v_digest, verified_at=now()
    WHERE generation_id = v_session.target_generation_id;
    UPDATE public.replay_sessions
    SET status='VERIFIED', version=version+1, event_count=v_count,
        result_digest=v_digest, verified_at=now(), updated_at=now()
    WHERE replay_session_id = p_replay_session_id;
    v_result := jsonb_build_object(
        'result_code','REPLAY_VERIFIED','replay_session_id',p_replay_session_id,
        'target_generation_id',v_session.target_generation_id,'event_count',v_count,
        'projection_digest',v_digest,'version',v_session.version + 1
    );
    v_event_id := public.hermes_p3_append_event(
        p_command_id,v_session.partition_key,v_session.actor_type,v_session.actor_id,
        'replay.verified',v_result,p_fault_point
    );
    PERFORM public.hermes_p3_complete_command(p_command_id,'APPLIED',v_result || jsonb_build_object('event_id',v_event_id));
    RETURN v_result || jsonb_build_object('event_id',v_event_id);
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_activate_replay_generation(
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_replay_session_id TEXT,
    p_expected_replay_version BIGINT,
    p_authorization_ref TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_session public.replay_sessions%ROWTYPE;
    v_generation public.replay_generations%ROWTYPE;
    v_hash TEXT;
    v_existing public.command_receipts%ROWTYPE;
    v_result JSONB;
    v_event_id TEXT;
BEGIN
    SELECT * INTO v_session FROM public.replay_sessions
    WHERE replay_session_id = p_replay_session_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'REPLAY_SESSION_NOT_FOUND'; END IF;
    PERFORM public.hermes_p3_assert_authority(v_session.actor_type,v_session.actor_id,p_authorization_ref);
    IF v_session.version <> p_expected_replay_version THEN RAISE EXCEPTION 'REPLAY_VERSION_CONFLICT'; END IF;
    IF v_session.status <> 'VERIFIED' THEN RAISE EXCEPTION 'REPLAY_STATE_CONFLICT'; END IF;
    SELECT * INTO v_generation FROM public.replay_generations
    WHERE generation_id = v_session.target_generation_id FOR UPDATE;
    IF NOT FOUND OR v_generation.status <> 'VERIFIED' THEN RAISE EXCEPTION 'REPLAY_STATE_CONFLICT'; END IF;
    v_hash := public.hermes_p3_payload_hash(jsonb_build_object(
        'command_type','replay.activate','replay_session_id',p_replay_session_id,
        'expected_replay_version',p_expected_replay_version,'authorization_ref',p_authorization_ref
    ));
    INSERT INTO public.command_receipts(
        command_id,project_id,command_type,idempotency_key,request_hash,status,result
    ) VALUES (p_command_id,v_session.partition_key,'replay.activate',p_idempotency_key,v_hash,'PROCESSING','{}'::jsonb)
    ON CONFLICT DO NOTHING;
    IF NOT FOUND THEN
        SELECT * INTO v_existing FROM public.command_receipts WHERE command_id = p_command_id;
        IF v_existing.request_hash <> v_hash THEN RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT'; END IF;
        IF v_existing.status = 'APPLIED' THEN RETURN v_existing.result; END IF;
        RAISE EXCEPTION 'COMMAND_ALREADY_PROCESSING';
    END IF;
    INSERT INTO public.replay_generation_pointers(
        consumer_id,stream_name,partition_key,current_generation_id,
        pointer_version,activated_by_session_id
    ) VALUES (
        v_session.consumer_id,v_session.stream_name,v_session.partition_key,
        v_session.target_generation_id,1,p_replay_session_id
    )
    ON CONFLICT (consumer_id,stream_name,partition_key) DO UPDATE
    SET current_generation_id = EXCLUDED.current_generation_id,
        pointer_version = public.replay_generation_pointers.pointer_version + 1,
        activated_by_session_id = EXCLUDED.activated_by_session_id,
        activated_at = now();
    IF p_fault_point = 'after_activation_before_event' THEN
        RAISE EXCEPTION 'INJECTED_REPLAY_CRASH_AFTER_ACTIVATION';
    END IF;
    UPDATE public.replay_generations
    SET status='ACTIVATED', activated_at=now()
    WHERE generation_id = v_session.target_generation_id;
    UPDATE public.replay_sessions
    SET status='ACTIVATED', version=version+1, activated_at=now(), updated_at=now()
    WHERE replay_session_id = p_replay_session_id;
    v_result := jsonb_build_object(
        'result_code','REPLAY_ACTIVATED','replay_session_id',p_replay_session_id,
        'generation_id',v_session.target_generation_id,'version',v_session.version + 1
    );
    v_event_id := public.hermes_p3_append_event(
        p_command_id,v_session.partition_key,v_session.actor_type,v_session.actor_id,
        'replay.activated',v_result,p_fault_point
    );
    PERFORM public.hermes_p3_complete_command(p_command_id,'APPLIED',v_result || jsonb_build_object('event_id',v_event_id));
    RETURN v_result || jsonb_build_object('event_id',v_event_id);
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_p3_record_finding(
    p_command_id TEXT,
    p_scope_id TEXT,
    p_kind TEXT,
    p_consumer_id TEXT,
    p_stream_name TEXT,
    p_partition_key TEXT,
    p_event_id TEXT,
    p_observed_sequence BIGINT,
    p_observed_versions JSONB,
    p_detail JSONB
) RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_scope_hash TEXT;
    v_id TEXT;
BEGIN
    v_scope_hash := public.hermes_p3_payload_hash(jsonb_build_object(
        'kind',p_kind,'scope_id',p_scope_id,'consumer_id',p_consumer_id,
        'partition_key',p_partition_key,'event_id',p_event_id,
        'sequence',p_observed_sequence
    ));
    INSERT INTO public.reconcile_findings(
        finding_id,finding_kind,scope_id,scope_hash,consumer_id,stream_name,
        partition_key,event_id,observed_sequence,observed_versions,
        finding_detail,status,command_id
    ) VALUES (
        'finding-' || gen_random_uuid()::text,p_kind,p_scope_id,v_scope_hash,
        p_consumer_id,p_stream_name,p_partition_key,p_event_id,
        p_observed_sequence,p_observed_versions,p_detail,'OPEN',p_command_id
    )
    ON CONFLICT (finding_kind, scope_hash) WHERE status IN ('OPEN','PLANNED','BLOCKED')
    DO UPDATE SET created_at = public.reconcile_findings.created_at
    RETURNING finding_id INTO v_id;
    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_observe_reconcile_findings(
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_scope_id TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_reason TEXT,
    p_authorization_ref TEXT,
    p_consumer_id TEXT DEFAULT NULL,
    p_partition_key TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_hash TEXT;
    v_existing public.command_receipts%ROWTYPE;
    v_before BIGINT;
    v_after BIGINT;
    v_event_id TEXT;
    v_result JSONB;
BEGIN
    PERFORM public.hermes_p3_assert_authority(p_actor_type,p_actor_id,p_authorization_ref);
    v_hash := public.hermes_p3_payload_hash(jsonb_build_object(
        'command_type','reconcile.observe','scope_id',p_scope_id,
        'consumer_id',p_consumer_id,'partition_key',p_partition_key
    ));
    INSERT INTO public.command_receipts(
        command_id,project_id,command_type,idempotency_key,request_hash,status,result
    ) VALUES (p_command_id,p_scope_id,'reconcile.observe',p_idempotency_key,v_hash,'PROCESSING','{}'::jsonb)
    ON CONFLICT DO NOTHING;
    IF NOT FOUND THEN
        SELECT * INTO v_existing FROM public.command_receipts WHERE command_id = p_command_id;
        IF v_existing.request_hash <> v_hash THEN RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT'; END IF;
        IF v_existing.status = 'APPLIED' THEN RETURN v_existing.result; END IF;
        RAISE EXCEPTION 'COMMAND_ALREADY_PROCESSING';
    END IF;
    SELECT count(*) INTO v_before FROM public.reconcile_findings WHERE status IN ('OPEN','PLANNED','BLOCKED');

    PERFORM public.hermes_p3_record_finding(
        p_command_id,p_scope_id,'CHECKPOINT_AHEAD',c.consumer_id,c.stream_name,
        c.partition_key,NULL,c.last_sequence,
        jsonb_build_object('checkpoint_version',c.checkpoint_version),
        jsonb_build_object('last_sequence',c.last_sequence,'max_event_sequence',COALESCE(src.max_sequence,0))
    )
    FROM public.consumer_checkpoints c
    LEFT JOIN LATERAL (
        SELECT max(sequence) AS max_sequence FROM public.event_log e
        WHERE e.partition_key = c.partition_key
    ) src ON true
    WHERE (p_consumer_id IS NULL OR c.consumer_id = p_consumer_id)
      AND (p_partition_key IS NULL OR c.partition_key = p_partition_key)
      AND c.last_sequence > COALESCE(src.max_sequence,0);

    PERFORM public.hermes_p3_record_finding(
        p_command_id,p_scope_id,'CHECKPOINT_CORRUPT',c.consumer_id,c.stream_name,
        c.partition_key,NULL,c.last_sequence,
        jsonb_build_object('checkpoint_version',c.checkpoint_version),
        jsonb_build_object('stored_hash',c.checkpoint_hash)
    )
    FROM public.consumer_checkpoints c
    WHERE (p_consumer_id IS NULL OR c.consumer_id = p_consumer_id)
      AND (p_partition_key IS NULL OR c.partition_key = p_partition_key)
      AND c.checkpoint_hash <> public.hermes_p3_checkpoint_hash(
          c.consumer_id,c.stream_name,c.partition_key,c.generation_id,
          c.last_sequence,c.consumer_version,c.checkpoint_schema_version,
          c.projection_digest,c.previous_checkpoint_id
      );

    PERFORM public.hermes_p3_record_finding(
        p_command_id,p_scope_id,'EVENT_GAP',g.consumer_id,'hermes.runtime.events',
        g.partition_key,g.event_id,g.sequence,
        jsonb_build_object('gap_status',g.status),
        jsonb_build_object('expected_sequence',COALESCE(c.last_sequence,0)+1,'observed_sequence',g.sequence)
    )
    FROM public.consumer_pending_gaps g
    LEFT JOIN public.consumer_checkpoints c
      ON c.consumer_id = g.consumer_id AND c.partition_key = g.partition_key
    WHERE g.status IN ('PENDING','RECONCILE_REQUIRED')
      AND (p_consumer_id IS NULL OR g.consumer_id = p_consumer_id)
      AND (p_partition_key IS NULL OR g.partition_key = p_partition_key);

    PERFORM public.hermes_p3_record_finding(
        p_command_id,p_scope_id,'OUTBOX_MISSING',NULL,'hermes.runtime.events',
        e.partition_key,e.event_id,e.sequence,
        jsonb_build_object('event_type',e.event_type),
        jsonb_build_object('event_id',e.event_id)
    )
    FROM public.event_log e
    LEFT JOIN public.outbox_messages o ON o.event_id = e.event_id
    WHERE o.event_id IS NULL
      AND (p_partition_key IS NULL OR e.partition_key = p_partition_key);

    PERFORM public.hermes_p3_record_finding(
        p_command_id,p_scope_id,'INBOX_EFFECT_MISSING',i.consumer_id,'hermes.runtime.events',
        i.partition_key,i.event_id,i.sequence,
        jsonb_build_object('inbox_sequence',i.sequence),
        jsonb_build_object('event_id',i.event_id)
    )
    FROM public.consumer_inbox i
    LEFT JOIN public.consumer_effects ef ON ef.consumer_id = i.consumer_id AND ef.event_id = i.event_id
    WHERE ef.event_id IS NULL
      AND (p_consumer_id IS NULL OR i.consumer_id = p_consumer_id)
      AND (p_partition_key IS NULL OR i.partition_key = p_partition_key);

    PERFORM public.hermes_p3_record_finding(
        p_command_id,p_scope_id,'EFFECT_WITHOUT_CHECKPOINT',i.consumer_id,c.stream_name,
        i.partition_key,NULL,max(i.sequence),
        jsonb_build_object('checkpoint_version',c.checkpoint_version),
        jsonb_build_object('checkpoint',c.last_sequence,'contiguous_effect',max(i.sequence))
    )
    FROM public.consumer_inbox i
    JOIN public.consumer_checkpoints c USING (consumer_id, partition_key)
    WHERE (p_consumer_id IS NULL OR i.consumer_id = p_consumer_id)
      AND (p_partition_key IS NULL OR i.partition_key = p_partition_key)
    GROUP BY i.consumer_id,c.stream_name,i.partition_key,c.last_sequence,c.checkpoint_version
    HAVING max(i.sequence) > c.last_sequence
       AND NOT EXISTS (
           SELECT 1 FROM generate_series(c.last_sequence + 1, max(i.sequence)) s
           WHERE NOT EXISTS (
               SELECT 1 FROM public.consumer_inbox ii
               WHERE ii.consumer_id = i.consumer_id AND ii.partition_key = i.partition_key
                 AND ii.sequence = s
           )
       );

    PERFORM public.hermes_p3_record_finding(
        p_command_id,p_scope_id,'UNSUPPORTED_SCHEMA',q.consumer_id,'hermes.runtime.events',
        q.partition_key,q.event_id,q.sequence,
        jsonb_build_object('category',q.failure_category),
        jsonb_build_object('last_error',q.last_error)
    )
    FROM public.consumer_quarantine q
    WHERE q.status = 'OPEN' AND q.failure_category IN ('SCHEMA','UNSUPPORTED_SCHEMA','UNKNOWN_CRITICAL_VALUE')
      AND (p_consumer_id IS NULL OR q.consumer_id = p_consumer_id)
      AND (p_partition_key IS NULL OR q.partition_key = p_partition_key);

    PERFORM public.hermes_p3_record_finding(
        p_command_id,p_scope_id,'DLQ_PENDING',NULL,'hermes.runtime.events',
        d.partition_key,d.event_id,d.sequence,
        jsonb_build_object('category',d.failure_category),
        jsonb_build_object('last_error',d.last_error)
    )
    FROM public.outbox_delivery_dlq d
    WHERE d.status = 'OPEN'
      AND (p_partition_key IS NULL OR d.partition_key = p_partition_key);

    SELECT count(*) INTO v_after FROM public.reconcile_findings WHERE status IN ('OPEN','PLANNED','BLOCKED');
    v_result := jsonb_build_object('result_code','RECONCILE_OBSERVED','created_or_open_findings',v_after,'new_findings',GREATEST(v_after - v_before,0));
    v_event_id := public.hermes_p3_append_event(
        p_command_id,p_scope_id,p_actor_type,p_actor_id,'reconcile.finding_created',v_result
    );
    PERFORM public.hermes_p3_complete_command(p_command_id,'APPLIED',v_result || jsonb_build_object('event_id',v_event_id));
    RETURN v_result || jsonb_build_object('event_id',v_event_id);
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_create_reconcile_plan(
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_plan_id TEXT,
    p_finding_ids TEXT[],
    p_repair_actions TEXT[],
    p_dry_run BOOLEAN,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_reason TEXT,
    p_authorization_ref TEXT,
    p_expires_at TIMESTAMPTZ
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_hash TEXT;
    v_existing public.command_receipts%ROWTYPE;
    v_observed JSONB;
    v_actions JSONB;
    v_event_id TEXT;
    v_result JSONB;
    v_action TEXT;
    v_finding public.reconcile_findings%ROWTYPE;
    v_scope TEXT;
    v_observed_count INTEGER;
BEGIN
    PERFORM public.hermes_p3_assert_authority(p_actor_type,p_actor_id,p_authorization_ref);
    IF array_length(p_finding_ids,1) IS NULL THEN RAISE EXCEPTION 'RECONCILE_FINDING_REQUIRED'; END IF;
    FOREACH v_action IN ARRAY p_repair_actions LOOP
        IF v_action NOT IN (
            'REBUILD_READ_MODEL_GENERATION','REPLAY_IDEMPOTENT_CONSUMER_RANGE',
            'ADVANCE_CHECKPOINT_IF_EFFECT_CONTIGUOUS','REGENERATE_MISSING_OUTBOX_VIA_AUTHORITY',
            'REDRIVE_SUPPORTED_EVENT','MARK_UNSUPPORTED_SCHEMA_BLOCKED',
            'SUPERSEDE_STALE_PLAN'
        ) THEN RAISE EXCEPTION 'RECONCILE_REPAIR_NOT_WHITELISTED'; END IF;
    END LOOP;
    SELECT COALESCE(min(scope_id), 'reconcile') INTO v_scope
    FROM public.reconcile_findings WHERE finding_id = ANY(p_finding_ids);
    IF v_scope IS NULL THEN v_scope := 'reconcile'; END IF;
    SELECT jsonb_object_agg(finding_id, version) INTO v_observed
    FROM public.reconcile_findings
    WHERE finding_id = ANY(p_finding_ids) AND status IN ('OPEN','PLANNED','BLOCKED');
    SELECT count(*) INTO v_observed_count FROM jsonb_object_keys(COALESCE(v_observed, '{}'::jsonb));
    IF v_observed IS NULL OR v_observed_count <> array_length(p_finding_ids,1) THEN
        RAISE EXCEPTION 'RECONCILE_AUTHORITY_MISMATCH';
    END IF;
    v_actions := to_jsonb(p_repair_actions);
    v_hash := public.hermes_p3_payload_hash(jsonb_build_object(
        'plan_id',p_plan_id,'finding_ids',p_finding_ids,'repair_actions',p_repair_actions,
        'dry_run',p_dry_run,'observed_versions',v_observed
    ));
    INSERT INTO public.command_receipts(
        command_id,project_id,command_type,idempotency_key,request_hash,status,result
    ) VALUES (p_command_id,v_scope,'reconcile.plan',p_idempotency_key,v_hash,'PROCESSING','{}'::jsonb)
    ON CONFLICT DO NOTHING;
    IF NOT FOUND THEN
        SELECT * INTO v_existing FROM public.command_receipts WHERE command_id = p_command_id;
        IF v_existing.request_hash <> v_hash THEN RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT'; END IF;
        IF v_existing.status = 'APPLIED' THEN RETURN v_existing.result; END IF;
        RAISE EXCEPTION 'COMMAND_ALREADY_PROCESSING';
    END IF;
    INSERT INTO public.reconcile_plans(
        plan_id,command_id,actor_type,actor_id,reason,authorization_ref,dry_run,
        observed_versions,repair_actions,plan_hash,expires_at
    ) VALUES (
        p_plan_id,p_command_id,p_actor_type,p_actor_id,p_reason,p_authorization_ref,
        p_dry_run,v_observed,v_actions,v_hash,p_expires_at
    );
    FOR v_finding IN
        SELECT * FROM public.reconcile_findings
        WHERE finding_id = ANY(p_finding_ids)
        ORDER BY finding_id
    LOOP
        INSERT INTO public.reconcile_plan_findings(plan_id,finding_id,finding_version)
        VALUES (p_plan_id,v_finding.finding_id,v_finding.version);
        UPDATE public.reconcile_findings
        SET status='PLANNED', version=version+1
        WHERE finding_id = v_finding.finding_id AND status IN ('OPEN','BLOCKED');
    END LOOP;
    FOREACH v_action IN ARRAY p_repair_actions LOOP
        INSERT INTO public.reconcile_plan_repairs(repair_id,plan_id,repair_action,target_ref,status)
        VALUES ('repair-' || gen_random_uuid()::text,p_plan_id,v_action,array_to_string(p_finding_ids,','),'PLANNED');
    END LOOP;
    v_result := jsonb_build_object(
        'result_code', CASE WHEN p_dry_run THEN 'RECONCILE_DRY_RUN_PLANNED' ELSE 'RECONCILE_PLAN_CREATED' END,
        'plan_id',p_plan_id,'plan_hash',v_hash,'dry_run',p_dry_run,'version',1
    );
    v_event_id := public.hermes_p3_append_event(
        p_command_id,v_scope,p_actor_type,p_actor_id,'reconcile.plan_created',v_result
    );
    PERFORM public.hermes_p3_complete_command(p_command_id,'APPLIED',v_result || jsonb_build_object('event_id',v_event_id));
    RETURN v_result || jsonb_build_object('event_id',v_event_id);
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_apply_reconcile_plan(
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_plan_id TEXT,
    p_expected_plan_version BIGINT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_reason TEXT,
    p_authorization_ref TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_plan public.reconcile_plans%ROWTYPE;
    v_hash TEXT;
    v_existing public.command_receipts%ROWTYPE;
    v_finding public.reconcile_findings%ROWTYPE;
    v_checkpoint public.consumer_checkpoints%ROWTYPE;
    v_contiguous BIGINT;
    v_new_hash TEXT;
    v_checkpoint_id TEXT;
    v_resolved INTEGER := 0;
    v_blocked INTEGER := 0;
    v_event_id TEXT;
    v_result JSONB;
BEGIN
    PERFORM public.hermes_p3_assert_authority(p_actor_type,p_actor_id,p_authorization_ref);
    SELECT * INTO v_plan FROM public.reconcile_plans WHERE plan_id = p_plan_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'RECONCILE_PLAN_NOT_FOUND'; END IF;
    IF v_plan.version <> p_expected_plan_version OR v_plan.status <> 'PLANNED' OR v_plan.expires_at <= now() THEN
        RAISE EXCEPTION 'RECONCILE_PLAN_STALE';
    END IF;
    v_hash := public.hermes_p3_payload_hash(jsonb_build_object(
        'command_type','reconcile.apply','plan_id',p_plan_id,
        'expected_plan_version',p_expected_plan_version,'authorization_ref',p_authorization_ref
    ));
    INSERT INTO public.command_receipts(
        command_id,project_id,command_type,idempotency_key,request_hash,status,result
    ) VALUES (p_command_id,p_plan_id,'reconcile.apply',p_idempotency_key,v_hash,'PROCESSING','{}'::jsonb)
    ON CONFLICT DO NOTHING;
    IF NOT FOUND THEN
        SELECT * INTO v_existing FROM public.command_receipts WHERE command_id = p_command_id;
        IF v_existing.request_hash <> v_hash THEN RAISE EXCEPTION 'IDEMPOTENCY_PAYLOAD_CONFLICT'; END IF;
        IF v_existing.status = 'APPLIED' THEN RETURN v_existing.result; END IF;
        RAISE EXCEPTION 'COMMAND_ALREADY_PROCESSING';
    END IF;
    IF v_plan.dry_run THEN
        RAISE EXCEPTION 'RECONCILE_DRY_RUN_CANNOT_APPLY';
    END IF;
    FOR v_finding IN
        SELECT f.* FROM public.reconcile_findings f
        JOIN public.reconcile_plan_findings pf ON pf.finding_id = f.finding_id
        WHERE pf.plan_id = p_plan_id
        ORDER BY f.finding_id
        FOR UPDATE OF f
    LOOP
        IF v_finding.version <> (v_plan.observed_versions ->> v_finding.finding_id)::bigint
           AND NOT (
               v_finding.status = 'PLANNED'
               AND v_finding.version = (v_plan.observed_versions ->> v_finding.finding_id)::bigint + 1
           ) THEN
            RAISE EXCEPTION 'RECONCILE_PLAN_STALE';
        END IF;
        IF EXISTS (
            SELECT 1 FROM public.reconcile_plan_repairs
            WHERE plan_id = p_plan_id
              AND repair_action = 'ADVANCE_CHECKPOINT_IF_EFFECT_CONTIGUOUS'
        ) AND v_finding.finding_kind = 'EFFECT_WITHOUT_CHECKPOINT' THEN
            SELECT * INTO v_checkpoint FROM public.consumer_checkpoints
            WHERE consumer_id = v_finding.consumer_id AND partition_key = v_finding.partition_key
            FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'CHECKPOINT_NOT_FOUND'; END IF;
            SELECT max(i.sequence) INTO v_contiguous
            FROM public.consumer_inbox i
            WHERE i.consumer_id = v_finding.consumer_id
              AND i.partition_key = v_finding.partition_key
              AND i.sequence > v_checkpoint.last_sequence
              AND NOT EXISTS (
                  SELECT 1 FROM generate_series(v_checkpoint.last_sequence + 1, i.sequence) s
                  WHERE NOT EXISTS (
                      SELECT 1 FROM public.consumer_inbox ii
                      JOIN public.consumer_effects ef
                        ON ef.consumer_id = ii.consumer_id AND ef.event_id = ii.event_id
                      WHERE ii.consumer_id = i.consumer_id
                        AND ii.partition_key = i.partition_key
                        AND ii.sequence = s
                  )
              );
            IF v_contiguous IS NULL OR v_contiguous <= v_checkpoint.last_sequence THEN
                UPDATE public.reconcile_findings SET status='BLOCKED', version=version+1
                WHERE finding_id = v_finding.finding_id;
                v_blocked := v_blocked + 1;
            ELSE
                v_new_hash := public.hermes_p3_checkpoint_hash(
                    v_checkpoint.consumer_id,v_checkpoint.stream_name,v_checkpoint.partition_key,
                    v_checkpoint.generation_id,v_contiguous,v_checkpoint.consumer_version,
                    v_checkpoint.checkpoint_schema_version,v_checkpoint.projection_digest,
                    v_checkpoint.previous_checkpoint_id
                );
                UPDATE public.consumer_checkpoints
                SET last_sequence = v_contiguous,
                    checkpoint_hash = v_new_hash,
                    checkpoint_version = checkpoint_version + 1,
                    advanced_at = now(),
                    updated_at = now()
                WHERE consumer_id = v_checkpoint.consumer_id AND partition_key = v_checkpoint.partition_key;
                v_checkpoint_id := 'checkpoint-' || gen_random_uuid()::text;
                INSERT INTO public.consumer_checkpoint_versions(
                    checkpoint_id,consumer_id,stream_name,partition_key,generation_id,
                    last_sequence,previous_checkpoint_id,consumer_version,schema_version,
                    projection_digest,checkpoint_hash,checkpoint_version,status,command_id
                ) VALUES (
                    v_checkpoint_id,v_checkpoint.consumer_id,v_checkpoint.stream_name,
                    v_checkpoint.partition_key,v_checkpoint.generation_id,v_contiguous,
                    v_checkpoint.previous_checkpoint_id,v_checkpoint.consumer_version,
                    v_checkpoint.checkpoint_schema_version,v_checkpoint.projection_digest,
                    v_new_hash,v_checkpoint.checkpoint_version + 1,'CURRENT',p_command_id
                );
                UPDATE public.reconcile_findings
                SET status='RESOLVED', version=version+1, resolved_at=now()
                WHERE finding_id = v_finding.finding_id;
                v_resolved := v_resolved + 1;
                IF p_fault_point = 'after_first_repair' THEN
                    RAISE EXCEPTION 'INJECTED_RECONCILE_CRASH_AFTER_FIRST_REPAIR';
                END IF;
            END IF;
        ELSE
            UPDATE public.reconcile_findings SET status='BLOCKED', version=version+1
            WHERE finding_id = v_finding.finding_id;
            v_blocked := v_blocked + 1;
        END IF;
    END LOOP;
    v_result := jsonb_build_object(
        'result_code','RECONCILE_PLAN_APPLIED','plan_id',p_plan_id,
        'resolved_findings',v_resolved,'blocked_findings',v_blocked,
        'version',v_plan.version + 1
    );
    v_event_id := public.hermes_p3_append_event(
        p_command_id,p_plan_id,p_actor_type,p_actor_id,'reconcile.plan_applied',
        v_result,p_fault_point
    );
    UPDATE public.reconcile_plans
    SET status='APPLIED', version=version+1, applied_at=now(), result=v_result
    WHERE plan_id = p_plan_id;
    UPDATE public.reconcile_plan_repairs
    SET status = CASE WHEN v_resolved > 0 THEN 'APPLIED' ELSE 'BLOCKED' END,
        result = v_result
    WHERE plan_id = p_plan_id;
    PERFORM public.hermes_p3_complete_command(p_command_id,'APPLIED',v_result || jsonb_build_object('event_id',v_event_id));
    RETURN v_result || jsonb_build_object('event_id',v_event_id);
END;
$$;

ALTER TABLE public.consumer_checkpoint_versions OWNER TO hermes_replay_reconcile_owner;
ALTER TABLE public.replay_generation_pointers OWNER TO hermes_replay_reconcile_owner;
ALTER TABLE public.replay_generations OWNER TO hermes_replay_reconcile_owner;
ALTER TABLE public.replay_sessions OWNER TO hermes_replay_reconcile_owner;
ALTER TABLE public.replay_shadow_projection_events OWNER TO hermes_replay_reconcile_owner;
ALTER TABLE public.reconcile_findings OWNER TO hermes_replay_reconcile_owner;
ALTER TABLE public.reconcile_plans OWNER TO hermes_replay_reconcile_owner;
ALTER TABLE public.reconcile_plan_findings OWNER TO hermes_replay_reconcile_owner;
ALTER TABLE public.reconcile_plan_repairs OWNER TO hermes_replay_reconcile_owner;

ALTER FUNCTION public.hermes_p3_checkpoint_hash(TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_replay_reconcile_owner;
ALTER FUNCTION public.hermes_p3_set_checkpoint_hash() OWNER TO hermes_replay_reconcile_owner;
ALTER FUNCTION public.hermes_p3_reject_history_change() OWNER TO hermes_replay_reconcile_owner;
ALTER FUNCTION public.hermes_p3_payload_hash(JSONB) OWNER TO hermes_replay_reconcile_owner;
ALTER FUNCTION public.hermes_p3_append_event(TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) OWNER TO hermes_replay_reconcile_owner;
ALTER FUNCTION public.hermes_p3_complete_command(TEXT,TEXT,JSONB) OWNER TO hermes_replay_reconcile_owner;
ALTER FUNCTION public.hermes_p3_assert_authority(TEXT,TEXT,TEXT) OWNER TO hermes_replay_reconcile_owner;
ALTER FUNCTION public.hermes_request_replay_session(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,BOOLEAN,BIGINT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_replay_reconcile_owner;
ALTER FUNCTION public.hermes_execute_replay_session(TEXT,TEXT,TEXT,BIGINT,TEXT) OWNER TO hermes_replay_reconcile_owner;
ALTER FUNCTION public.hermes_activate_replay_generation(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT) OWNER TO hermes_replay_reconcile_owner;
ALTER FUNCTION public.hermes_p3_record_finding(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,JSONB,JSONB) OWNER TO hermes_replay_reconcile_owner;
ALTER FUNCTION public.hermes_observe_reconcile_findings(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_replay_reconcile_owner;
ALTER FUNCTION public.hermes_create_reconcile_plan(TEXT,TEXT,TEXT,TEXT[],TEXT[],BOOLEAN,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ) OWNER TO hermes_replay_reconcile_owner;
ALTER FUNCTION public.hermes_apply_reconcile_plan(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_replay_reconcile_owner;

GRANT SELECT ON public.event_log, public.outbox_messages, public.consumer_inbox,
    public.consumer_effects, public.consumer_checkpoints, public.consumer_pending_gaps,
    public.consumer_quarantine, public.outbox_delivery_dlq
    TO hermes_replay_reconcile_owner;
GRANT SELECT, INSERT, UPDATE ON public.command_receipts, public.audit_records
    TO hermes_replay_reconcile_owner;
GRANT SELECT, INSERT ON public.event_log, public.outbox_messages
    TO hermes_replay_reconcile_owner;
GRANT SELECT, UPDATE ON public.consumer_checkpoints TO hermes_replay_reconcile_owner;
GRANT SELECT, INSERT, UPDATE ON public.consumer_quarantine TO hermes_replay_reconcile_owner;
GRANT SELECT, INSERT ON public.consumer_checkpoint_versions,
    public.replay_shadow_projection_events, public.reconcile_plan_findings,
    public.reconcile_plan_repairs TO hermes_replay_reconcile_owner;
GRANT SELECT, INSERT, UPDATE ON public.replay_generation_pointers,
    public.replay_generations, public.replay_sessions, public.reconcile_findings,
    public.reconcile_plans TO hermes_replay_reconcile_owner;
GRANT EXECUTE ON FUNCTION public.hermes_event_envelope(TEXT) TO hermes_replay_reconcile_owner;
GRANT EXECUTE ON FUNCTION public.hermes_consumer_quarantine(TEXT,TEXT,TEXT,BIGINT,JSONB,TEXT,TEXT)
    TO hermes_replay_reconcile_owner;

REVOKE ALL ON public.consumer_checkpoint_versions,
    public.replay_generation_pointers, public.replay_generations,
    public.replay_sessions, public.replay_shadow_projection_events,
    public.reconcile_findings, public.reconcile_plans,
    public.reconcile_plan_findings, public.reconcile_plan_repairs FROM PUBLIC;

REVOKE ALL ON FUNCTION public.hermes_p3_checkpoint_hash(TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_set_checkpoint_hash() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_reject_history_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_payload_hash(JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_append_event(TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_complete_command(TEXT,TEXT,JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_assert_authority(TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_request_replay_session(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,BOOLEAN,BIGINT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_execute_replay_session(TEXT,TEXT,TEXT,BIGINT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_activate_replay_generation(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_p3_record_finding(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,JSONB,JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_observe_reconcile_findings(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_create_reconcile_plan(TEXT,TEXT,TEXT,TEXT[],TEXT[],BOOLEAN,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_apply_reconcile_plan(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;

GRANT SELECT ON public.consumer_checkpoint_versions, public.replay_generation_pointers,
    public.replay_generations, public.replay_sessions,
    public.replay_shadow_projection_events, public.reconcile_findings,
    public.reconcile_plans, public.reconcile_plan_findings,
    public.reconcile_plan_repairs TO hermes_read_only_runtime;

GRANT SELECT ON public.event_log, public.consumer_checkpoints,
    public.consumer_inbox, public.consumer_effects, public.consumer_pending_gaps,
    public.consumer_quarantine TO hermes_replay_runtime, hermes_reconcile_runtime,
    hermes_reconcile_apply_runtime;
GRANT SELECT ON public.consumer_checkpoint_versions, public.replay_generation_pointers,
    public.replay_generations, public.replay_sessions,
    public.replay_shadow_projection_events TO hermes_replay_runtime,
    hermes_reconcile_runtime, hermes_reconcile_apply_runtime;
GRANT SELECT ON public.reconcile_findings, public.reconcile_plans,
    public.reconcile_plan_findings, public.reconcile_plan_repairs
    TO hermes_reconcile_runtime, hermes_reconcile_apply_runtime;

GRANT EXECUTE ON FUNCTION public.hermes_request_replay_session(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,BOOLEAN,BIGINT,TEXT,TEXT,TEXT,TEXT)
    TO hermes_replay_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_execute_replay_session(TEXT,TEXT,TEXT,BIGINT,TEXT)
    TO hermes_replay_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_activate_replay_generation(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT)
    TO hermes_replay_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_observe_reconcile_findings(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO hermes_reconcile_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_create_reconcile_plan(TEXT,TEXT,TEXT,TEXT[],TEXT[],BOOLEAN,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ)
    TO hermes_reconcile_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_apply_reconcile_plan(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO hermes_reconcile_apply_runtime;

REVOKE INSERT, UPDATE, DELETE ON public.consumer_checkpoint_versions,
    public.replay_generation_pointers, public.replay_generations,
    public.replay_sessions, public.replay_shadow_projection_events,
    public.reconcile_findings, public.reconcile_plans,
    public.reconcile_plan_findings, public.reconcile_plan_repairs
    FROM hermes_replay_runtime, hermes_reconcile_runtime,
    hermes_reconcile_apply_runtime, hermes_worker_runtime,
    hermes_scheduler_runtime, hermes_planner_runtime, hermes_verifier_runtime,
    hermes_read_only_runtime;

REVOKE UPDATE ON public.projects, public.tasks, public.resource_accounts,
    public.execution_leases, public.verification_results
    FROM hermes_replay_runtime, hermes_reconcile_runtime,
    hermes_reconcile_apply_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_replay_runtime,
    hermes_reconcile_runtime, hermes_reconcile_apply_runtime;

COMMENT ON TABLE public.replay_generations IS
'P3-2 isolated replay generations. They are read-model/checkpoint candidates, not authority rebuilds.';
COMMENT ON TABLE public.reconcile_plans IS
'P3-2 immutable reconcile dry-run/apply plans. Repairs are whitelisted semantic actions only.';
