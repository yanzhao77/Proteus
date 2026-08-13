DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_accounting_owner') THEN
        CREATE ROLE hermes_accounting_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_accounting_runtime') THEN
        CREATE ROLE hermes_accounting_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.resource_accounts (
    account_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    scope_type TEXT NOT NULL CHECK (scope_type IN ('project', 'task', 'action')),
    scope_id TEXT NOT NULL,
    currency TEXT CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
    version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0),
    threshold_status TEXT NOT NULL DEFAULT 'NORMAL'
        CHECK (threshold_status IN ('NORMAL', 'WARN', 'GATE', 'HARD_STOP')),
    warn_basis_points INTEGER NOT NULL DEFAULT 7500,
    gate_basis_points INTEGER NOT NULL DEFAULT 9500,
    hard_stop_basis_points INTEGER NOT NULL DEFAULT 10000,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, scope_type, scope_id),
    CHECK (0 <= warn_basis_points AND warn_basis_points <= gate_basis_points
       AND gate_basis_points <= hard_stop_basis_points)
);

CREATE TABLE IF NOT EXISTS public.resource_balances (
    account_id TEXT NOT NULL REFERENCES public.resource_accounts(account_id),
    dimension TEXT NOT NULL CHECK (dimension IN (
        'llm_tokens', 'llm_cost_minor', 'agent_runs', 'retry_count',
        'execution_time_ms', 'cpu_time_ms', 'gpu_time_ms',
        'docker_runtime_ms', 'browser_runtime_ms', 'external_api_calls',
        'storage_bytes', 'human_attention_requests'
    )),
    limit_amount BIGINT NOT NULL CHECK (limit_amount >= 0),
    consumed_amount BIGINT NOT NULL DEFAULT 0 CHECK (consumed_amount >= 0),
    reserved_amount BIGINT NOT NULL DEFAULT 0 CHECK (reserved_amount >= 0),
    PRIMARY KEY (account_id, dimension)
);

