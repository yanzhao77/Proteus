-- P0 delivery/recovery slice. The former global identity is retained only as
-- an internal migration-order key; protocol sequence is partition-local.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'event_log'
          AND column_name = 'global_sequence'
    ) THEN
        ALTER TABLE public.event_log RENAME COLUMN sequence TO global_sequence;
    END IF;
END;
$$;

DROP TRIGGER IF EXISTS event_log_immutable ON public.event_log;

CREATE TABLE IF NOT EXISTS public.event_partition_sequences (
    partition_key TEXT PRIMARY KEY,
    last_sequence BIGINT NOT NULL CHECK (last_sequence >= 0)
);

ALTER TABLE public.event_log ADD COLUMN IF NOT EXISTS sequence BIGINT;

WITH numbered AS (
    SELECT event_id,
           row_number() OVER (
               PARTITION BY partition_key ORDER BY global_sequence
           )::BIGINT AS local_sequence
    FROM public.event_log
)
UPDATE public.event_log e
SET sequence = numbered.local_sequence
FROM numbered
WHERE e.event_id = numbered.event_id AND e.sequence IS NULL;

INSERT INTO public.event_partition_sequences(partition_key, last_sequence)
SELECT partition_key, max(sequence)
FROM public.event_log
GROUP BY partition_key
ON CONFLICT (partition_key) DO UPDATE
SET last_sequence = GREATEST(
    public.event_partition_sequences.last_sequence,
    EXCLUDED.last_sequence
);

ALTER TABLE public.event_log ALTER COLUMN sequence SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS event_log_partition_sequence_unique
    ON public.event_log(partition_key, sequence);

UPDATE public.outbox_messages o
SET sequence = e.sequence
FROM public.event_log e
WHERE e.event_id = o.event_id AND o.sequence IS DISTINCT FROM e.sequence;

CREATE UNIQUE INDEX IF NOT EXISTS outbox_partition_sequence_unique
    ON public.outbox_messages(partition_key, sequence);

ALTER TABLE public.event_log
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT,
    ADD COLUMN IF NOT EXISTS causation_id TEXT,
    ADD COLUMN IF NOT EXISTS trace_id TEXT,
    ADD COLUMN IF NOT EXISTS task_id TEXT,
    ADD COLUMN IF NOT EXISTS run_id TEXT,
    ADD COLUMN IF NOT EXISTS classification TEXT NOT NULL DEFAULT 'INTERNAL';

UPDATE public.event_log e
SET idempotency_key = c.idempotency_key
FROM public.command_receipts c
WHERE c.command_id = e.command_id AND e.idempotency_key IS NULL;
UPDATE public.event_log
SET idempotency_key = command_id
WHERE idempotency_key IS NULL;
ALTER TABLE public.event_log ALTER COLUMN idempotency_key SET NOT NULL;

CREATE OR REPLACE FUNCTION public.hermes_assign_partition_sequence()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.idempotency_key IS NULL THEN
        SELECT idempotency_key INTO NEW.idempotency_key
        FROM public.command_receipts
        WHERE command_id = NEW.command_id;
        IF NEW.idempotency_key IS NULL THEN
            RAISE EXCEPTION 'EVENT_COMMAND_RECEIPT_REQUIRED';
        END IF;
    END IF;
    IF NEW.sequence IS NOT NULL THEN
        RAISE EXCEPTION 'EVENT_SEQUENCE_ASSIGNED_BY_DATABASE';
    END IF;
    INSERT INTO public.event_partition_sequences(partition_key, last_sequence)
    VALUES (NEW.partition_key, 1)
    ON CONFLICT (partition_key) DO UPDATE
    SET last_sequence = public.event_partition_sequences.last_sequence + 1
    RETURNING last_sequence INTO NEW.sequence;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS event_log_assign_partition_sequence ON public.event_log;
CREATE TRIGGER event_log_assign_partition_sequence
BEFORE INSERT ON public.event_log
FOR EACH ROW EXECUTE FUNCTION public.hermes_assign_partition_sequence();

CREATE TRIGGER event_log_immutable
BEFORE UPDATE OR DELETE ON public.event_log
FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_immutable_change();

ALTER TABLE public.outbox_messages
    DROP CONSTRAINT IF EXISTS outbox_messages_status_check;
ALTER TABLE public.outbox_messages
    ADD CONSTRAINT outbox_messages_status_check CHECK (
        status IN ('PENDING', 'LEASED', 'PUBLISHED', 'DEAD_LETTERED')
    );
