-- P2-3: Scheduler authority, PostgreSQL Lease, fencing token and execution lock acquisition.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_scheduler_owner') THEN
        CREATE ROLE hermes_scheduler_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_scheduler_runtime') THEN
        CREATE ROLE hermes_scheduler_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.scheduler_lease_profiles (
    profile_id TEXT NOT NULL,
    profile_version BIGINT NOT NULL CHECK (profile_version >= 1),
    schema_version TEXT NOT NULL,
    initial_ttl_ms INTEGER NOT NULL CHECK (initial_ttl_ms BETWEEN 100 AND 3600000),
    renew_interval_ms INTEGER NOT NULL CHECK (renew_interval_ms BETWEEN 100 AND 3600000),
    max_extension_ms INTEGER NOT NULL CHECK (max_extension_ms BETWEEN 100 AND 3600000),
    max_lifetime_ms INTEGER NOT NULL CHECK (max_lifetime_ms BETWEEN 100 AND 3600000),
    takeover_after_expiry_ms INTEGER NOT NULL CHECK (takeover_after_expiry_ms BETWEEN 0 AND 3600000),
    requeue_backoff_ms INTEGER NOT NULL CHECK (requeue_backoff_ms BETWEEN 0 AND 3600000),
    max_acquisition_batch INTEGER NOT NULL CHECK (max_acquisition_batch = 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (profile_id, profile_version),
    CHECK (max_lifetime_ms >= initial_ttl_ms),
    CHECK (renew_interval_ms <= initial_ttl_ms),
    CHECK (max_extension_ms <= initial_ttl_ms)
);

INSERT INTO public.scheduler_lease_profiles(
    profile_id, profile_version, schema_version, initial_ttl_ms,
    renew_interval_ms, max_extension_ms, max_lifetime_ms,
    takeover_after_expiry_ms, requeue_backoff_ms, max_acquisition_batch
) VALUES (
    'p2-default', 1, 'lease-profile/1.0', 30000,
    10000, 30000, 300000, 0, 0, 1
) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.scheduler_instances (
    scheduler_id TEXT NOT NULL,
    scheduler_session_id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    actor_type TEXT NOT NULL CHECK (actor_type = 'scheduler'),
    actor_id TEXT NOT NULL,
    admitted BOOLEAN NOT NULL DEFAULT true,
    scheduler_version BIGINT NOT NULL CHECK (scheduler_version >= 1),
    admitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    reason TEXT NOT NULL,
    PRIMARY KEY (scheduler_id, scheduler_session_id, project_id)
);

CREATE TABLE IF NOT EXISTS public.execution_request_current_states (
    execution_request_id TEXT PRIMARY KEY REFERENCES public.execution_requests(execution_request_id),
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    request_state TEXT NOT NULL CHECK (request_state IN ('QUEUED','LEASED')),
    request_version BIGINT NOT NULL CHECK (request_version >= 1),
    current_lease_id TEXT,
    current_fencing_token BIGINT NOT NULL DEFAULT 0 CHECK (current_fencing_token >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    CHECK (
        (request_state = 'QUEUED' AND current_lease_id IS NULL)
        OR
        (request_state = 'LEASED' AND current_lease_id IS NOT NULL AND current_fencing_token > 0)
    )
);

CREATE TABLE IF NOT EXISTS public.execution_queue_current_states (
    queue_item_id TEXT PRIMARY KEY REFERENCES public.execution_queue_items(queue_item_id),
    execution_request_id TEXT NOT NULL UNIQUE REFERENCES public.execution_requests(execution_request_id),
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    queue_state TEXT NOT NULL CHECK (queue_state IN ('PENDING','LEASED')),
    priority INTEGER NOT NULL CHECK (priority BETWEEN -1000 AND 1000),
    available_at TIMESTAMPTZ NOT NULL,
    enqueued_at TIMESTAMPTZ NOT NULL,
    stable_order_key TEXT NOT NULL,
    current_lease_id TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    CHECK (
        (queue_state = 'PENDING' AND current_lease_id IS NULL)
        OR
        (queue_state = 'LEASED' AND current_lease_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS public.execution_fencing_counters (
    execution_request_id TEXT PRIMARY KEY REFERENCES public.execution_requests(execution_request_id),
    last_token BIGINT NOT NULL CHECK (last_token >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.execution_leases (
    lease_id TEXT PRIMARY KEY,
    execution_request_id TEXT NOT NULL REFERENCES public.execution_requests(execution_request_id),
    queue_item_id TEXT NOT NULL REFERENCES public.execution_queue_items(queue_item_id),
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    scheduler_id TEXT NOT NULL,
    scheduler_session_id TEXT NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type = 'scheduler'),
    actor_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    profile_version BIGINT NOT NULL,
    fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
    lease_state TEXT NOT NULL CHECK (lease_state IN ('ACTIVE','EXPIRED','RELINQUISHED','SUPERSEDED')),
    lease_version BIGINT NOT NULL CHECK (lease_version >= 1),
    grant_generation BIGINT NOT NULL CHECK (grant_generation >= 1),
    granted_at TIMESTAMPTZ NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    max_expires_at TIMESTAMPTZ NOT NULL,
    lock_scope_hash TEXT NOT NULL CHECK (lock_scope_hash LIKE 'sha256:%'),
    lock_refs JSONB NOT NULL,
    command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    idempotency_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK (payload_hash LIKE 'sha256:%'),
    reason TEXT NOT NULL,
    terminal_reason TEXT,
    terminal_command_id TEXT REFERENCES public.command_receipts(command_id),
    terminal_at TIMESTAMPTZ,
    acquired_event_id TEXT,
    terminal_event_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (profile_id, profile_version)
        REFERENCES public.scheduler_lease_profiles(profile_id, profile_version),
    FOREIGN KEY (scheduler_id, scheduler_session_id, project_id)
        REFERENCES public.scheduler_instances(scheduler_id, scheduler_session_id, project_id),
    UNIQUE (execution_request_id, fencing_token),
    CHECK (expires_at <= max_expires_at),
    CHECK (
        (lease_state = 'ACTIVE' AND terminal_at IS NULL)
        OR
        (lease_state <> 'ACTIVE' AND terminal_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS execution_leases_one_active_request
    ON public.execution_leases(execution_request_id)
    WHERE lease_state = 'ACTIVE';

CREATE UNIQUE INDEX IF NOT EXISTS execution_leases_one_active_queue_item
    ON public.execution_leases(queue_item_id)
    WHERE lease_state = 'ACTIVE';

CREATE TABLE IF NOT EXISTS public.execution_lease_state_history (
    history_id TEXT PRIMARY KEY,
    lease_id TEXT NOT NULL REFERENCES public.execution_leases(lease_id),
    execution_request_id TEXT NOT NULL REFERENCES public.execution_requests(execution_request_id),
    from_state TEXT,
    to_state TEXT NOT NULL,
    lease_version BIGINT NOT NULL,
    fencing_token BIGINT NOT NULL,
    reason_code TEXT NOT NULL,
    command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    event_id TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.execution_lock_ownerships (
    lock_scope TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    execution_request_id TEXT NOT NULL REFERENCES public.execution_requests(execution_request_id),
    queue_item_id TEXT NOT NULL REFERENCES public.execution_queue_items(queue_item_id),
    lease_id TEXT NOT NULL REFERENCES public.execution_leases(lease_id),
    fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
    owner_scheduler_id TEXT NOT NULL,
    owner_session_id TEXT NOT NULL,
    lock_state TEXT NOT NULL CHECK (lock_state IN ('ACTIVE','RELEASED','EXPIRED','SUPERSEDED')),
    acquired_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    released_at TIMESTAMPTZ,
    CHECK (
        (lock_state = 'ACTIVE' AND released_at IS NULL)
        OR
        (lock_state <> 'ACTIVE' AND released_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS public.execution_scheduler_rejections (
    rejection_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    idempotency_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.hermes_seed_execution_request_current_state()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    INSERT INTO public.execution_request_current_states(
        execution_request_id, project_id, task_id, request_state, request_version,
        current_fencing_token, command_id
    ) VALUES (
        NEW.execution_request_id, NEW.project_id, NEW.task_id, 'QUEUED',
        NEW.request_version, 0, NEW.command_id
    ) ON CONFLICT DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS execution_request_current_seed ON public.execution_requests;
CREATE TRIGGER execution_request_current_seed
AFTER INSERT ON public.execution_requests
FOR EACH ROW EXECUTE FUNCTION public.hermes_seed_execution_request_current_state();

CREATE OR REPLACE FUNCTION public.hermes_seed_execution_queue_current_state()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    INSERT INTO public.execution_queue_current_states(
        queue_item_id, execution_request_id, project_id, task_id, queue_state,
        priority, available_at, enqueued_at, stable_order_key, current_lease_id,
        command_id
    ) VALUES (
        NEW.queue_item_id, NEW.execution_request_id, NEW.project_id, NEW.task_id,
        'PENDING', NEW.priority, NEW.available_at, NEW.enqueued_at,
        NEW.stable_order_key, NULL, NEW.command_id
    ) ON CONFLICT DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS execution_queue_current_seed ON public.execution_queue_items;
CREATE TRIGGER execution_queue_current_seed
AFTER INSERT ON public.execution_queue_items
FOR EACH ROW EXECUTE FUNCTION public.hermes_seed_execution_queue_current_state();

INSERT INTO public.execution_request_current_states(
    execution_request_id, project_id, task_id, request_state, request_version,
    current_fencing_token, command_id
)
SELECT execution_request_id, project_id, task_id, 'QUEUED', request_version, 0, command_id
FROM public.execution_requests
ON CONFLICT DO NOTHING;

INSERT INTO public.execution_queue_current_states(
    queue_item_id, execution_request_id, project_id, task_id, queue_state,
    priority, available_at, enqueued_at, stable_order_key, command_id
)
SELECT queue_item_id, execution_request_id, project_id, task_id, 'PENDING',
       priority, available_at, enqueued_at, stable_order_key, command_id
FROM public.execution_queue_items
ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION public.hermes_scheduler_secret_guard(p_payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
    SELECT p_payload::text ~* '("(api[_-]?token|password|credential|private[_-]?key)"[[:space:]]*:|private key|sk-[A-Za-z0-9]{12,}|password=)'
$$;

CREATE OR REPLACE FUNCTION public.hermes_scheduler_reject_command(
    p_project_id TEXT,
    p_command_id TEXT,
    p_command_type TEXT,
    p_idempotency_key TEXT,
    p_request_hash TEXT,
    p_reason_code TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_detail TEXT DEFAULT ''
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    result_payload JSONB;
BEGIN
    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key,
        request_hash, status, result, completed_at
    ) VALUES (
        p_command_id, p_project_id, p_command_type, p_idempotency_key,
        p_request_hash, 'REJECTED',
        jsonb_build_object('result_code', p_reason_code, 'detail', p_detail),
        clock_timestamp()
    ) ON CONFLICT (command_id) DO UPDATE
      SET status='REJECTED',
          result=jsonb_build_object('result_code', p_reason_code, 'detail', p_detail),
          completed_at=clock_timestamp()
      WHERE public.command_receipts.command_id = p_command_id
        AND public.command_receipts.status = 'PROCESSING';

    INSERT INTO public.execution_scheduler_rejections(
        rejection_id, project_id, command_id, idempotency_key, payload_hash,
        reason_code, detail, actor_type, actor_id
    ) VALUES (
        'sched-rej-' || gen_random_uuid()::text, p_project_id, p_command_id,
        p_idempotency_key, p_request_hash, p_reason_code,
        left(COALESCE(p_detail,''), 1000), p_actor_type, p_actor_id
    ) ON CONFLICT DO NOTHING;

    result_payload := jsonb_build_object(
        'result_code', p_reason_code,
        'rejected', true,
        'detail', p_detail
    );
    RETURN result_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_scheduler_register(
    p_project_id TEXT,
    p_scheduler_id TEXT,
    p_scheduler_session_id TEXT,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_request_hash TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_reason TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    command_row public.command_receipts%ROWTYPE;
    result_payload JSONB;
BEGIN
    IF p_actor_type <> 'scheduler' OR p_scheduler_id IS NULL OR p_scheduler_session_id IS NULL THEN
        RETURN public.hermes_scheduler_reject_command(
            p_project_id, p_command_id, 'scheduler.register', p_idempotency_key,
            p_request_hash, 'SCHEDULER_NOT_ADMITTED', p_actor_type, p_actor_id, ''
        );
    END IF;
    IF public.hermes_scheduler_secret_guard(to_jsonb(ARRAY[p_scheduler_id,p_scheduler_session_id,p_actor_id,p_reason])) THEN
        RAISE EXCEPTION 'SECRET_VALUE_FORBIDDEN';
    END IF;

    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key,
        request_hash, status, result
    ) VALUES (
        p_command_id, p_project_id, 'scheduler.register', p_idempotency_key,
        p_request_hash, 'PROCESSING', '{}'::jsonb
    ) ON CONFLICT DO NOTHING;

    SELECT * INTO command_row
    FROM public.command_receipts
    WHERE project_id=p_project_id
      AND command_type='scheduler.register'
      AND idempotency_key=p_idempotency_key
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SCHEDULER_IDEMPOTENCY_CONFLICT';
    END IF;
    IF command_row.request_hash <> p_request_hash THEN
        RAISE EXCEPTION 'SCHEDULER_IDEMPOTENCY_CONFLICT';
    END IF;
    IF command_row.status = 'APPLIED' THEN
        RETURN command_row.result->'response';
    END IF;

    INSERT INTO public.scheduler_instances(
        scheduler_id, scheduler_session_id, project_id, actor_type, actor_id,
        admitted, scheduler_version, command_id, reason
    ) VALUES (
        p_scheduler_id, p_scheduler_session_id, p_project_id, p_actor_type,
        p_actor_id, true, 1, p_command_id, p_reason
    ) ON CONFLICT (scheduler_id, scheduler_session_id, project_id) DO UPDATE
      SET admitted=true,
          scheduler_version=public.scheduler_instances.scheduler_version + 1,
          revoked_at=NULL,
          command_id=p_command_id,
          reason=p_reason;

    result_payload := jsonb_build_object(
        'result_code', 'SCHEDULER_ADMITTED',
        'project_id', p_project_id,
        'scheduler_id', p_scheduler_id,
        'scheduler_session_id', p_scheduler_session_id,
        'scheduler_version', (
            SELECT scheduler_version FROM public.scheduler_instances
            WHERE scheduler_id=p_scheduler_id
              AND scheduler_session_id=p_scheduler_session_id
              AND project_id=p_project_id
        )
    );

    UPDATE public.command_receipts
    SET status='APPLIED',
        result=jsonb_build_object(
            'command_id', p_command_id,
            'status', 'APPLIED',
            'result_code', 'SCHEDULER_ADMITTED',
            'response', result_payload
        ),
        completed_at=clock_timestamp()
    WHERE command_id=p_command_id AND status='PROCESSING';
    RETURN result_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_scheduler_acquire_lease(
    p_project_id TEXT,
    p_scheduler_id TEXT,
    p_scheduler_session_id TEXT,
    p_profile_id TEXT,
    p_profile_version BIGINT,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_request_hash TEXT,
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
    scheduler_row public.scheduler_instances%ROWTYPE;
    profile_row public.scheduler_lease_profiles%ROWTYPE;
    candidate RECORD;
    active_lease public.execution_leases%ROWTYPE;
    request_row public.execution_requests%ROWTYPE;
    availability_row public.worker_template_availability%ROWTYPE;
    binding_row public.execution_reservation_bindings%ROWTYPE;
    reservation_row public.resource_reservations%ROWTYPE;
    lock_item JSONB;
    v_lock_scope TEXT;
    lock_conflict BOOLEAN;
    current_clock TIMESTAMPTZ;
    new_lease_id TEXT;
    new_token BIGINT;
    new_expires_at TIMESTAMPTZ;
    new_max_expires_at TIMESTAMPTZ;
    lease_event_id TEXT;
    expired_event_id TEXT;
    event_sequence BIGINT;
    expired_sequence BIGINT;
    v_lock_refs JSONB;
    result_payload JSONB;
BEGIN
    IF p_actor_type <> 'scheduler' THEN
        RETURN public.hermes_scheduler_reject_command(
            p_project_id, p_command_id, 'scheduler.acquire_lease',
            p_idempotency_key, p_request_hash, 'SCHEDULER_NOT_ADMITTED',
            p_actor_type, p_actor_id, ''
        );
    END IF;
    IF public.hermes_scheduler_secret_guard(to_jsonb(ARRAY[p_scheduler_id,p_scheduler_session_id,p_actor_id,p_reason])) THEN
        RAISE EXCEPTION 'SECRET_VALUE_FORBIDDEN';
    END IF;

    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key,
        request_hash, status, result
    ) VALUES (
        p_command_id, p_project_id, 'scheduler.acquire_lease',
        p_idempotency_key, p_request_hash, 'PROCESSING', '{}'::jsonb
    ) ON CONFLICT DO NOTHING;
    SELECT * INTO command_row
    FROM public.command_receipts
    WHERE project_id=p_project_id
      AND command_type='scheduler.acquire_lease'
      AND idempotency_key=p_idempotency_key
    FOR UPDATE;
    IF NOT FOUND OR command_row.request_hash <> p_request_hash THEN
        RAISE EXCEPTION 'SCHEDULER_IDEMPOTENCY_CONFLICT';
    END IF;
    IF command_row.status = 'APPLIED' THEN
        RETURN command_row.result->'response';
    END IF;
    IF p_fault_point = 'after_receipt_placeholder' THEN
        RAISE EXCEPTION 'injected scheduler crash: after_receipt_placeholder';
    END IF;

    SELECT * INTO scheduler_row
    FROM public.scheduler_instances
    WHERE scheduler_id=p_scheduler_id
      AND scheduler_session_id=p_scheduler_session_id
      AND project_id=p_project_id
      AND admitted=true
      AND revoked_at IS NULL
    ;
    IF NOT FOUND THEN
        RETURN public.hermes_scheduler_reject_command(
            p_project_id, p_command_id, 'scheduler.acquire_lease',
            p_idempotency_key, p_request_hash, 'SCHEDULER_NOT_ADMITTED',
            p_actor_type, p_actor_id, ''
        );
    END IF;
    SELECT * INTO profile_row
    FROM public.scheduler_lease_profiles
    WHERE profile_id=p_profile_id AND profile_version=p_profile_version
    ;
    IF NOT FOUND THEN
        RETURN public.hermes_scheduler_reject_command(
            p_project_id, p_command_id, 'scheduler.acquire_lease',
            p_idempotency_key, p_request_hash, 'LEASE_PROFILE_INVALID',
            p_actor_type, p_actor_id, ''
        );
    END IF;
    IF p_fault_point = 'after_authority_validation' THEN
        RAISE EXCEPTION 'injected scheduler crash: after_authority_validation';
    END IF;

    FOR candidate IN
        SELECT q.queue_item_id, q.execution_request_id, q.project_id, q.task_id,
               q.priority, q.available_at, q.enqueued_at, q.stable_order_key,
               q.queue_state, r.request_state, r.request_version,
               immutable_request.lock_intents, immutable_request.lock_scope_hash
        FROM public.execution_queue_current_states q
        JOIN public.execution_request_current_states r
          ON r.execution_request_id = q.execution_request_id
        JOIN public.execution_requests immutable_request
          ON immutable_request.execution_request_id = q.execution_request_id
        LEFT JOIN public.execution_leases lease
          ON lease.lease_id = r.current_lease_id
        WHERE q.project_id=p_project_id
          AND q.available_at <= clock_timestamp()
          AND (
              (q.queue_state='PENDING' AND r.request_state='QUEUED')
              OR
              (q.queue_state='LEASED' AND r.request_state IN ('LEASED','RUNNING')
               AND lease.lease_state='ACTIVE' AND lease.expires_at <= clock_timestamp())
          )
        ORDER BY q.priority DESC, q.available_at ASC, q.enqueued_at ASC, q.queue_item_id ASC
        FOR UPDATE OF q SKIP LOCKED
    LOOP
        SELECT * INTO request_row
        FROM public.execution_requests
        WHERE execution_request_id=candidate.execution_request_id
        ;

        SELECT * INTO binding_row
        FROM public.execution_reservation_bindings
        WHERE execution_request_id=candidate.execution_request_id
        ;
        SELECT * INTO reservation_row
        FROM public.resource_reservations
        WHERE reservation_id=request_row.reservation_id
        ;
        SELECT * INTO availability_row
        FROM public.worker_template_availability
        WHERE template_id=request_row.worker_template_id
          AND revision=request_row.worker_template_revision
          AND availability_version=request_row.worker_template_availability_version
        ;
        IF NOT FOUND OR binding_row.execution_request_id IS NULL
           OR reservation_row.status <> 'ACTIVE'
           OR availability_row.availability_status <> 'AVAILABLE'
           OR availability_row.admission_status <> 'ADMISSIBLE' THEN
            CONTINUE;
        END IF;
        IF p_fault_point = 'after_queue_candidate_locked' THEN
            RAISE EXCEPTION 'injected scheduler crash: after_queue_candidate_locked';
        END IF;

        lock_conflict := false;
        FOR lock_item IN
            SELECT * FROM jsonb_array_elements(candidate.lock_intents)
            ORDER BY
                CASE split_part(value->>'scope', ':', 1)
                    WHEN 'repository' THEN 0
                    WHEN 'workspace' THEN 1
                    WHEN 'branch_ref' THEN 2
                    WHEN 'artifact_namespace' THEN 3
                    WHEN 'external_environment' THEN 4
                    WHEN 'deployment_target' THEN 5
                    ELSE 99
                END,
                value->>'scope'
        LOOP
            v_lock_scope := lock_item->>'scope';
            IF v_lock_scope IS NULL
               OR position(':' in v_lock_scope) < 2
               OR split_part(v_lock_scope, ':', 1) NOT IN (
                   'repository','workspace','branch_ref','artifact_namespace',
                   'external_environment','deployment_target'
               )
               OR v_lock_scope LIKE '%*%' THEN
                RAISE EXCEPTION 'EXECUTION_LOCK_CONFLICT';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtext(v_lock_scope));
            IF EXISTS (
                SELECT 1 FROM public.execution_lock_ownerships l
                WHERE l.lock_scope=v_lock_scope
                  AND l.lock_state='ACTIVE'
                  AND l.expires_at > clock_timestamp()
                  AND l.execution_request_id <> candidate.execution_request_id
                FOR UPDATE
            ) THEN
                lock_conflict := true;
            END IF;
        END LOOP;
        IF p_fault_point = 'after_lock_scopes_prepared' THEN
            RAISE EXCEPTION 'injected scheduler crash: after_lock_scopes_prepared';
        END IF;
        IF lock_conflict THEN
            CONTINUE;
        END IF;

        SELECT * INTO active_lease
        FROM public.execution_leases
        WHERE lease_id = (
            SELECT current_lease_id
            FROM public.execution_request_current_states
            WHERE execution_request_id=candidate.execution_request_id
            FOR UPDATE
        )
        FOR UPDATE;

        current_clock := clock_timestamp();
        expired_event_id := NULL;
        expired_sequence := NULL;
        IF active_lease.lease_id IS NOT NULL THEN
            IF active_lease.lease_state <> 'ACTIVE' OR active_lease.expires_at > current_clock THEN
                CONTINUE;
            END IF;
            expired_event_id := 'evt-' || gen_random_uuid()::text;
            UPDATE public.execution_leases
            SET lease_state='EXPIRED',
                lease_version=lease_version + 1,
                terminal_reason='LEASE_EXPIRED',
                terminal_command_id=p_command_id,
                terminal_at=current_clock,
                terminal_event_id=expired_event_id
            WHERE lease_id=active_lease.lease_id
              AND lease_state='ACTIVE'
              AND expires_at <= current_clock;
            IF NOT FOUND THEN
                CONTINUE;
            END IF;
            INSERT INTO public.execution_lease_state_history(
                history_id, lease_id, execution_request_id, from_state, to_state,
                lease_version, fencing_token, reason_code, command_id, event_id
            ) VALUES (
                'lease-hist-' || gen_random_uuid()::text, active_lease.lease_id,
                active_lease.execution_request_id, 'ACTIVE', 'EXPIRED',
                active_lease.lease_version + 1, active_lease.fencing_token,
                'LEASE_EXPIRED', p_command_id, expired_event_id
            );
            UPDATE public.execution_lock_ownerships
            SET lock_state='EXPIRED', released_at=current_clock
            WHERE lease_id=active_lease.lease_id
              AND lock_state='ACTIVE'
              AND expires_at <= current_clock;
            INSERT INTO public.event_log(
                event_id, event_type, schema_version, producer_type, producer_id,
                project_id, partition_key, command_id, correlation_id, causation_id,
                task_id, payload
            ) VALUES (
                expired_event_id, 'execution.lease_expired', '1.0',
                p_actor_type, p_actor_id, p_project_id, p_project_id, p_command_id,
                p_command_id, active_lease.acquired_event_id, active_lease.task_id,
                jsonb_build_object(
                    'execution_request_id', active_lease.execution_request_id,
                    'lease_id', active_lease.lease_id,
                    'fencing_token', active_lease.fencing_token,
                    'expired_at', current_clock,
                    'lease_version', active_lease.lease_version + 1
                )
            ) RETURNING sequence INTO expired_sequence;
        END IF;
        IF p_fault_point = 'after_expiry_before_new_lease' THEN
            RAISE EXCEPTION 'injected scheduler crash: after_expiry_before_new_lease';
        END IF;

        INSERT INTO public.execution_fencing_counters(
            execution_request_id, last_token, updated_at
        ) VALUES (
            candidate.execution_request_id, 1, current_clock
        ) ON CONFLICT (execution_request_id) DO UPDATE
          SET last_token=public.execution_fencing_counters.last_token + 1,
              updated_at=current_clock
          WHERE public.execution_fencing_counters.last_token < 9223372036854775807
        RETURNING last_token INTO new_token;
        IF new_token IS NULL THEN
            RAISE EXCEPTION 'FENCING_TOKEN_OVERFLOW';
        END IF;
        IF p_fault_point = 'after_fencing_token_allocated' THEN
            RAISE EXCEPTION 'injected scheduler crash: after_fencing_token_allocated';
        END IF;

        new_lease_id := 'lease-' || gen_random_uuid()::text;
        new_expires_at := current_clock + (profile_row.initial_ttl_ms::text || ' milliseconds')::interval;
        new_max_expires_at := current_clock + (profile_row.max_lifetime_ms::text || ' milliseconds')::interval;
        lease_event_id := 'evt-' || gen_random_uuid()::text;
        v_lock_refs := '[]'::jsonb;

        INSERT INTO public.execution_leases(
            lease_id, execution_request_id, queue_item_id, project_id, task_id,
            scheduler_id, scheduler_session_id, actor_type, actor_id,
            profile_id, profile_version, fencing_token, lease_state,
            lease_version, grant_generation, granted_at, heartbeat_at,
            expires_at, max_expires_at, lock_scope_hash, lock_refs,
            command_id, idempotency_key, payload_hash, reason, acquired_event_id
        ) VALUES (
            new_lease_id, candidate.execution_request_id, candidate.queue_item_id,
            candidate.project_id, candidate.task_id, p_scheduler_id,
            p_scheduler_session_id, p_actor_type, p_actor_id,
            p_profile_id, p_profile_version, new_token, 'ACTIVE',
            1, new_token, current_clock, current_clock, new_expires_at,
            new_max_expires_at, candidate.lock_scope_hash, '[]'::jsonb,
            p_command_id, p_idempotency_key, p_request_hash, p_reason, lease_event_id
        );
        IF p_fault_point = 'after_lease_written' THEN
            RAISE EXCEPTION 'injected scheduler crash: after_lease_written';
        END IF;

        FOR lock_item IN
            SELECT * FROM jsonb_array_elements(candidate.lock_intents)
            ORDER BY
                CASE split_part(value->>'scope', ':', 1)
                    WHEN 'repository' THEN 0
                    WHEN 'workspace' THEN 1
                    WHEN 'branch_ref' THEN 2
                    WHEN 'artifact_namespace' THEN 3
                    WHEN 'external_environment' THEN 4
                    WHEN 'deployment_target' THEN 5
                    ELSE 99
                END,
                value->>'scope'
        LOOP
            v_lock_scope := lock_item->>'scope';
            INSERT INTO public.execution_lock_ownerships(
                lock_scope, project_id, execution_request_id, queue_item_id,
                lease_id, fencing_token, owner_scheduler_id, owner_session_id,
                lock_state, acquired_at, expires_at, command_id
            ) VALUES (
                v_lock_scope, candidate.project_id, candidate.execution_request_id,
                candidate.queue_item_id, new_lease_id, new_token, p_scheduler_id,
                p_scheduler_session_id, 'ACTIVE', current_clock, new_expires_at,
                p_command_id
            ) ON CONFLICT (lock_scope) DO UPDATE
              SET project_id=EXCLUDED.project_id,
                  execution_request_id=EXCLUDED.execution_request_id,
                  queue_item_id=EXCLUDED.queue_item_id,
                  lease_id=EXCLUDED.lease_id,
                  fencing_token=EXCLUDED.fencing_token,
                  owner_scheduler_id=EXCLUDED.owner_scheduler_id,
                  owner_session_id=EXCLUDED.owner_session_id,
                  lock_state='ACTIVE',
                  acquired_at=EXCLUDED.acquired_at,
                  expires_at=EXCLUDED.expires_at,
                  command_id=EXCLUDED.command_id,
                  released_at=NULL
              WHERE public.execution_lock_ownerships.lock_state <> 'ACTIVE'
                 OR public.execution_lock_ownerships.expires_at <= current_clock
                 OR public.execution_lock_ownerships.execution_request_id = candidate.execution_request_id
              RETURNING to_jsonb(public.execution_lock_ownerships.*) INTO lock_item;
            IF lock_item IS NULL THEN
                RAISE EXCEPTION 'EXECUTION_LOCK_CONFLICT';
            END IF;
            v_lock_refs := v_lock_refs || jsonb_build_array(v_lock_scope);
        END LOOP;
        IF p_fault_point = 'after_locks_written' THEN
            RAISE EXCEPTION 'injected scheduler crash: after_locks_written';
        END IF;

        UPDATE public.execution_leases
        SET lock_refs=v_lock_refs
        WHERE lease_id=new_lease_id;
        UPDATE public.execution_request_current_states
        SET request_state='LEASED',
            request_version=request_version + 1,
            current_lease_id=new_lease_id,
            current_fencing_token=new_token,
            updated_at=current_clock,
            command_id=p_command_id
        WHERE execution_request_id=candidate.execution_request_id;
        IF p_fault_point = 'after_request_leased' THEN
            RAISE EXCEPTION 'injected scheduler crash: after_request_leased';
        END IF;
        UPDATE public.execution_queue_current_states
        SET queue_state='LEASED',
            current_lease_id=new_lease_id,
            updated_at=current_clock,
            command_id=p_command_id
        WHERE queue_item_id=candidate.queue_item_id;
        IF p_fault_point = 'after_queue_claimed' THEN
            RAISE EXCEPTION 'injected scheduler crash: after_queue_claimed';
        END IF;
        INSERT INTO public.execution_lease_state_history(
            history_id, lease_id, execution_request_id, from_state, to_state,
            lease_version, fencing_token, reason_code, command_id, event_id
        ) VALUES (
            'lease-hist-' || gen_random_uuid()::text, new_lease_id,
            candidate.execution_request_id, NULL, 'ACTIVE', 1, new_token,
            CASE WHEN active_lease.lease_id IS NULL THEN 'LEASE_ACQUIRED' ELSE 'LEASE_TAKEN_OVER' END,
            p_command_id, lease_event_id
        );

        INSERT INTO public.event_log(
            event_id, event_type, schema_version, producer_type, producer_id,
            project_id, partition_key, command_id, correlation_id, causation_id,
            task_id, payload
        ) VALUES (
            lease_event_id,
            CASE WHEN active_lease.lease_id IS NULL THEN 'execution.lease_acquired'
                 ELSE 'execution.lease_taken_over' END,
            '1.0', p_actor_type, p_actor_id, p_project_id, p_project_id,
            p_command_id, p_command_id, COALESCE(expired_event_id, p_command_id),
            candidate.task_id,
            jsonb_build_object(
                'execution_request_id', candidate.execution_request_id,
                'queue_item_id', candidate.queue_item_id,
                'lease_id', new_lease_id,
                'previous_lease_id', active_lease.lease_id,
                'scheduler_id', p_scheduler_id,
                'scheduler_session_id', p_scheduler_session_id,
                'fencing_token', new_token,
                'request_version', (
                    SELECT request_version FROM public.execution_request_current_states
                    WHERE execution_request_id=candidate.execution_request_id
                ),
                'lease_version', 1,
                'granted_at', current_clock,
                'expires_at', new_expires_at,
                'profile_id', p_profile_id,
                'profile_version', p_profile_version,
                'lock_refs', v_lock_refs,
                'reason', p_reason
            )
        ) RETURNING sequence INTO event_sequence;
        IF p_fault_point = 'after_event_before_outbox' THEN
            RAISE EXCEPTION 'injected scheduler crash: after_event_before_outbox';
        END IF;

        IF expired_event_id IS NOT NULL THEN
            INSERT INTO public.outbox_messages(message_id, event_id, topic, partition_key, sequence, payload)
            SELECT 'msg-' || gen_random_uuid()::text, event_id, 'hermes.runtime.events',
                   p_project_id, sequence, payload
            FROM public.event_log
            WHERE event_id=expired_event_id;
        END IF;
        INSERT INTO public.outbox_messages(message_id, event_id, topic, partition_key, sequence, payload)
        SELECT 'msg-' || gen_random_uuid()::text, event_id, 'hermes.runtime.events',
               p_project_id, sequence, payload
        FROM public.event_log
            WHERE public.event_log.event_id=lease_event_id;
        IF p_fault_point = 'after_outbox_before_receipt' THEN
            RAISE EXCEPTION 'injected scheduler crash: after_outbox_before_receipt';
        END IF;

        result_payload := jsonb_build_object(
            'result_code', CASE WHEN active_lease.lease_id IS NULL THEN 'EXECUTION_LEASE_ACQUIRED' ELSE 'EXECUTION_LEASE_TAKEN_OVER' END,
            'execution_request_id', candidate.execution_request_id,
            'queue_item_id', candidate.queue_item_id,
            'lease_id', new_lease_id,
            'previous_lease_id', active_lease.lease_id,
            'request_state', 'LEASED',
            'queue_state', 'LEASED',
            'lease_state', 'ACTIVE',
            'fencing_token', new_token,
            'lease_version', 1,
            'request_version', (
                SELECT request_version FROM public.execution_request_current_states
                WHERE execution_request_id=candidate.execution_request_id
            ),
            'granted_at', current_clock,
            'expires_at', new_expires_at,
            'lock_refs', v_lock_refs,
            'event_ids', CASE WHEN expired_event_id IS NULL
                THEN jsonb_build_array(lease_event_id)
                ELSE jsonb_build_array(expired_event_id, lease_event_id)
            END,
            'deduplicated', false
        );
        UPDATE public.command_receipts
        SET status='APPLIED',
            result=jsonb_build_object(
                'command_id', p_command_id,
                'status', 'APPLIED',
                'result_code', result_payload->>'result_code',
                'target_version', result_payload->>'request_version',
                'event_ids', result_payload->'event_ids',
                'response', result_payload
            ),
            completed_at=clock_timestamp()
        WHERE command_id=p_command_id AND status='PROCESSING';
        IF p_fault_point = 'after_receipt_before_commit' THEN
            RAISE EXCEPTION 'injected scheduler crash: after_receipt_before_commit';
        END IF;
        RETURN result_payload;
    END LOOP;

    result_payload := jsonb_build_object(
        'result_code', 'NO_ELIGIBLE_EXECUTION',
        'acquired', false,
        'deduplicated', false
    );
    UPDATE public.command_receipts
    SET status='APPLIED',
        result=jsonb_build_object(
            'command_id', p_command_id,
            'status', 'APPLIED',
            'result_code', 'NO_ELIGIBLE_EXECUTION',
            'response', result_payload
        ),
        completed_at=clock_timestamp()
    WHERE command_id=p_command_id AND status='PROCESSING';
    RETURN result_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_scheduler_renew_lease(
    p_project_id TEXT,
    p_execution_request_id TEXT,
    p_lease_id TEXT,
    p_scheduler_id TEXT,
    p_scheduler_session_id TEXT,
    p_fencing_token BIGINT,
    p_expected_lease_version BIGINT,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_request_hash TEXT,
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
    lease_row public.execution_leases%ROWTYPE;
    profile_row public.scheduler_lease_profiles%ROWTYPE;
    current_clock TIMESTAMPTZ;
    new_expires_at TIMESTAMPTZ;
    renew_event_id TEXT;
    event_sequence BIGINT;
    lock_count INTEGER;
    result_payload JSONB;
BEGIN
    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key,
        request_hash, status, result
    ) VALUES (
        p_command_id, p_project_id, 'scheduler.renew_lease',
        p_idempotency_key, p_request_hash, 'PROCESSING', '{}'::jsonb
    ) ON CONFLICT DO NOTHING;
    SELECT * INTO command_row
    FROM public.command_receipts
    WHERE project_id=p_project_id
      AND command_type='scheduler.renew_lease'
      AND idempotency_key=p_idempotency_key
    FOR UPDATE;
    IF NOT FOUND OR command_row.request_hash <> p_request_hash THEN
        RAISE EXCEPTION 'SCHEDULER_IDEMPOTENCY_CONFLICT';
    END IF;
    IF command_row.status = 'APPLIED' THEN
        RETURN command_row.result->'response';
    END IF;
    IF p_actor_type <> 'scheduler' THEN
        RETURN public.hermes_scheduler_reject_command(
            p_project_id, p_command_id, 'scheduler.renew_lease',
            p_idempotency_key, p_request_hash, 'SCHEDULER_NOT_ADMITTED',
            p_actor_type, p_actor_id, ''
        );
    END IF;
    current_clock := clock_timestamp();
    SELECT * INTO lease_row
    FROM public.execution_leases
    WHERE lease_id=p_lease_id
      AND execution_request_id=p_execution_request_id
      AND project_id=p_project_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN public.hermes_scheduler_reject_command(p_project_id,p_command_id,'scheduler.renew_lease',p_idempotency_key,p_request_hash,'LEASE_NOT_FOUND',p_actor_type,p_actor_id,'');
    END IF;
    IF lease_row.lease_state <> 'ACTIVE' THEN
        RETURN public.hermes_scheduler_reject_command(p_project_id,p_command_id,'scheduler.renew_lease',p_idempotency_key,p_request_hash,'LEASE_NOT_ACTIVE',p_actor_type,p_actor_id,'');
    END IF;
    IF lease_row.expires_at <= current_clock THEN
        RETURN public.hermes_scheduler_reject_command(p_project_id,p_command_id,'scheduler.renew_lease',p_idempotency_key,p_request_hash,'LEASE_EXPIRED',p_actor_type,p_actor_id,'');
    END IF;
    IF lease_row.scheduler_id <> p_scheduler_id OR lease_row.scheduler_session_id <> p_scheduler_session_id THEN
        RETURN public.hermes_scheduler_reject_command(p_project_id,p_command_id,'scheduler.renew_lease',p_idempotency_key,p_request_hash,'LEASE_OWNER_MISMATCH',p_actor_type,p_actor_id,'');
    END IF;
    IF lease_row.fencing_token <> p_fencing_token THEN
        RETURN public.hermes_scheduler_reject_command(p_project_id,p_command_id,'scheduler.renew_lease',p_idempotency_key,p_request_hash,'FENCING_TOKEN_STALE',p_actor_type,p_actor_id,'');
    END IF;
    IF lease_row.lease_version <> p_expected_lease_version THEN
        RETURN public.hermes_scheduler_reject_command(p_project_id,p_command_id,'scheduler.renew_lease',p_idempotency_key,p_request_hash,'LEASE_VERSION_CONFLICT',p_actor_type,p_actor_id,'');
    END IF;
    SELECT * INTO profile_row
    FROM public.scheduler_lease_profiles
    WHERE profile_id=lease_row.profile_id AND profile_version=lease_row.profile_version;
    new_expires_at := LEAST(
        current_clock + (profile_row.max_extension_ms::text || ' milliseconds')::interval,
        lease_row.max_expires_at
    );
    IF new_expires_at <= lease_row.expires_at THEN
        RETURN public.hermes_scheduler_reject_command(p_project_id,p_command_id,'scheduler.renew_lease',p_idempotency_key,p_request_hash,'LEASE_RENEWAL_LIMIT_EXCEEDED',p_actor_type,p_actor_id,'');
    END IF;
    SELECT count(*)::INTEGER INTO lock_count
    FROM public.execution_lock_ownerships l
    WHERE l.lease_id=p_lease_id
      AND l.fencing_token=p_fencing_token
      AND l.lock_state='ACTIVE'
      AND l.expires_at > current_clock;
    IF lock_count <> jsonb_array_length(lease_row.lock_refs) THEN
        RETURN public.hermes_scheduler_reject_command(p_project_id,p_command_id,'scheduler.renew_lease',p_idempotency_key,p_request_hash,'LEASE_LOCK_OWNERSHIP_LOST',p_actor_type,p_actor_id,'');
    END IF;
    IF p_fault_point = 'after_renew_validated' THEN
        RAISE EXCEPTION 'injected scheduler crash: after_renew_validated';
    END IF;

    UPDATE public.execution_leases
    SET heartbeat_at=current_clock,
        expires_at=new_expires_at,
        lease_version=lease_version + 1
    WHERE lease_id=p_lease_id;
    UPDATE public.execution_lock_ownerships
    SET expires_at=new_expires_at
    WHERE lease_id=p_lease_id AND lock_state='ACTIVE';
    IF p_fault_point = 'after_renew_expiry_update' THEN
        RAISE EXCEPTION 'injected scheduler crash: after_renew_expiry_update';
    END IF;

    renew_event_id := 'evt-' || gen_random_uuid()::text;
    INSERT INTO public.event_log(
        event_id, event_type, schema_version, producer_type, producer_id,
        project_id, partition_key, command_id, correlation_id, causation_id,
        task_id, payload
    ) VALUES (
        renew_event_id, 'execution.lease_renewed', '1.0', p_actor_type, p_actor_id,
        p_project_id, p_project_id, p_command_id, p_command_id,
        lease_row.acquired_event_id, lease_row.task_id,
        jsonb_build_object(
            'execution_request_id', p_execution_request_id,
            'lease_id', p_lease_id,
            'scheduler_id', p_scheduler_id,
            'scheduler_session_id', p_scheduler_session_id,
            'fencing_token', p_fencing_token,
            'lease_version', lease_row.lease_version + 1,
            'heartbeat_at', current_clock,
            'expires_at', new_expires_at,
            'reason', p_reason
        )
    ) RETURNING sequence INTO event_sequence;
    IF p_fault_point = 'after_event_before_outbox' THEN
        RAISE EXCEPTION 'injected scheduler crash: after_event_before_outbox';
    END IF;
    INSERT INTO public.outbox_messages(message_id, event_id, topic, partition_key, sequence, payload)
    SELECT 'msg-' || gen_random_uuid()::text, event_id, 'hermes.runtime.events',
           p_project_id, sequence, payload
    FROM public.event_log
    WHERE public.event_log.event_id=renew_event_id;
    result_payload := jsonb_build_object(
        'result_code', 'EXECUTION_LEASE_RENEWED',
        'execution_request_id', p_execution_request_id,
        'lease_id', p_lease_id,
        'fencing_token', p_fencing_token,
        'lease_version', lease_row.lease_version + 1,
        'expires_at', new_expires_at,
        'event_ids', jsonb_build_array(renew_event_id),
        'deduplicated', false
    );
    UPDATE public.command_receipts
    SET status='APPLIED',
        result=jsonb_build_object(
            'command_id', p_command_id,
            'status', 'APPLIED',
            'result_code', 'EXECUTION_LEASE_RENEWED',
            'event_ids', jsonb_build_array(renew_event_id),
            'response', result_payload
        ),
        completed_at=clock_timestamp()
    WHERE command_id=p_command_id AND status='PROCESSING';
    IF p_fault_point = 'after_receipt_before_commit' THEN
        RAISE EXCEPTION 'injected scheduler crash: after_receipt_before_commit';
    END IF;
    RETURN result_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_scheduler_relinquish_lease(
    p_project_id TEXT,
    p_execution_request_id TEXT,
    p_lease_id TEXT,
    p_scheduler_id TEXT,
    p_scheduler_session_id TEXT,
    p_fencing_token BIGINT,
    p_expected_lease_version BIGINT,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_request_hash TEXT,
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
    lease_row public.execution_leases%ROWTYPE;
    profile_row public.scheduler_lease_profiles%ROWTYPE;
    current_clock TIMESTAMPTZ;
    relinquished_event_id TEXT;
    requeued_event_id TEXT;
    relinquished_sequence BIGINT;
    requeued_sequence BIGINT;
    result_payload JSONB;
BEGIN
    INSERT INTO public.command_receipts(
        command_id, project_id, command_type, idempotency_key,
        request_hash, status, result
    ) VALUES (
        p_command_id, p_project_id, 'scheduler.relinquish_lease',
        p_idempotency_key, p_request_hash, 'PROCESSING', '{}'::jsonb
    ) ON CONFLICT DO NOTHING;
    SELECT * INTO command_row
    FROM public.command_receipts
    WHERE project_id=p_project_id
      AND command_type='scheduler.relinquish_lease'
      AND idempotency_key=p_idempotency_key
    FOR UPDATE;
    IF NOT FOUND OR command_row.request_hash <> p_request_hash THEN
        RAISE EXCEPTION 'SCHEDULER_IDEMPOTENCY_CONFLICT';
    END IF;
    IF command_row.status = 'APPLIED' THEN
        RETURN command_row.result->'response';
    END IF;
    current_clock := clock_timestamp();
    SELECT * INTO lease_row
    FROM public.execution_leases
    WHERE lease_id=p_lease_id
      AND execution_request_id=p_execution_request_id
      AND project_id=p_project_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN public.hermes_scheduler_reject_command(p_project_id,p_command_id,'scheduler.relinquish_lease',p_idempotency_key,p_request_hash,'LEASE_NOT_FOUND',p_actor_type,p_actor_id,'');
    END IF;
    IF lease_row.lease_state <> 'ACTIVE' THEN
        RETURN public.hermes_scheduler_reject_command(p_project_id,p_command_id,'scheduler.relinquish_lease',p_idempotency_key,p_request_hash,'LEASE_NOT_ACTIVE',p_actor_type,p_actor_id,'');
    END IF;
    IF lease_row.scheduler_id <> p_scheduler_id OR lease_row.scheduler_session_id <> p_scheduler_session_id THEN
        RETURN public.hermes_scheduler_reject_command(p_project_id,p_command_id,'scheduler.relinquish_lease',p_idempotency_key,p_request_hash,'LEASE_OWNER_MISMATCH',p_actor_type,p_actor_id,'');
    END IF;
    IF lease_row.fencing_token <> p_fencing_token THEN
        RETURN public.hermes_scheduler_reject_command(p_project_id,p_command_id,'scheduler.relinquish_lease',p_idempotency_key,p_request_hash,'FENCING_TOKEN_STALE',p_actor_type,p_actor_id,'');
    END IF;
    IF lease_row.lease_version <> p_expected_lease_version THEN
        RETURN public.hermes_scheduler_reject_command(p_project_id,p_command_id,'scheduler.relinquish_lease',p_idempotency_key,p_request_hash,'LEASE_VERSION_CONFLICT',p_actor_type,p_actor_id,'');
    END IF;
    SELECT * INTO profile_row
    FROM public.scheduler_lease_profiles
    WHERE profile_id=lease_row.profile_id AND profile_version=lease_row.profile_version;
    IF p_fault_point = 'after_relinquish_validated' THEN
        RAISE EXCEPTION 'injected scheduler crash: after_relinquish_validated';
    END IF;

    relinquished_event_id := 'evt-' || gen_random_uuid()::text;
    requeued_event_id := 'evt-' || gen_random_uuid()::text;
    UPDATE public.execution_leases
    SET lease_state='RELINQUISHED',
        lease_version=lease_version + 1,
        terminal_reason='LEASE_RELINQUISHED',
        terminal_command_id=p_command_id,
        terminal_at=current_clock,
        terminal_event_id=relinquished_event_id
    WHERE lease_id=p_lease_id;
    UPDATE public.execution_lock_ownerships
    SET lock_state='RELEASED', released_at=current_clock
    WHERE lease_id=p_lease_id AND lock_state='ACTIVE';
    IF p_fault_point = 'after_relinquish_before_requeue' THEN
        RAISE EXCEPTION 'injected scheduler crash: after_relinquish_before_requeue';
    END IF;
    UPDATE public.execution_request_current_states
    SET request_state='QUEUED',
        request_version=request_version + 1,
        current_lease_id=NULL,
        updated_at=current_clock,
        command_id=p_command_id
    WHERE execution_request_id=p_execution_request_id;
    UPDATE public.execution_queue_current_states
    SET queue_state='PENDING',
        current_lease_id=NULL,
        available_at=current_clock + (profile_row.requeue_backoff_ms::text || ' milliseconds')::interval,
        updated_at=current_clock,
        command_id=p_command_id
    WHERE queue_item_id=lease_row.queue_item_id;

    INSERT INTO public.execution_lease_state_history(
        history_id, lease_id, execution_request_id, from_state, to_state,
        lease_version, fencing_token, reason_code, command_id, event_id
    ) VALUES (
        'lease-hist-' || gen_random_uuid()::text, p_lease_id,
        p_execution_request_id, 'ACTIVE', 'RELINQUISHED',
        lease_row.lease_version + 1, p_fencing_token,
        'LEASE_RELINQUISHED', p_command_id, relinquished_event_id
    );
    INSERT INTO public.event_log(
        event_id, event_type, schema_version, producer_type, producer_id,
        project_id, partition_key, command_id, correlation_id, causation_id,
        task_id, payload
    ) VALUES (
        relinquished_event_id, 'execution.lease_relinquished', '1.0',
        p_actor_type, p_actor_id, p_project_id, p_project_id,
        p_command_id, p_command_id, lease_row.acquired_event_id, lease_row.task_id,
        jsonb_build_object(
            'execution_request_id', p_execution_request_id,
            'queue_item_id', lease_row.queue_item_id,
            'lease_id', p_lease_id,
            'fencing_token', p_fencing_token,
            'lease_version', lease_row.lease_version + 1,
            'reason', p_reason
        )
    ) RETURNING sequence INTO relinquished_sequence;
    INSERT INTO public.event_log(
        event_id, event_type, schema_version, producer_type, producer_id,
        project_id, partition_key, command_id, correlation_id, causation_id,
        task_id, payload
    ) VALUES (
        requeued_event_id, 'execution.requeued', '1.0',
        p_actor_type, p_actor_id, p_project_id, p_project_id,
        p_command_id, p_command_id, relinquished_event_id, lease_row.task_id,
        jsonb_build_object(
            'execution_request_id', p_execution_request_id,
            'queue_item_id', lease_row.queue_item_id,
            'request_state', 'QUEUED',
            'queue_state', 'PENDING',
            'available_at', (
                SELECT available_at FROM public.execution_queue_current_states
                WHERE queue_item_id=lease_row.queue_item_id
            ),
            'previous_lease_id', p_lease_id,
            'previous_fencing_token', p_fencing_token
        )
    ) RETURNING sequence INTO requeued_sequence;
    INSERT INTO public.outbox_messages(message_id, event_id, topic, partition_key, sequence, payload)
    SELECT 'msg-' || gen_random_uuid()::text, event_id, 'hermes.runtime.events',
           p_project_id, sequence, payload
    FROM public.event_log
    WHERE event_id IN (relinquished_event_id, requeued_event_id);
    result_payload := jsonb_build_object(
        'result_code', 'EXECUTION_LEASE_RELINQUISHED',
        'execution_request_id', p_execution_request_id,
        'queue_item_id', lease_row.queue_item_id,
        'lease_id', p_lease_id,
        'fencing_token', p_fencing_token,
        'request_state', 'QUEUED',
        'queue_state', 'PENDING',
        'event_ids', jsonb_build_array(relinquished_event_id, requeued_event_id),
        'deduplicated', false
    );
    UPDATE public.command_receipts
    SET status='APPLIED',
        result=jsonb_build_object(
            'command_id', p_command_id,
            'status', 'APPLIED',
            'result_code', 'EXECUTION_LEASE_RELINQUISHED',
            'event_ids', jsonb_build_array(relinquished_event_id, requeued_event_id),
            'response', result_payload
        ),
        completed_at=clock_timestamp()
    WHERE command_id=p_command_id AND status='PROCESSING';
    IF p_fault_point = 'after_receipt_before_commit' THEN
        RAISE EXCEPTION 'injected scheduler crash: after_receipt_before_commit';
    END IF;
    RETURN result_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_validate_current_lease(
    p_execution_request_id TEXT,
    p_lease_id TEXT,
    p_scheduler_id TEXT,
    p_scheduler_session_id TEXT,
    p_fencing_token BIGINT,
    p_observed_request_version BIGINT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    lease_row public.execution_leases%ROWTYPE;
    request_row public.execution_request_current_states%ROWTYPE;
    current_clock TIMESTAMPTZ;
BEGIN
    current_clock := clock_timestamp();
    SELECT * INTO lease_row
    FROM public.execution_leases
    WHERE lease_id=p_lease_id AND execution_request_id=p_execution_request_id;
    SELECT * INTO request_row
    FROM public.execution_request_current_states
    WHERE execution_request_id=p_execution_request_id;
    RETURN jsonb_build_object(
        'valid',
        lease_row.lease_id IS NOT NULL
        AND request_row.current_lease_id = p_lease_id
        AND request_row.request_state = 'LEASED'
        AND lease_row.lease_state = 'ACTIVE'
        AND lease_row.scheduler_id = p_scheduler_id
        AND lease_row.scheduler_session_id = p_scheduler_session_id
        AND lease_row.fencing_token = p_fencing_token
        AND lease_row.expires_at > current_clock
        AND (p_observed_request_version IS NULL OR request_row.request_version = p_observed_request_version),
        'reason_code',
        CASE
            WHEN lease_row.lease_id IS NULL THEN 'LEASE_NOT_FOUND'
            WHEN lease_row.lease_state <> 'ACTIVE' THEN 'LEASE_NOT_ACTIVE'
            WHEN lease_row.expires_at <= current_clock THEN 'LEASE_EXPIRED'
            WHEN lease_row.scheduler_id <> p_scheduler_id OR lease_row.scheduler_session_id <> p_scheduler_session_id THEN 'LEASE_OWNER_MISMATCH'
            WHEN lease_row.fencing_token <> p_fencing_token THEN 'FENCING_TOKEN_STALE'
            WHEN p_observed_request_version IS NOT NULL AND request_row.request_version <> p_observed_request_version THEN 'LEASE_VERSION_CONFLICT'
            ELSE 'LEASE_CURRENT'
        END,
        'execution_request_id', p_execution_request_id,
        'lease_id', p_lease_id,
        'current_fencing_token', COALESCE(request_row.current_fencing_token, 0),
        'request_version', request_row.request_version
    );
END;
$$;

ALTER TABLE public.scheduler_lease_profiles OWNER TO hermes_scheduler_owner;
ALTER TABLE public.scheduler_instances OWNER TO hermes_scheduler_owner;
ALTER TABLE public.execution_request_current_states OWNER TO hermes_scheduler_owner;
ALTER TABLE public.execution_queue_current_states OWNER TO hermes_scheduler_owner;
ALTER TABLE public.execution_fencing_counters OWNER TO hermes_scheduler_owner;
ALTER TABLE public.execution_leases OWNER TO hermes_scheduler_owner;
ALTER TABLE public.execution_lease_state_history OWNER TO hermes_scheduler_owner;
ALTER TABLE public.execution_lock_ownerships OWNER TO hermes_scheduler_owner;
ALTER TABLE public.execution_scheduler_rejections OWNER TO hermes_scheduler_owner;
ALTER FUNCTION public.hermes_seed_execution_request_current_state() OWNER TO hermes_scheduler_owner;
ALTER FUNCTION public.hermes_seed_execution_queue_current_state() OWNER TO hermes_scheduler_owner;
ALTER FUNCTION public.hermes_scheduler_secret_guard(JSONB) OWNER TO hermes_scheduler_owner;
ALTER FUNCTION public.hermes_scheduler_reject_command(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_scheduler_owner;
ALTER FUNCTION public.hermes_scheduler_register(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_scheduler_owner;
ALTER FUNCTION public.hermes_scheduler_acquire_lease(TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_scheduler_owner;
ALTER FUNCTION public.hermes_scheduler_renew_lease(TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_scheduler_owner;
ALTER FUNCTION public.hermes_scheduler_relinquish_lease(TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_scheduler_owner;
ALTER FUNCTION public.hermes_validate_current_lease(TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT) OWNER TO hermes_scheduler_owner;

GRANT SELECT ON public.execution_requests, public.execution_queue_items,
    public.execution_reservation_bindings, public.resource_reservations,
    public.worker_template_availability, public.scheduler_lease_profiles,
    public.scheduler_instances, public.execution_request_current_states,
    public.execution_queue_current_states, public.execution_leases,
    public.execution_lock_ownerships TO hermes_scheduler_owner;
GRANT SELECT, INSERT, UPDATE ON public.scheduler_instances,
    public.execution_request_current_states, public.execution_queue_current_states,
    public.execution_fencing_counters, public.execution_leases,
    public.execution_lock_ownerships, public.execution_lease_state_history,
    public.execution_scheduler_rejections, public.command_receipts
    TO hermes_scheduler_owner;
GRANT SELECT, INSERT ON public.event_log, public.outbox_messages, public.audit_records
    TO hermes_scheduler_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_scheduler_owner;

GRANT SELECT, INSERT, UPDATE ON public.command_receipts TO hermes_scheduler_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_scheduler_register(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO hermes_scheduler_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_scheduler_acquire_lease(TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO hermes_scheduler_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_scheduler_renew_lease(TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO hermes_scheduler_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_scheduler_relinquish_lease(TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO hermes_scheduler_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_validate_current_lease(TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT)
    TO hermes_scheduler_runtime;
GRANT SELECT ON public.scheduler_lease_profiles, public.scheduler_instances,
    public.execution_request_current_states, public.execution_queue_current_states,
    public.execution_leases, public.execution_lease_state_history,
    public.execution_lock_ownerships
    TO hermes_scheduler_runtime, hermes_read_only_runtime;

REVOKE ALL ON public.scheduler_lease_profiles, public.scheduler_instances,
    public.execution_request_current_states, public.execution_queue_current_states,
    public.execution_fencing_counters, public.execution_leases,
    public.execution_lease_state_history, public.execution_lock_ownerships,
    public.execution_scheduler_rejections FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_seed_execution_request_current_state() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_seed_execution_queue_current_state() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_scheduler_secret_guard(JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_scheduler_reject_command(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_scheduler_register(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_scheduler_acquire_lease(TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_scheduler_renew_lease(TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_scheduler_relinquish_lease(TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_validate_current_lease(TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT) FROM PUBLIC;

REVOKE INSERT, UPDATE, DELETE ON public.scheduler_instances,
    public.execution_request_current_states, public.execution_queue_current_states,
    public.execution_fencing_counters, public.execution_leases,
    public.execution_lease_state_history, public.execution_lock_ownerships,
    public.execution_scheduler_rejections
FROM hermes_worker_runtime, hermes_verifier_runtime, hermes_control_plane_runtime,
     hermes_read_only_runtime, hermes_capability_runtime, hermes_accounting_runtime,
     hermes_selection_runtime, hermes_policy_runtime, hermes_risk_runtime,
     hermes_planner_runtime, hermes_diagnosis_runtime, hermes_situation_runtime,
     hermes_execution_runtime, hermes_scheduler_runtime;
REVOKE EXECUTE ON FUNCTION public.hermes_scheduler_register(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
FROM hermes_worker_runtime, hermes_verifier_runtime, hermes_control_plane_runtime,
     hermes_read_only_runtime, hermes_capability_runtime, hermes_accounting_runtime,
     hermes_selection_runtime, hermes_policy_runtime, hermes_risk_runtime,
     hermes_planner_runtime, hermes_diagnosis_runtime, hermes_situation_runtime,
     hermes_execution_runtime, PUBLIC;
REVOKE EXECUTE ON FUNCTION public.hermes_scheduler_acquire_lease(TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
FROM hermes_worker_runtime, hermes_verifier_runtime, hermes_control_plane_runtime,
     hermes_read_only_runtime, hermes_capability_runtime, hermes_accounting_runtime,
     hermes_selection_runtime, hermes_policy_runtime, hermes_risk_runtime,
     hermes_planner_runtime, hermes_diagnosis_runtime, hermes_situation_runtime,
     hermes_execution_runtime, PUBLIC;
REVOKE EXECUTE ON FUNCTION public.hermes_scheduler_renew_lease(TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
FROM hermes_worker_runtime, hermes_verifier_runtime, hermes_control_plane_runtime,
     hermes_read_only_runtime, hermes_capability_runtime, hermes_accounting_runtime,
     hermes_selection_runtime, hermes_policy_runtime, hermes_risk_runtime,
     hermes_planner_runtime, hermes_diagnosis_runtime, hermes_situation_runtime,
     hermes_execution_runtime, PUBLIC;
REVOKE EXECUTE ON FUNCTION public.hermes_scheduler_relinquish_lease(TEXT,TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
FROM hermes_worker_runtime, hermes_verifier_runtime, hermes_control_plane_runtime,
     hermes_read_only_runtime, hermes_capability_runtime, hermes_accounting_runtime,
     hermes_selection_runtime, hermes_policy_runtime, hermes_risk_runtime,
     hermes_planner_runtime, hermes_diagnosis_runtime, hermes_situation_runtime,
     hermes_execution_runtime, PUBLIC;
REVOKE EXECUTE ON FUNCTION public.hermes_validate_current_lease(TEXT,TEXT,TEXT,TEXT,BIGINT,BIGINT)
FROM hermes_worker_runtime, hermes_verifier_runtime, hermes_control_plane_runtime,
     hermes_read_only_runtime, hermes_capability_runtime, hermes_accounting_runtime,
     hermes_selection_runtime, hermes_policy_runtime, hermes_risk_runtime,
     hermes_planner_runtime, hermes_diagnosis_runtime, hermes_situation_runtime,
     hermes_execution_runtime, PUBLIC;
REVOKE CREATE ON SCHEMA public FROM hermes_scheduler_runtime;

COMMENT ON TABLE public.execution_request_current_states IS
'P2-3 mutable scheduler authority for ExecutionRequest QUEUED/LEASED state. P2-2 execution_requests remains immutable admitted snapshot.';
COMMENT ON TABLE public.execution_queue_current_states IS
'P2-3 mutable durable queue claim authority. Fairness is best effort: priority, available_at, enqueued_at, queue_item_id; locked/conflicting items may be skipped.';
COMMENT ON TABLE public.execution_leases IS
'P2-3 PostgreSQL-clock Lease authority with monotonic per-request fencing token and one ACTIVE lease per Request/Queue item.';
COMMENT ON TABLE public.execution_lock_ownerships IS
'P2-3 execution lock ownership bound to Lease ID and fencing token; active conflicting scopes are DB-atomic.';