CREATE TABLE IF NOT EXISTS public.resource_preparations (
    preparation_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    owner_type TEXT NOT NULL CHECK (owner_type IN ('decision', 'action', 'preparation')),
    owner_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PREPARED', 'FINALIZED', 'FAILED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalized_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.resource_reservations (
    reservation_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES public.resource_accounts(account_id),
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    owner_type TEXT NOT NULL CHECK (owner_type IN ('decision', 'action', 'preparation')),
    owner_id TEXT NOT NULL,
    preparation_id TEXT REFERENCES public.resource_preparations(preparation_id),
    currency TEXT CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RELEASED', 'CANCELLED', 'EXPIRED', 'SETTLED')),
    account_version BIGINT NOT NULL CHECK (account_version > 0),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    terminal_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.resource_reservation_amounts (
    reservation_id TEXT NOT NULL REFERENCES public.resource_reservations(reservation_id),
    dimension TEXT NOT NULL CHECK (dimension IN (
        'llm_tokens', 'llm_cost_minor', 'agent_runs', 'retry_count',
        'execution_time_ms', 'cpu_time_ms', 'gpu_time_ms',
        'docker_runtime_ms', 'browser_runtime_ms', 'external_api_calls',
        'storage_bytes', 'human_attention_requests'
    )),
    amount BIGINT NOT NULL CHECK (amount >= 0),
    PRIMARY KEY (reservation_id, dimension),
    FOREIGN KEY (reservation_id) REFERENCES public.resource_reservations(reservation_id)
);

CREATE TABLE IF NOT EXISTS public.resource_usage_records (
    usage_id TEXT PRIMARY KEY,
    sample_id TEXT NOT NULL UNIQUE,
    reservation_id TEXT NOT NULL REFERENCES public.resource_reservations(reservation_id),
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    currency TEXT CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.resource_usage_amounts (
    usage_id TEXT NOT NULL REFERENCES public.resource_usage_records(usage_id),
    dimension TEXT NOT NULL CHECK (dimension IN (
        'llm_tokens', 'llm_cost_minor', 'agent_runs', 'retry_count',
        'execution_time_ms', 'cpu_time_ms', 'gpu_time_ms',
        'docker_runtime_ms', 'browser_runtime_ms', 'external_api_calls',
        'storage_bytes', 'human_attention_requests'
    )),
    amount BIGINT NOT NULL CHECK (amount >= 0),
    PRIMARY KEY (usage_id, dimension)
);

CREATE TABLE IF NOT EXISTS public.resource_settlements (
    settlement_id TEXT PRIMARY KEY,
    reservation_id TEXT NOT NULL UNIQUE REFERENCES public.resource_reservations(reservation_id),
    account_id TEXT NOT NULL REFERENCES public.resource_accounts(account_id),
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    account_version BIGINT NOT NULL CHECK (account_version > 0),
    over_limit BOOLEAN NOT NULL,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.resource_settlement_usage (
    settlement_id TEXT NOT NULL REFERENCES public.resource_settlements(settlement_id),
    usage_id TEXT NOT NULL UNIQUE REFERENCES public.resource_usage_records(usage_id),
    PRIMARY KEY (settlement_id, usage_id)
);

CREATE TABLE IF NOT EXISTS public.resource_reconcile_records (
    reconcile_id TEXT PRIMARY KEY,
    reservation_id TEXT NOT NULL REFERENCES public.resource_reservations(reservation_id),
    action TEXT NOT NULL CHECK (action IN ('RELEASE_ORPHAN', 'SETTLE_USAGE', 'NO_ACTION')),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (reservation_id, action)
);

ALTER TABLE public.project_budget_facts
    ADD COLUMN IF NOT EXISTS resource_account_id TEXT REFERENCES public.resource_accounts(account_id),
    ADD COLUMN IF NOT EXISTS resource_account_version BIGINT CHECK (resource_account_version >= 0),
    ADD COLUMN IF NOT EXISTS hard_stop BOOLEAN NOT NULL DEFAULT false;

CREATE OR REPLACE FUNCTION public.hermes_reject_accounting_immutable_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'resource_reservation_amounts', 'resource_usage_records',
        'resource_usage_amounts', 'resource_settlements',
        'resource_settlement_usage', 'resource_reconcile_records'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS accounting_immutable ON public.%I', table_name);
        EXECUTE format(
            'CREATE TRIGGER accounting_immutable BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_accounting_immutable_change()',
            table_name
        );
    END LOOP;
END;
$$;

ALTER TABLE public.resource_accounts OWNER TO hermes_accounting_owner;
ALTER TABLE public.resource_balances OWNER TO hermes_accounting_owner;
ALTER TABLE public.resource_preparations OWNER TO hermes_accounting_owner;
ALTER TABLE public.resource_reservations OWNER TO hermes_accounting_owner;
ALTER TABLE public.resource_reservation_amounts OWNER TO hermes_accounting_owner;
ALTER TABLE public.resource_usage_records OWNER TO hermes_accounting_owner;
ALTER TABLE public.resource_usage_amounts OWNER TO hermes_accounting_owner;
ALTER TABLE public.resource_settlements OWNER TO hermes_accounting_owner;
ALTER TABLE public.resource_settlement_usage OWNER TO hermes_accounting_owner;
ALTER TABLE public.resource_reconcile_records OWNER TO hermes_accounting_owner;
ALTER FUNCTION public.hermes_reject_accounting_immutable_change() OWNER TO hermes_accounting_owner;

REVOKE ALL ON public.resource_accounts, public.resource_balances,
    public.resource_preparations, public.resource_reservations,
    public.resource_reservation_amounts, public.resource_usage_records,
    public.resource_usage_amounts, public.resource_settlements,
    public.resource_settlement_usage, public.resource_reconcile_records FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_reject_accounting_immutable_change() FROM PUBLIC;

GRANT SELECT ON public.resource_accounts, public.resource_balances,
    public.resource_preparations, public.resource_reservations,
    public.resource_reservation_amounts, public.resource_usage_records,
    public.resource_usage_amounts, public.resource_settlements,
    public.resource_settlement_usage, public.resource_reconcile_records
TO hermes_accounting_runtime, hermes_control_plane_runtime, hermes_read_only_runtime;
GRANT SELECT ON public.resource_accounts, public.resource_reservations
TO hermes_worker_runtime;

REVOKE INSERT, UPDATE, DELETE ON public.resource_accounts, public.resource_balances,
    public.resource_preparations, public.resource_reservations,
    public.resource_reservation_amounts, public.resource_usage_records,
    public.resource_usage_amounts, public.resource_settlements,
    public.resource_settlement_usage, public.resource_reconcile_records
FROM hermes_worker_runtime, hermes_control_plane_runtime,
     hermes_read_only_runtime, hermes_accounting_runtime;

REVOKE INSERT, UPDATE, DELETE ON public.project_budget_facts
FROM hermes_worker_runtime, hermes_control_plane_runtime,
     hermes_read_only_runtime, hermes_accounting_runtime;

REVOKE CREATE ON SCHEMA public FROM hermes_accounting_runtime;

CREATE OR REPLACE FUNCTION public.hermes_accounting_status(
    p_account_id TEXT, p_force_hard_stop BOOLEAN DEFAULT false
) RETURNS TEXT
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    warn_bp INTEGER;
    gate_bp INTEGER;
    hard_bp INTEGER;
    highest_ratio BIGINT;
    result TEXT;
BEGIN
    SELECT warn_basis_points, gate_basis_points, hard_stop_basis_points
    INTO warn_bp, gate_bp, hard_bp
    FROM public.resource_accounts WHERE account_id=p_account_id;
    SELECT COALESCE(max(CASE
        WHEN limit_amount=0 AND consumed_amount+reserved_amount=0 THEN 0
        WHEN limit_amount=0 THEN hard_bp
        ELSE (consumed_amount+reserved_amount)*10000/limit_amount
    END), 0) INTO highest_ratio
    FROM public.resource_balances WHERE account_id=p_account_id;
    result := CASE
        WHEN p_force_hard_stop OR highest_ratio >= hard_bp THEN 'HARD_STOP'
        WHEN highest_ratio >= gate_bp THEN 'GATE'
        WHEN highest_ratio >= warn_bp THEN 'WARN'
        ELSE 'NORMAL'
    END;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_create_resource_account_authority(
    p_account_id TEXT, p_project_id TEXT, p_scope_type TEXT, p_scope_id TEXT,
    p_currency TEXT, p_limits JSONB, p_warn_bp INTEGER, p_gate_bp INTEGER,
    p_hard_bp INTEGER, p_command_id TEXT, p_actor_type TEXT
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE item RECORD;
BEGIN
    IF p_actor_type <> 'control_plane' THEN RAISE EXCEPTION 'ACCOUNTING_AUTHORITY_REQUIRED'; END IF;
    IF p_scope_type NOT IN ('project','task','action') OR p_warn_bp < 0
       OR p_warn_bp > p_gate_bp OR p_gate_bp > p_hard_bp THEN
        RAISE EXCEPTION 'RESOURCE_SCOPE_OR_THRESHOLD_INVALID';
    END IF;
    IF p_currency IS NOT NULL AND p_currency !~ '^[A-Z]{3}$' THEN
        RAISE EXCEPTION 'RESOURCE_CURRENCY_MISMATCH';
    END IF;
    PERFORM 1 FROM public.command_receipts WHERE command_id=p_command_id
      AND project_id=p_project_id AND command_type='resource_account.create'
      AND status='PROCESSING';
    IF NOT FOUND THEN RAISE EXCEPTION 'ACCOUNTING_COMMAND_SEMANTICS_MISMATCH'; END IF;
    IF jsonb_typeof(p_limits) <> 'object' OR p_limits = '{}'::jsonb THEN
        RAISE EXCEPTION 'RESOURCE_AMOUNT_INVALID';
    END IF;
    INSERT INTO public.resource_accounts(
        account_id,project_id,scope_type,scope_id,currency,warn_basis_points,
        gate_basis_points,hard_stop_basis_points)
    VALUES (p_account_id,p_project_id,p_scope_type,p_scope_id,p_currency,p_warn_bp,
            p_gate_bp,p_hard_bp);
    FOR item IN SELECT key,value FROM jsonb_each(p_limits) LOOP
        IF item.key NOT IN (
            'llm_tokens','llm_cost_minor','agent_runs','retry_count',
            'execution_time_ms','cpu_time_ms','gpu_time_ms','docker_runtime_ms',
            'browser_runtime_ms','external_api_calls','storage_bytes',
            'human_attention_requests'
        ) THEN RAISE EXCEPTION 'RESOURCE_DIMENSION_UNKNOWN'; END IF;
        IF jsonb_typeof(item.value) <> 'number' OR item.value::text !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'RESOURCE_AMOUNT_INVALID';
        END IF;
        IF item.key='llm_cost_minor' AND p_currency IS NULL THEN
            RAISE EXCEPTION 'RESOURCE_CURRENCY_MISMATCH';
        END IF;
        INSERT INTO public.resource_balances(account_id,dimension,limit_amount)
        VALUES (p_account_id,item.key,(item.value::text)::BIGINT);
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_reserve_resources_authority(
    p_account_id TEXT, p_project_id TEXT, p_expected_version BIGINT,
    p_reservation_id TEXT, p_owner_type TEXT, p_owner_id TEXT,
    p_preparation_id TEXT, p_currency TEXT, p_amounts JSONB,
    p_command_id TEXT, p_actor_type TEXT
) RETURNS TABLE(account_version BIGINT, threshold_status TEXT)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE account_row RECORD; item RECORD; balance_row RECORD;
BEGIN
    IF p_actor_type <> 'control_plane' THEN RAISE EXCEPTION 'ACCOUNTING_AUTHORITY_REQUIRED'; END IF;
    IF p_owner_type NOT IN ('decision','action','preparation') OR NULLIF(btrim(p_owner_id),'') IS NULL THEN
        RAISE EXCEPTION 'RESOURCE_RESERVATION_OWNER_MISMATCH';
    END IF;
    PERFORM 1 FROM public.command_receipts WHERE command_id=p_command_id
      AND project_id=p_project_id AND command_type='resource.reserve' AND status='PROCESSING';
    IF NOT FOUND THEN RAISE EXCEPTION 'ACCOUNTING_COMMAND_SEMANTICS_MISMATCH'; END IF;
    SELECT * INTO account_row FROM public.resource_accounts
    WHERE account_id=p_account_id AND project_id=p_project_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'RESOURCE_ACCOUNT_NOT_FOUND'; END IF;
    IF account_row.version <> p_expected_version THEN RAISE EXCEPTION 'RESOURCE_ACCOUNT_VERSION_CONFLICT'; END IF;
    IF account_row.threshold_status='HARD_STOP' THEN RAISE EXCEPTION 'RESOURCE_HARD_STOP'; END IF;
    IF p_currency IS DISTINCT FROM account_row.currency THEN RAISE EXCEPTION 'RESOURCE_CURRENCY_MISMATCH'; END IF;
    IF jsonb_typeof(p_amounts) <> 'object' OR p_amounts='{}'::jsonb THEN RAISE EXCEPTION 'RESOURCE_AMOUNT_INVALID'; END IF;
    FOR item IN SELECT key,value FROM jsonb_each(p_amounts) LOOP
        IF item.key NOT IN (
            'llm_tokens','llm_cost_minor','agent_runs','retry_count','execution_time_ms',
            'cpu_time_ms','gpu_time_ms','docker_runtime_ms','browser_runtime_ms',
            'external_api_calls','storage_bytes','human_attention_requests'
        ) THEN RAISE EXCEPTION 'RESOURCE_DIMENSION_UNKNOWN'; END IF;
        IF jsonb_typeof(item.value) <> 'number' OR item.value::text !~ '^[0-9]+$' THEN RAISE EXCEPTION 'RESOURCE_AMOUNT_INVALID'; END IF;
        SELECT * INTO balance_row FROM public.resource_balances
        WHERE account_id=p_account_id AND dimension=item.key FOR UPDATE;
        IF NOT FOUND OR (item.value::text)::BIGINT >
           balance_row.limit_amount-balance_row.consumed_amount-balance_row.reserved_amount THEN
            RAISE EXCEPTION 'RESOURCE_RESERVATION_INFEASIBLE';
        END IF;
    END LOOP;
    IF p_preparation_id IS NOT NULL THEN
        INSERT INTO public.resource_preparations(preparation_id,project_id,owner_type,owner_id,status)
        VALUES (p_preparation_id,p_project_id,p_owner_type,p_owner_id,'PREPARED');
    END IF;
    account_version := account_row.version+1;
    INSERT INTO public.resource_reservations(
        reservation_id,account_id,project_id,owner_type,owner_id,preparation_id,
        currency,status,account_version,command_id)
    VALUES (p_reservation_id,p_account_id,p_project_id,p_owner_type,p_owner_id,
            p_preparation_id,p_currency,'ACTIVE',account_version,p_command_id);
    FOR item IN SELECT key,value FROM jsonb_each(p_amounts) LOOP
        INSERT INTO public.resource_reservation_amounts(reservation_id,dimension,amount)
        VALUES (p_reservation_id,item.key,(item.value::text)::BIGINT);
        UPDATE public.resource_balances
        SET reserved_amount=reserved_amount+(item.value::text)::BIGINT
        WHERE account_id=p_account_id AND dimension=item.key;
    END LOOP;
    threshold_status := public.hermes_accounting_status(p_account_id,false);
    UPDATE public.resource_accounts SET version=account_version,
        threshold_status=hermes_reserve_resources_authority.threshold_status,updated_at=now()
    WHERE account_id=p_account_id;
    UPDATE public.project_budget_facts SET valid=false,invalidated_at=now()
    WHERE resource_account_id=p_account_id AND valid;
    IF p_preparation_id IS NOT NULL THEN
        UPDATE public.resource_preparations SET status='FINALIZED',finalized_at=now()
        WHERE preparation_id=p_preparation_id;
    END IF;
    RETURN NEXT;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_release_reservation_authority(
    p_reservation_id TEXT, p_project_id TEXT, p_expected_version BIGINT,
    p_terminal_status TEXT, p_command_id TEXT, p_actor_type TEXT
) RETURNS TABLE(account_version BIGINT, threshold_status TEXT, account_id TEXT, amounts JSONB)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE reservation_row RECORD; account_row RECORD; item RECORD; stored_command_type TEXT;
BEGIN
    IF p_terminal_status NOT IN ('RELEASED','CANCELLED','EXPIRED') THEN RAISE EXCEPTION 'RESOURCE_RESERVATION_NOT_ACTIVE'; END IF;
    SELECT command_type INTO stored_command_type FROM public.command_receipts
    WHERE command_id=p_command_id AND project_id=p_project_id
      AND command_type IN ('resource.release','resource.reconcile') AND status='PROCESSING';
    IF stored_command_type IS NULL THEN RAISE EXCEPTION 'ACCOUNTING_COMMAND_SEMANTICS_MISMATCH'; END IF;
    IF p_actor_type <> 'control_plane' AND NOT (
        p_actor_type='recovery_controller' AND stored_command_type='resource.reconcile'
    ) THEN RAISE EXCEPTION 'ACCOUNTING_AUTHORITY_REQUIRED'; END IF;
    SELECT * INTO reservation_row FROM public.resource_reservations
    WHERE reservation_id=p_reservation_id AND project_id=p_project_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'RESOURCE_RESERVATION_NOT_ACTIVE'; END IF;
    IF reservation_row.status <> 'ACTIVE' THEN RAISE EXCEPTION 'RESOURCE_RELEASE_ALREADY_APPLIED'; END IF;
    SELECT * INTO account_row FROM public.resource_accounts
    WHERE resource_accounts.account_id=reservation_row.account_id FOR UPDATE;
    IF account_row.version <> p_expected_version THEN RAISE EXCEPTION 'RESOURCE_ACCOUNT_VERSION_CONFLICT'; END IF;
    amounts := '{}'::jsonb;
    FOR item IN SELECT dimension,amount FROM public.resource_reservation_amounts
                WHERE reservation_id=p_reservation_id LOOP
        UPDATE public.resource_balances SET reserved_amount=reserved_amount-item.amount
        WHERE resource_balances.account_id=reservation_row.account_id
          AND dimension=item.dimension AND reserved_amount>=item.amount;
        IF NOT FOUND THEN RAISE EXCEPTION 'RESOURCE_SETTLEMENT_USAGE_CONFLICT'; END IF;
        amounts := amounts || jsonb_build_object(item.dimension,item.amount);
    END LOOP;
    UPDATE public.resource_reservations SET status=p_terminal_status,terminal_at=now()
    WHERE reservation_id=p_reservation_id;
    account_version := account_row.version+1; account_id := reservation_row.account_id;
    threshold_status := public.hermes_accounting_status(account_id,false);
    UPDATE public.resource_accounts SET version=account_version,
      threshold_status=hermes_release_reservation_authority.threshold_status,updated_at=now()
    WHERE resource_accounts.account_id=hermes_release_reservation_authority.account_id;
    UPDATE public.project_budget_facts SET valid=false,invalidated_at=now()
    WHERE resource_account_id=account_id AND valid;
    RETURN NEXT;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_record_resource_usage_authority(
    p_usage_id TEXT, p_sample_id TEXT, p_reservation_id TEXT, p_project_id TEXT,
    p_owner_type TEXT, p_owner_id TEXT, p_currency TEXT, p_amounts JSONB,
    p_command_id TEXT, p_actor_type TEXT
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE reservation_row RECORD; item RECORD;
BEGIN
    IF p_actor_type <> 'control_plane' THEN RAISE EXCEPTION 'ACCOUNTING_AUTHORITY_REQUIRED'; END IF;
    PERFORM 1 FROM public.command_receipts WHERE command_id=p_command_id AND project_id=p_project_id
      AND command_type='resource.usage.record' AND status='PROCESSING';
    IF NOT FOUND THEN RAISE EXCEPTION 'ACCOUNTING_COMMAND_SEMANTICS_MISMATCH'; END IF;
    SELECT * INTO reservation_row FROM public.resource_reservations
    WHERE reservation_id=p_reservation_id AND project_id=p_project_id FOR UPDATE;
    IF NOT FOUND OR reservation_row.owner_type<>p_owner_type OR reservation_row.owner_id<>p_owner_id THEN
        RAISE EXCEPTION 'RESOURCE_RESERVATION_OWNER_MISMATCH';
    END IF;
    IF reservation_row.status<>'ACTIVE' THEN
        RAISE EXCEPTION 'RESOURCE_RESERVATION_NOT_ACTIVE';
    END IF;
    IF p_currency IS DISTINCT FROM reservation_row.currency THEN RAISE EXCEPTION 'RESOURCE_CURRENCY_MISMATCH'; END IF;
    IF EXISTS(SELECT 1 FROM public.resource_usage_records WHERE sample_id=p_sample_id) THEN
        RAISE EXCEPTION 'RESOURCE_USAGE_DUPLICATE_CONFLICT';
    END IF;
    INSERT INTO public.resource_usage_records(
        usage_id,sample_id,reservation_id,project_id,owner_type,owner_id,currency,command_id)
    VALUES (p_usage_id,p_sample_id,p_reservation_id,p_project_id,p_owner_type,p_owner_id,p_currency,p_command_id);
    FOR item IN SELECT key,value FROM jsonb_each(p_amounts) LOOP
        IF item.key NOT IN (
            'llm_tokens','llm_cost_minor','agent_runs','retry_count','execution_time_ms',
            'cpu_time_ms','gpu_time_ms','docker_runtime_ms','browser_runtime_ms',
            'external_api_calls','storage_bytes','human_attention_requests'
        ) THEN RAISE EXCEPTION 'RESOURCE_DIMENSION_UNKNOWN'; END IF;
        IF jsonb_typeof(item.value)<>'number' OR item.value::text !~ '^[0-9]+$' THEN RAISE EXCEPTION 'RESOURCE_AMOUNT_INVALID'; END IF;
        INSERT INTO public.resource_usage_amounts(usage_id,dimension,amount)
        VALUES (p_usage_id,item.key,(item.value::text)::BIGINT);
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_settle_reservation_authority(
    p_settlement_id TEXT, p_reservation_id TEXT, p_project_id TEXT,
    p_expected_version BIGINT, p_command_id TEXT, p_actor_type TEXT
) RETURNS TABLE(account_version BIGINT, threshold_status TEXT, account_id TEXT,
                actual JSONB, released JSONB, over_limit BOOLEAN)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE reservation_row RECORD; account_row RECORD; item RECORD; balance_row RECORD;
        stored_command_type TEXT;
BEGIN
    SELECT command_type INTO stored_command_type FROM public.command_receipts
    WHERE command_id=p_command_id AND project_id=p_project_id
      AND command_type IN ('resource.settle','resource.reconcile') AND status='PROCESSING';
    IF stored_command_type IS NULL THEN RAISE EXCEPTION 'ACCOUNTING_COMMAND_SEMANTICS_MISMATCH'; END IF;
    IF p_actor_type <> 'control_plane' AND NOT (
        p_actor_type='recovery_controller' AND stored_command_type='resource.reconcile'
    ) THEN RAISE EXCEPTION 'ACCOUNTING_AUTHORITY_REQUIRED'; END IF;
    SELECT * INTO reservation_row FROM public.resource_reservations
    WHERE reservation_id=p_reservation_id AND project_id=p_project_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'RESOURCE_RESERVATION_NOT_ACTIVE'; END IF;
    IF reservation_row.status<>'ACTIVE' THEN RAISE EXCEPTION 'RESOURCE_SETTLEMENT_ALREADY_APPLIED'; END IF;
    SELECT * INTO account_row FROM public.resource_accounts
    WHERE resource_accounts.account_id=reservation_row.account_id FOR UPDATE;
    IF account_row.version<>p_expected_version THEN RAISE EXCEPTION 'RESOURCE_ACCOUNT_VERSION_CONFLICT'; END IF;
    IF NOT EXISTS(SELECT 1 FROM public.resource_usage_records WHERE reservation_id=p_reservation_id) THEN
        RAISE EXCEPTION 'RESOURCE_RECONCILE_NOT_REQUIRED';
    END IF;
    IF EXISTS(SELECT 1 FROM public.resource_usage_records u JOIN public.resource_settlement_usage s USING(usage_id)
              WHERE u.reservation_id=p_reservation_id) THEN RAISE EXCEPTION 'RESOURCE_SETTLEMENT_USAGE_CONFLICT'; END IF;
    actual := '{}'::jsonb; released := '{}'::jsonb; over_limit := false;
    FOR item IN
        SELECT d.dimension,COALESCE(u.amount,0)::BIGINT AS consumed,COALESCE(r.amount,0)::BIGINT AS reserved
        FROM (SELECT dimension FROM public.resource_reservation_amounts WHERE reservation_id=p_reservation_id
              UNION SELECT ua.dimension FROM public.resource_usage_records ur
                    JOIN public.resource_usage_amounts ua USING(usage_id)
                    WHERE ur.reservation_id=p_reservation_id) d
        LEFT JOIN (SELECT dimension,sum(amount) amount FROM public.resource_usage_records ur
                   JOIN public.resource_usage_amounts ua USING(usage_id)
                   WHERE ur.reservation_id=p_reservation_id GROUP BY dimension) u USING(dimension)
        LEFT JOIN (SELECT dimension,amount FROM public.resource_reservation_amounts
                   WHERE reservation_id=p_reservation_id) r USING(dimension)
    LOOP
        UPDATE public.resource_balances SET consumed_amount=consumed_amount+item.consumed,
          reserved_amount=reserved_amount-item.reserved
        WHERE resource_balances.account_id=reservation_row.account_id AND dimension=item.dimension
          AND reserved_amount>=item.reserved RETURNING * INTO balance_row;
        IF NOT FOUND THEN RAISE EXCEPTION 'RESOURCE_SETTLEMENT_USAGE_CONFLICT'; END IF;
        actual := actual || jsonb_build_object(item.dimension,item.consumed);
        released := released || jsonb_build_object(item.dimension,item.reserved);
        over_limit := over_limit OR item.consumed>item.reserved
          OR balance_row.consumed_amount+balance_row.reserved_amount>balance_row.limit_amount;
    END LOOP;
    account_version := account_row.version+1; account_id := reservation_row.account_id;
    INSERT INTO public.resource_settlements(settlement_id,reservation_id,account_id,project_id,
        account_version,over_limit,command_id)
    VALUES (p_settlement_id,p_reservation_id,account_id,p_project_id,account_version,over_limit,p_command_id);
    INSERT INTO public.resource_settlement_usage(settlement_id,usage_id)
    SELECT p_settlement_id,usage_id FROM public.resource_usage_records WHERE reservation_id=p_reservation_id;
    UPDATE public.resource_reservations SET status='SETTLED',terminal_at=now()
    WHERE reservation_id=p_reservation_id;
    threshold_status := public.hermes_accounting_status(account_id,over_limit);
    UPDATE public.resource_accounts SET version=account_version,
      threshold_status=hermes_settle_reservation_authority.threshold_status,updated_at=now()
    WHERE resource_accounts.account_id=hermes_settle_reservation_authority.account_id;
    UPDATE public.project_budget_facts SET valid=false,invalidated_at=now()
    WHERE resource_account_id=account_id AND valid;
    RETURN NEXT;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_issue_budget_fact_authority(
    p_budget_fact_id TEXT,p_account_id TEXT,p_project_id TEXT,p_account_version BIGINT,
    p_project_version BIGINT,p_from_state TEXT,p_to_state TEXT,p_command_id TEXT,p_actor_type TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE account_row RECORD; project_row RECORD; is_hard_stop BOOLEAN;
BEGIN
    IF p_actor_type<>'control_plane' THEN RAISE EXCEPTION 'ACCOUNTING_AUTHORITY_REQUIRED'; END IF;
    PERFORM 1 FROM public.command_receipts WHERE command_id=p_command_id AND project_id=p_project_id
      AND command_type='resource.budget_fact.issue' AND status='PROCESSING';
    IF NOT FOUND THEN RAISE EXCEPTION 'ACCOUNTING_COMMAND_SEMANTICS_MISMATCH'; END IF;
    SELECT * INTO account_row FROM public.resource_accounts WHERE account_id=p_account_id
      AND project_id=p_project_id FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'RESOURCE_ACCOUNT_NOT_FOUND'; END IF;
    IF account_row.version<>p_account_version THEN RAISE EXCEPTION 'RESOURCE_ACCOUNT_VERSION_CONFLICT'; END IF;
    SELECT * INTO project_row FROM public.projects WHERE project_id=p_project_id;
    IF project_row.version<>p_project_version OR project_row.state<>p_from_state THEN
        RAISE EXCEPTION 'PROJECT_AUTHORITY_PRECONDITION_FAILED';
    END IF;
    is_hard_stop := account_row.threshold_status='HARD_STOP';
    UPDATE public.project_budget_facts SET valid=false,invalidated_at=now()
    WHERE project_id=p_project_id AND project_version=p_project_version
      AND from_state=p_from_state AND to_state=p_to_state AND valid;
    INSERT INTO public.project_budget_facts(budget_fact_id,project_id,project_version,
      from_state,to_state,status,authority,budget_scope_id,version,resource_account_id,
      resource_account_version,hard_stop)
    VALUES (p_budget_fact_id,p_project_id,p_project_version,p_from_state,p_to_state,
      CASE WHEN is_hard_stop THEN 'HARD_STOP' ELSE 'OK' END,'budget_engine',p_account_id,
      p_account_version,p_account_id,p_account_version,is_hard_stop);
    RETURN is_hard_stop;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_record_resource_reconcile_authority(
    p_reconcile_id TEXT,p_reservation_id TEXT,p_action TEXT,
    p_project_id TEXT,p_command_id TEXT,p_actor_type TEXT
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF p_actor_type NOT IN ('control_plane','recovery_controller') THEN
        RAISE EXCEPTION 'ACCOUNTING_AUTHORITY_REQUIRED';
    END IF;
    IF p_action NOT IN ('RELEASE_ORPHAN','SETTLE_USAGE','NO_ACTION') THEN
        RAISE EXCEPTION 'RESOURCE_RECONCILE_NOT_REQUIRED';
    END IF;
    PERFORM 1 FROM public.command_receipts WHERE command_id=p_command_id
      AND project_id=p_project_id AND command_type='resource.reconcile'
      AND status='PROCESSING';
    IF NOT FOUND THEN RAISE EXCEPTION 'ACCOUNTING_COMMAND_SEMANTICS_MISMATCH'; END IF;
    INSERT INTO public.resource_reconcile_records(
        reconcile_id,reservation_id,action,command_id)
    VALUES (p_reconcile_id,p_reservation_id,p_action,p_command_id);
END;
$$;

ALTER FUNCTION public.hermes_accounting_status(TEXT,BOOLEAN) OWNER TO hermes_accounting_owner;
ALTER FUNCTION public.hermes_create_resource_account_authority(TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,INTEGER,INTEGER,INTEGER,TEXT,TEXT) OWNER TO hermes_accounting_owner;
ALTER FUNCTION public.hermes_reserve_resources_authority(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT,TEXT) OWNER TO hermes_accounting_owner;
ALTER FUNCTION public.hermes_release_reservation_authority(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT) OWNER TO hermes_accounting_owner;
ALTER FUNCTION public.hermes_record_resource_usage_authority(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT,TEXT) OWNER TO hermes_accounting_owner;
ALTER FUNCTION public.hermes_settle_reservation_authority(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT) OWNER TO hermes_accounting_owner;
ALTER FUNCTION public.hermes_issue_budget_fact_authority(TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_accounting_owner;
ALTER FUNCTION public.hermes_record_resource_reconcile_authority(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) OWNER TO hermes_accounting_owner;

GRANT SELECT ON public.projects,public.command_receipts TO hermes_accounting_owner;
GRANT SELECT,INSERT,UPDATE ON public.project_budget_facts TO hermes_accounting_owner;
REVOKE ALL ON FUNCTION public.hermes_accounting_status(TEXT,BOOLEAN) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_create_resource_account_authority(TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,INTEGER,INTEGER,INTEGER,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_reserve_resources_authority(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_release_reservation_authority(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_record_resource_usage_authority(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_settle_reservation_authority(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_issue_budget_fact_authority(TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_record_resource_reconcile_authority(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.hermes_create_resource_account_authority(TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,INTEGER,INTEGER,INTEGER,TEXT,TEXT) TO hermes_accounting_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_reserve_resources_authority(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT,TEXT) TO hermes_accounting_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_release_reservation_authority(TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT) TO hermes_accounting_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_record_resource_usage_authority(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT,TEXT) TO hermes_accounting_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_settle_reservation_authority(TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT) TO hermes_accounting_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_issue_budget_fact_authority(TEXT,TEXT,TEXT,BIGINT,BIGINT,TEXT,TEXT,TEXT,TEXT) TO hermes_accounting_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_record_resource_reconcile_authority(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT) TO hermes_accounting_runtime;
GRANT SELECT,INSERT,UPDATE ON public.command_receipts TO hermes_accounting_runtime;
GRANT SELECT,INSERT ON public.event_log,public.outbox_messages,public.audit_records TO hermes_accounting_runtime;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_accounting_runtime;