ALTER TABLE public.outbox_messages
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0
        CHECK (attempt_count >= 0),
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS lease_owner TEXT,
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS claim_token TEXT,
    ADD COLUMN IF NOT EXISTS last_error_category TEXT,
    ADD COLUMN IF NOT EXISTS last_error_message TEXT,
    ADD COLUMN IF NOT EXISTS dead_lettered_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS redrive_count INTEGER NOT NULL DEFAULT 0
        CHECK (redrive_count >= 0),
    ADD COLUMN IF NOT EXISTS status_version BIGINT NOT NULL DEFAULT 0
        CHECK (status_version >= 0);

CREATE INDEX IF NOT EXISTS outbox_claimable_index
    ON public.outbox_messages(status, next_attempt_at, lease_expires_at, created_at);

ALTER TABLE public.consumer_inbox
    ADD COLUMN IF NOT EXISTS partition_key TEXT,
    ADD COLUMN IF NOT EXISTS sequence BIGINT,
    ADD COLUMN IF NOT EXISTS schema_version TEXT,
    ADD COLUMN IF NOT EXISTS processing_result JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS raw_envelope JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE public.consumer_inbox i
SET partition_key = e.partition_key,
    sequence = e.sequence,
    schema_version = e.schema_version
FROM public.event_log e
WHERE e.event_id = i.event_id
  AND (i.partition_key IS NULL OR i.sequence IS NULL OR i.schema_version IS NULL);

ALTER TABLE public.consumer_inbox
    ALTER COLUMN partition_key SET NOT NULL,
    ALTER COLUMN sequence SET NOT NULL,
    ALTER COLUMN schema_version SET NOT NULL;

-- Old global/max checkpoints cannot be trusted. Rebuild only the contiguous
-- prefix proven by Inbox rows after deterministic Event resequencing.
UPDATE public.consumer_checkpoints SET last_sequence = 0;
WITH maxima AS (
    SELECT consumer_id, partition_key, max(sequence) AS max_sequence
    FROM public.consumer_inbox
    GROUP BY consumer_id, partition_key
), contiguous AS (
    SELECT m.consumer_id, m.partition_key, max(candidate)::BIGINT AS last_sequence
    FROM maxima m
    CROSS JOIN LATERAL generate_series(1, m.max_sequence) candidate
    WHERE NOT EXISTS (
        SELECT 1 FROM generate_series(1, candidate) required_sequence
        WHERE NOT EXISTS (
            SELECT 1 FROM public.consumer_inbox i
            WHERE i.consumer_id = m.consumer_id
              AND i.partition_key = m.partition_key
              AND i.sequence = required_sequence
        )
    )
    GROUP BY m.consumer_id, m.partition_key
)
UPDATE public.consumer_checkpoints c
SET last_sequence = contiguous.last_sequence, updated_at = now()
FROM contiguous
WHERE c.consumer_id = contiguous.consumer_id
  AND c.partition_key = contiguous.partition_key;

COMMENT ON COLUMN public.consumer_checkpoints.last_sequence IS
'Last contiguous partition-local sequence; it must never be advanced by maximum received sequence.';

CREATE TABLE IF NOT EXISTS public.outbox_delivery_attempts (
    attempt_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES public.outbox_messages(message_id),
    event_id TEXT NOT NULL REFERENCES public.event_log(event_id),
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    lease_owner TEXT NOT NULL,
    claim_token TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('CLAIMED', 'PUBLISHED', 'RETRY_SCHEDULED', 'DEAD_LETTERED')
    ),
    error_category TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.outbox_delivery_attempts
    DROP CONSTRAINT IF EXISTS outbox_delivery_attempts_message_id_attempt_number_outcome_key;
ALTER TABLE public.outbox_delivery_attempts
    DROP CONSTRAINT IF EXISTS outbox_delivery_attempts_claim_outcome_unique;
ALTER TABLE public.outbox_delivery_attempts
    ADD CONSTRAINT outbox_delivery_attempts_claim_outcome_unique
    UNIQUE (message_id, claim_token, outcome);

CREATE TABLE IF NOT EXISTS public.outbox_delivery_dlq (
    dlq_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL UNIQUE REFERENCES public.outbox_messages(message_id),
    event_id TEXT NOT NULL REFERENCES public.event_log(event_id),
    partition_key TEXT NOT NULL,
    sequence BIGINT NOT NULL,
    original_envelope JSONB NOT NULL,
    failure_category TEXT NOT NULL,
    attempt_count INTEGER NOT NULL,
    first_failure_at TIMESTAMPTZ NOT NULL,
    last_failure_at TIMESTAMPTZ NOT NULL,
    last_error TEXT NOT NULL,
    trace_id TEXT,
    correlation_id TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'REDRIVEN')),
    redriven_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.outbox_redrive_records (
    redrive_id TEXT PRIMARY KEY,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    message_id TEXT NOT NULL REFERENCES public.outbox_messages(message_id),
    event_id TEXT NOT NULL REFERENCES public.event_log(event_id),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    authorization_ref TEXT NOT NULL,
    previous_version BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.consumer_pending_gaps (
    consumer_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    sequence BIGINT NOT NULL,
    raw_envelope JSONB NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING', 'PROCESSED', 'RECONCILE_REQUIRED')
    ),
    PRIMARY KEY (consumer_id, event_id),
    UNIQUE (consumer_id, partition_key, sequence)
);

CREATE TABLE IF NOT EXISTS public.consumer_quarantine (
    quarantine_id TEXT PRIMARY KEY,
    consumer_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    partition_key TEXT,
    sequence BIGINT,
    original_envelope JSONB NOT NULL,
    failure_category TEXT NOT NULL CHECK (
        failure_category IN ('SCHEMA', 'UNSUPPORTED_SCHEMA', 'UNKNOWN_CRITICAL_VALUE',
                             'LATE_EVENT', 'EFFECT_FAILURE', 'GAP_TIMEOUT')
    ),
    attempt_count INTEGER NOT NULL DEFAULT 1,
    first_failure_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_failure_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'RELEASED')),
    UNIQUE (consumer_id, event_id, failure_category)
);

CREATE TABLE IF NOT EXISTS public.local_transport_publications (
    publication_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES public.event_log(event_id),
    partition_key TEXT NOT NULL,
    sequence BIGINT NOT NULL,
    envelope JSONB NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.delivery_operational_alerts (
    alert_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    consumer_id TEXT,
    event_id TEXT,
    partition_key TEXT,
    detail TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.delivery_metric_counters (
    metric_name TEXT PRIMARY KEY,
    metric_value BIGINT NOT NULL DEFAULT 0 CHECK (metric_value >= 0)
);

CREATE OR REPLACE FUNCTION public.hermes_increment_delivery_metric(
    p_metric_name TEXT
) RETURNS VOID
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    INSERT INTO public.delivery_metric_counters(metric_name, metric_value)
    VALUES (p_metric_name, 1)
    ON CONFLICT (metric_name) DO UPDATE
    SET metric_value = public.delivery_metric_counters.metric_value + 1
$$;

CREATE OR REPLACE FUNCTION public.hermes_consumer_park_gap(
    p_consumer_id TEXT, p_event_id TEXT, p_partition_key TEXT,
    p_sequence BIGINT, p_raw_envelope JSONB, p_partition_limit INTEGER
) RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE pending_count INTEGER;
BEGIN
    IF p_partition_limit <= 0 THEN RAISE EXCEPTION 'INVALID_GAP_LIMIT'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.event_log
        WHERE event_id = p_event_id AND partition_key = p_partition_key
          AND sequence = p_sequence
    ) THEN RAISE EXCEPTION 'EVENT_ENVELOPE_IDENTITY_MISMATCH'; END IF;
    SELECT count(*) INTO pending_count
    FROM public.consumer_pending_gaps
    WHERE consumer_id = p_consumer_id AND partition_key = p_partition_key
      AND status = 'PENDING';
    IF pending_count >= p_partition_limit AND NOT EXISTS (
        SELECT 1 FROM public.consumer_pending_gaps
        WHERE consumer_id = p_consumer_id AND event_id = p_event_id
    ) THEN
        INSERT INTO public.consumer_quarantine(
            quarantine_id, consumer_id, event_id, partition_key, sequence,
            original_envelope, failure_category, last_error
        ) VALUES ('cq-' || gen_random_uuid()::text, p_consumer_id, p_event_id,
                  p_partition_key, p_sequence, p_raw_envelope, 'GAP_TIMEOUT',
                  'bounded pending-gap limit reached')
        ON CONFLICT (consumer_id, event_id, failure_category) DO UPDATE
        SET attempt_count = public.consumer_quarantine.attempt_count + 1,
            last_failure_at = now(), last_error = EXCLUDED.last_error;
        INSERT INTO public.delivery_operational_alerts(
            alert_id, category, consumer_id, event_id, partition_key, detail
        ) VALUES ('alert-' || gen_random_uuid()::text, 'GAP_LIMIT_REACHED',
                  p_consumer_id, p_event_id, p_partition_key,
                  'bounded pending-gap limit reached');
        RETURN 'RECONCILE_REQUIRED';
    END IF;
    INSERT INTO public.consumer_pending_gaps(
        consumer_id, event_id, partition_key, sequence, raw_envelope
    ) VALUES (p_consumer_id, p_event_id, p_partition_key, p_sequence,
              p_raw_envelope)
    ON CONFLICT (consumer_id, event_id) DO UPDATE
    SET last_seen_at = now();
    RETURN 'GAP_PARKED';
END;
$$;

DROP FUNCTION IF EXISTS public.hermes_consumer_commit_next(
    TEXT, TEXT, TEXT, BIGINT, TEXT, JSONB, JSONB
);
CREATE OR REPLACE FUNCTION public.hermes_consumer_commit_next(
    p_consumer_id TEXT, p_event_id TEXT, p_partition_key TEXT,
    p_sequence BIGINT, p_schema_version TEXT, p_processing_result JSONB,
    p_raw_envelope JSONB, p_fault_point TEXT DEFAULT NULL
) RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE checkpoint BIGINT;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.event_log
        WHERE event_id = p_event_id AND partition_key = p_partition_key
          AND sequence = p_sequence AND schema_version = p_schema_version
    ) THEN RAISE EXCEPTION 'EVENT_ENVELOPE_IDENTITY_MISMATCH'; END IF;
    INSERT INTO public.consumer_checkpoints(consumer_id, partition_key, last_sequence)
    VALUES (p_consumer_id, p_partition_key, 0) ON CONFLICT DO NOTHING;
    SELECT last_sequence INTO checkpoint
    FROM public.consumer_checkpoints
    WHERE consumer_id = p_consumer_id AND partition_key = p_partition_key
    FOR UPDATE;
    IF EXISTS (
        SELECT 1 FROM public.consumer_inbox
        WHERE consumer_id = p_consumer_id AND event_id = p_event_id
    ) THEN
        PERFORM public.hermes_increment_delivery_metric('consumer_duplicate');
        RETURN 'DUPLICATE';
    END IF;
    IF p_sequence <> checkpoint + 1 THEN
        RAISE EXCEPTION 'CONSUMER_SEQUENCE_NOT_CONTIGUOUS';
    END IF;
    IF p_fault_point = 'before_effect' THEN
        RAISE EXCEPTION 'INJECTED_CONSUMER_CRASH_BEFORE_EFFECT';
    END IF;
    INSERT INTO public.consumer_effects(consumer_id, event_id, effect_count)
    VALUES (p_consumer_id, p_event_id, 1);
    IF p_fault_point = 'after_effect_before_inbox' THEN
        RAISE EXCEPTION 'INJECTED_CONSUMER_CRASH_AFTER_EFFECT';
    END IF;
    INSERT INTO public.consumer_inbox(
        consumer_id, event_id, partition_key, sequence, schema_version,
        processing_result, raw_envelope
    ) VALUES (p_consumer_id, p_event_id, p_partition_key, p_sequence,
              p_schema_version, p_processing_result, p_raw_envelope);
    IF p_fault_point = 'after_inbox_before_checkpoint' THEN
        RAISE EXCEPTION 'INJECTED_CONSUMER_CRASH_AFTER_INBOX';
    END IF;
    UPDATE public.consumer_checkpoints
    SET last_sequence = p_sequence, updated_at = now()
    WHERE consumer_id = p_consumer_id AND partition_key = p_partition_key
      AND last_sequence = checkpoint;
    UPDATE public.consumer_pending_gaps
    SET status = 'PROCESSED', last_seen_at = now()
    WHERE consumer_id = p_consumer_id AND event_id = p_event_id;
    RETURN 'APPLIED';
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_consumer_quarantine(
    p_consumer_id TEXT, p_event_id TEXT, p_partition_key TEXT,
    p_sequence BIGINT, p_raw_envelope JSONB, p_failure_category TEXT,
    p_last_error TEXT
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF p_failure_category NOT IN (
        'SCHEMA', 'UNSUPPORTED_SCHEMA', 'UNKNOWN_CRITICAL_VALUE',
        'LATE_EVENT', 'EFFECT_FAILURE', 'GAP_TIMEOUT'
    ) THEN RAISE EXCEPTION 'INVALID_QUARANTINE_CATEGORY'; END IF;
    INSERT INTO public.consumer_quarantine(
        quarantine_id, consumer_id, event_id, partition_key, sequence,
        original_envelope, failure_category, last_error
    ) VALUES ('cq-' || gen_random_uuid()::text, p_consumer_id, p_event_id,
              p_partition_key, p_sequence, p_raw_envelope,
              p_failure_category, left(COALESCE(p_last_error, ''), 2000))
    ON CONFLICT (consumer_id, event_id, failure_category) DO UPDATE
    SET attempt_count = public.consumer_quarantine.attempt_count + 1,
        last_failure_at = now(), last_error = EXCLUDED.last_error;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_event_envelope(p_event_id TEXT)
RETURNS JSONB
LANGUAGE sql
STABLE
SET search_path = pg_catalog
AS $$
    SELECT jsonb_build_object(
        'event_id', e.event_id,
        'event_type', e.event_type,
        'schema_version', e.schema_version,
        'occurred_at', e.occurred_at,
        'recorded_at', e.recorded_at,
        'producer', jsonb_build_object('type', e.producer_type, 'id', e.producer_id),
        'project_id', e.project_id,
        'partition_key', e.partition_key,
        'sequence', e.sequence,
        'idempotency_key', e.idempotency_key,
        'correlation_id', e.correlation_id,
        'causation_id', e.causation_id,
        'trace_id', e.trace_id,
        'task_id', e.task_id,
        'run_id', e.run_id,
        'classification', e.classification,
        'payload', e.payload
    )
    FROM public.event_log e WHERE e.event_id = p_event_id
$$;

CREATE OR REPLACE FUNCTION public.hermes_claim_outbox(
    p_owner TEXT, p_now TIMESTAMPTZ, p_lease_seconds INTEGER,
    p_batch_size INTEGER, p_max_attempts INTEGER
) RETURNS TABLE (
    message_id TEXT, event_id TEXT, topic TEXT, partition_key TEXT,
    sequence BIGINT, claim_token TEXT, attempt_count INTEGER, envelope JSONB
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF NULLIF(btrim(p_owner), '') IS NULL OR p_lease_seconds <= 0
       OR p_batch_size <= 0 OR p_max_attempts <= 0 THEN
        RAISE EXCEPTION 'INVALID_RELAY_CLAIM';
    END IF;

    INSERT INTO public.outbox_delivery_dlq(
        dlq_id, message_id, event_id, partition_key, sequence, original_envelope,
        failure_category, attempt_count, first_failure_at, last_failure_at,
        last_error, trace_id, correlation_id
    )
    SELECT 'odlq-' || gen_random_uuid()::text, o.message_id, o.event_id,
           o.partition_key, o.sequence, public.hermes_event_envelope(o.event_id),
           'ATTEMPT_EXHAUSTED', o.attempt_count, o.created_at, p_now,
           COALESCE(o.last_error_message, 'attempt policy exhausted'),
           e.trace_id, e.correlation_id
    FROM public.outbox_messages o
    JOIN public.event_log e ON e.event_id = o.event_id
    WHERE o.attempt_count >= p_max_attempts
      AND (o.status = 'PENDING' OR
           (o.status = 'LEASED' AND o.lease_expires_at <= p_now))
    ON CONFLICT ON CONSTRAINT outbox_delivery_dlq_message_id_key DO NOTHING;

    UPDATE public.outbox_messages o
    SET status = 'DEAD_LETTERED', dead_lettered_at = p_now,
        lease_owner = NULL, lease_expires_at = NULL, claim_token = NULL,
        status_version = status_version + 1
    WHERE o.attempt_count >= p_max_attempts
      AND (o.status = 'PENDING' OR
           (o.status = 'LEASED' AND o.lease_expires_at <= p_now));

    RETURN QUERY
    WITH candidates AS (
        SELECT o.message_id
        FROM public.outbox_messages o
        WHERE o.attempt_count < p_max_attempts
          AND (
              (o.status = 'PENDING' AND o.next_attempt_at <= p_now)
              OR (o.status = 'LEASED' AND o.lease_expires_at <= p_now)
          )
        ORDER BY o.partition_key, o.sequence
        FOR UPDATE SKIP LOCKED
        LIMIT p_batch_size
    ), claimed AS (
        UPDATE public.outbox_messages o
        SET status = 'LEASED', attempt_count = o.attempt_count + 1,
            lease_owner = p_owner,
            lease_expires_at = p_now + make_interval(secs => p_lease_seconds),
            claim_token = gen_random_uuid()::text,
            last_error_category = NULL, last_error_message = NULL,
            status_version = o.status_version + 1
        FROM candidates c
        WHERE o.message_id = c.message_id
        RETURNING o.*
    ), attempts AS (
        INSERT INTO public.outbox_delivery_attempts(
            attempt_id, message_id, event_id, attempt_number,
            lease_owner, claim_token, outcome
        )
        SELECT 'oda-' || gen_random_uuid()::text, c.message_id, c.event_id,
               c.attempt_count, c.lease_owner, c.claim_token, 'CLAIMED'
        FROM claimed c
        RETURNING outbox_delivery_attempts.message_id
    )
    SELECT c.message_id, c.event_id, c.topic, c.partition_key, c.sequence,
           c.claim_token, c.attempt_count,
           public.hermes_event_envelope(c.event_id)
    FROM claimed c JOIN attempts a USING (message_id)
    ORDER BY c.partition_key, c.sequence;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_mark_outbox_published(
    p_message_id TEXT, p_owner TEXT, p_claim_token TEXT, p_now TIMESTAMPTZ
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE changed public.outbox_messages%ROWTYPE;
BEGIN
    UPDATE public.outbox_messages
    SET status = 'PUBLISHED', published_at = p_now,
        lease_owner = NULL, lease_expires_at = NULL, claim_token = NULL,
        status_version = status_version + 1
    WHERE message_id = p_message_id AND status = 'LEASED'
      AND lease_owner = p_owner AND claim_token = p_claim_token
    RETURNING * INTO changed;
    IF NOT FOUND THEN RETURN false; END IF;
    INSERT INTO public.outbox_delivery_attempts(
        attempt_id, message_id, event_id, attempt_number,
        lease_owner, claim_token, outcome
    ) VALUES ('oda-' || gen_random_uuid()::text, changed.message_id,
              changed.event_id, changed.attempt_count, p_owner, p_claim_token,
              'PUBLISHED');
    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_mark_outbox_failure(
    p_message_id TEXT, p_owner TEXT, p_claim_token TEXT, p_now TIMESTAMPTZ,
    p_retryable BOOLEAN, p_error_category TEXT, p_error_message TEXT,
    p_next_attempt_at TIMESTAMPTZ, p_max_attempts INTEGER
) RETURNS TEXT
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE current_row public.outbox_messages%ROWTYPE;
DECLARE next_status TEXT;
BEGIN
    SELECT * INTO current_row FROM public.outbox_messages
    WHERE message_id = p_message_id AND status = 'LEASED'
      AND lease_owner = p_owner AND claim_token = p_claim_token
    FOR UPDATE;
    IF NOT FOUND THEN RETURN 'STALE_CLAIM'; END IF;
    next_status := CASE
        WHEN p_retryable AND current_row.attempt_count < p_max_attempts
            THEN 'PENDING' ELSE 'DEAD_LETTERED' END;
    UPDATE public.outbox_messages
    SET status = next_status,
        next_attempt_at = CASE WHEN next_status = 'PENDING'
                              THEN p_next_attempt_at ELSE next_attempt_at END,
        lease_owner = NULL, lease_expires_at = NULL, claim_token = NULL,
        last_error_category = p_error_category,
        last_error_message = left(COALESCE(p_error_message, ''), 2000),
        dead_lettered_at = CASE WHEN next_status = 'DEAD_LETTERED'
                               THEN p_now ELSE NULL END,
        status_version = status_version + 1
    WHERE message_id = p_message_id;
    INSERT INTO public.outbox_delivery_attempts(
        attempt_id, message_id, event_id, attempt_number, lease_owner,
        claim_token, outcome, error_category, error_message
    ) VALUES ('oda-' || gen_random_uuid()::text, current_row.message_id,
              current_row.event_id, current_row.attempt_count, p_owner,
              p_claim_token, CASE WHEN next_status = 'PENDING'
              THEN 'RETRY_SCHEDULED' ELSE 'DEAD_LETTERED' END,
              p_error_category, left(COALESCE(p_error_message, ''), 2000));
    IF next_status = 'DEAD_LETTERED' THEN
        INSERT INTO public.outbox_delivery_dlq(
            dlq_id, message_id, event_id, partition_key, sequence,
            original_envelope, failure_category, attempt_count,
            first_failure_at, last_failure_at, last_error, trace_id,
            correlation_id
        )
        SELECT 'odlq-' || gen_random_uuid()::text, current_row.message_id,
               current_row.event_id, current_row.partition_key,
               current_row.sequence,
               public.hermes_event_envelope(current_row.event_id),
               p_error_category, current_row.attempt_count,
               current_row.created_at, p_now,
               left(COALESCE(p_error_message, ''), 2000), e.trace_id,
               e.correlation_id
        FROM public.event_log e WHERE e.event_id = current_row.event_id
        ON CONFLICT (message_id) DO UPDATE
        SET attempt_count = EXCLUDED.attempt_count,
            failure_category = EXCLUDED.failure_category,
            last_failure_at = EXCLUDED.last_failure_at,
            last_error = EXCLUDED.last_error,
            status = 'OPEN', redriven_at = NULL;
    END IF;
    RETURN next_status;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_redrive_outbox(
    p_message_id TEXT, p_expected_version BIGINT, p_command_id TEXT,
    p_actor_type TEXT, p_actor_id TEXT, p_reason TEXT,
    p_authorization_ref TEXT, p_cause_resolved BOOLEAN, p_now TIMESTAMPTZ
) RETURNS TEXT
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE current_row public.outbox_messages%ROWTYPE;
BEGIN
    IF p_actor_type NOT IN ('control_plane', 'system_operator') THEN
        RAISE EXCEPTION 'REDRIVE_NOT_AUTHORIZED';
    END IF;
    IF NULLIF(btrim(p_reason), '') IS NULL OR
       NULLIF(btrim(p_authorization_ref), '') IS NULL THEN
        RAISE EXCEPTION 'REDRIVE_AUTHORIZATION_REQUIRED';
    END IF;
    IF NOT p_cause_resolved THEN RAISE EXCEPTION 'REDRIVE_CAUSE_UNRESOLVED'; END IF;
    SELECT * INTO current_row FROM public.outbox_messages
    WHERE message_id = p_message_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'OUTBOX_MESSAGE_NOT_FOUND'; END IF;
    IF current_row.status <> 'DEAD_LETTERED' THEN
        RAISE EXCEPTION 'OUTBOX_NOT_DEAD_LETTERED';
    END IF;
    IF current_row.status_version <> p_expected_version THEN
        RAISE EXCEPTION 'VERSION_CONFLICT';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.command_receipts
        WHERE command_id = p_command_id
          AND project_id = (SELECT project_id FROM public.event_log
                            WHERE event_id = current_row.event_id)
          AND command_type = 'outbox.redrive' AND status = 'PROCESSING'
    ) THEN RAISE EXCEPTION 'REDRIVE_COMMAND_REQUIRED'; END IF;
    UPDATE public.outbox_messages
    SET status = 'PENDING', next_attempt_at = p_now,
        attempt_count = 0,
        lease_owner = NULL, lease_expires_at = NULL, claim_token = NULL,
        dead_lettered_at = NULL, redrive_count = redrive_count + 1,
        status_version = status_version + 1
    WHERE message_id = p_message_id;
    UPDATE public.outbox_delivery_dlq
    SET status = 'REDRIVEN', redriven_at = p_now
    WHERE message_id = p_message_id;
    INSERT INTO public.outbox_redrive_records(
        redrive_id, command_id, message_id, event_id, actor_type, actor_id,
        reason, authorization_ref, previous_version
    ) VALUES ('ord-' || gen_random_uuid()::text, p_command_id, p_message_id,
              current_row.event_id, p_actor_type, p_actor_id, p_reason,
              p_authorization_ref, p_expected_version);
    INSERT INTO public.audit_records(
        audit_id, project_id, source_command_id, actor_type, actor_id,
        action, outcome, reason_code, detail
    ) SELECT 'audit-' || gen_random_uuid()::text, e.project_id, p_command_id,
             p_actor_type, p_actor_id, 'outbox.redrive', 'APPLIED',
             'OUTBOX_REDRIVEN', p_message_id
      FROM public.event_log e WHERE e.event_id = current_row.event_id;
    RETURN current_row.event_id;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_delivery_owner') THEN
        CREATE ROLE hermes_delivery_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_outbox_relay_runtime') THEN
        CREATE ROLE hermes_outbox_relay_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_consumer_runtime') THEN
        CREATE ROLE hermes_consumer_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_redrive_operator_runtime') THEN
        CREATE ROLE hermes_redrive_operator_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

ALTER FUNCTION public.hermes_assign_partition_sequence() OWNER TO hermes_delivery_owner;
ALTER FUNCTION public.hermes_claim_outbox(TEXT, TIMESTAMPTZ, INTEGER, INTEGER, INTEGER)
    OWNER TO hermes_delivery_owner;
ALTER FUNCTION public.hermes_mark_outbox_published(TEXT, TEXT, TEXT, TIMESTAMPTZ)
    OWNER TO hermes_delivery_owner;
ALTER FUNCTION public.hermes_mark_outbox_failure(
    TEXT, TEXT, TEXT, TIMESTAMPTZ, BOOLEAN, TEXT, TEXT, TIMESTAMPTZ, INTEGER
) OWNER TO hermes_delivery_owner;
ALTER FUNCTION public.hermes_redrive_outbox(
    TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, BOOLEAN, TIMESTAMPTZ
) OWNER TO hermes_delivery_owner;
ALTER FUNCTION public.hermes_increment_delivery_metric(TEXT)
    OWNER TO hermes_delivery_owner;
ALTER FUNCTION public.hermes_consumer_park_gap(
    TEXT, TEXT, TEXT, BIGINT, JSONB, INTEGER
) OWNER TO hermes_delivery_owner;
ALTER FUNCTION public.hermes_consumer_commit_next(
    TEXT, TEXT, TEXT, BIGINT, TEXT, JSONB, JSONB, TEXT
) OWNER TO hermes_delivery_owner;
ALTER FUNCTION public.hermes_consumer_quarantine(
    TEXT, TEXT, TEXT, BIGINT, JSONB, TEXT, TEXT
) OWNER TO hermes_delivery_owner;

GRANT SELECT, INSERT, UPDATE ON public.event_partition_sequences TO hermes_delivery_owner;
GRANT SELECT ON public.event_log, public.command_receipts TO hermes_delivery_owner;
GRANT SELECT, UPDATE ON public.outbox_messages TO hermes_delivery_owner;
GRANT SELECT, INSERT, UPDATE ON public.outbox_delivery_dlq TO hermes_delivery_owner;
GRANT SELECT, INSERT ON public.outbox_delivery_attempts,
    public.outbox_redrive_records, public.audit_records TO hermes_delivery_owner;
GRANT SELECT, INSERT, UPDATE ON public.consumer_inbox,
    public.consumer_effects, public.consumer_checkpoints,
    public.consumer_pending_gaps, public.consumer_quarantine,
    public.delivery_operational_alerts, public.delivery_metric_counters
TO hermes_delivery_owner;
GRANT EXECUTE ON FUNCTION public.hermes_event_envelope(TEXT) TO hermes_delivery_owner;

REVOKE ALL ON public.event_partition_sequences, public.outbox_delivery_attempts,
    public.outbox_delivery_dlq, public.outbox_redrive_records,
    public.consumer_pending_gaps, public.consumer_quarantine,
    public.local_transport_publications, public.delivery_operational_alerts,
    public.delivery_metric_counters
FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_assign_partition_sequence() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_claim_outbox(
    TEXT, TIMESTAMPTZ, INTEGER, INTEGER, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_mark_outbox_published(
    TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_mark_outbox_failure(
    TEXT, TEXT, TEXT, TIMESTAMPTZ, BOOLEAN, TEXT, TEXT, TIMESTAMPTZ, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_redrive_outbox(
    TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, BOOLEAN, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_increment_delivery_metric(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_consumer_park_gap(
    TEXT, TEXT, TEXT, BIGINT, JSONB, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_consumer_commit_next(
    TEXT, TEXT, TEXT, BIGINT, TEXT, JSONB, JSONB, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_consumer_quarantine(
    TEXT, TEXT, TEXT, BIGINT, JSONB, TEXT, TEXT
) FROM PUBLIC;

GRANT SELECT ON public.event_log, public.outbox_messages TO hermes_outbox_relay_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_claim_outbox(
    TEXT, TIMESTAMPTZ, INTEGER, INTEGER, INTEGER
) TO hermes_outbox_relay_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_mark_outbox_published(
    TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO hermes_outbox_relay_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_mark_outbox_failure(
    TEXT, TEXT, TEXT, TIMESTAMPTZ, BOOLEAN, TEXT, TEXT, TIMESTAMPTZ, INTEGER
) TO hermes_outbox_relay_runtime;

REVOKE ALL ON public.consumer_inbox, public.consumer_effects,
    public.consumer_checkpoints, public.consumer_pending_gaps,
    public.consumer_quarantine, public.delivery_operational_alerts
FROM hermes_consumer_runtime;
GRANT SELECT ON public.event_log TO hermes_consumer_runtime;
GRANT SELECT ON public.consumer_inbox,
    public.consumer_effects, public.consumer_checkpoints,
    public.consumer_pending_gaps, public.consumer_quarantine,
    public.delivery_operational_alerts TO hermes_consumer_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_increment_delivery_metric(TEXT)
    TO hermes_consumer_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_consumer_park_gap(
    TEXT, TEXT, TEXT, BIGINT, JSONB, INTEGER
) TO hermes_consumer_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_consumer_commit_next(
    TEXT, TEXT, TEXT, BIGINT, TEXT, JSONB, JSONB, TEXT
) TO hermes_consumer_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_consumer_quarantine(
    TEXT, TEXT, TEXT, BIGINT, JSONB, TEXT, TEXT
) TO hermes_consumer_runtime;

GRANT SELECT ON public.event_log, public.outbox_messages,
    public.outbox_delivery_dlq TO hermes_redrive_operator_runtime;
GRANT SELECT, INSERT, UPDATE ON public.command_receipts TO hermes_redrive_operator_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_redrive_outbox(
    TEXT, BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, BOOLEAN, TIMESTAMPTZ
) TO hermes_redrive_operator_runtime;

GRANT SELECT ON public.outbox_delivery_attempts, public.outbox_delivery_dlq,
    public.outbox_redrive_records, public.consumer_pending_gaps,
    public.consumer_quarantine, public.delivery_operational_alerts
TO hermes_read_only_runtime;

COMMENT ON TABLE public.event_partition_sequences IS
'Atomic allocator for partition-local Event protocol sequence.';
COMMENT ON TABLE public.outbox_delivery_dlq IS
'Delivery failure records; original Event Log rows remain immutable.';
