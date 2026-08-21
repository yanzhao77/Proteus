BEGIN;

-- P6 Secret Guard False-Positive Policy Repair.
-- These private helpers are intentionally executable only by the execution
-- function owner. They do not persist data or alter any authority table.
CREATE OR REPLACE FUNCTION public.hermes_execution_normalize_secret_key(p_key TEXT)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
STRICT
SECURITY INVOKER
SET search_path = pg_catalog
AS $$
    SELECT lower(regexp_replace(btrim(p_key), '[-[:space:]]+', '_', 'g'))
$$;

CREATE OR REPLACE FUNCTION public.hermes_execution_is_opaque_secret_reference(p_value TEXT)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
STRICT
SECURITY INVOKER
SET search_path = pg_catalog
AS $$
    SELECT p_value ~ '^(secret|credential|handle)-(ref|opaque|vault)-[a-z0-9][a-z0-9._:-]{5,120}$'
$$;

CREATE OR REPLACE FUNCTION public.hermes_execution_jsonb_has_secret_value(
    p_value JSONB,
    p_parent_key TEXT DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE plpgsql
IMMUTABLE
SECURITY INVOKER
SET search_path = pg_catalog
AS $$
DECLARE
    value_kind TEXT;
    child RECORD;
    child_key TEXT;
    scalar_value TEXT;
BEGIN
    value_kind := jsonb_typeof(p_value);

    IF value_kind = 'object' THEN
        FOR child IN SELECT key, value FROM jsonb_each(p_value)
        LOOP
            child_key := public.hermes_execution_normalize_secret_key(child.key);

            -- Exact normalized-key classification. Names such as token_count,
            -- secret_ref and credential_ref are intentionally not material keys.
            IF child_key IN (
                'api_key', 'api_token', 'password', 'access_token',
                'authorization', 'client_secret', 'private_key',
                'secret_value', 'credential', 'secret'
            )
            AND child.value <> 'null'::jsonb
            AND child.value <> '""'::jsonb THEN
                RETURN TRUE;
            END IF;

            -- A server-side opaque reference is not secret material. It still
            -- passes through scalar token detection below, then must match this
            -- strict grammar rather than being accepted by key-name fragment.
            IF child_key IN ('secret_ref', 'credential_ref', 'handle')
            AND (
                jsonb_typeof(child.value) <> 'string'
                OR NOT public.hermes_execution_is_opaque_secret_reference(child.value #>> '{}')
            ) THEN
                RETURN TRUE;
            END IF;

            IF public.hermes_execution_jsonb_has_secret_value(child.value, child_key) THEN
                RETURN TRUE;
            END IF;
        END LOOP;
        RETURN FALSE;
    END IF;

    IF value_kind = 'array' THEN
        FOR child IN SELECT value FROM jsonb_array_elements(p_value)
        LOOP
            IF public.hermes_execution_jsonb_has_secret_value(child.value, p_parent_key) THEN
                RETURN TRUE;
            END IF;
        END LOOP;
        RETURN FALSE;
    END IF;

    IF value_kind <> 'string' THEN
        RETURN FALSE;
    END IF;

    scalar_value := p_value #>> '{}';

    -- Boundary-aware detection is run for every string scalar. The left token
    -- boundary prevents the legitimate E4 prefix `task-<uuid5hex>` from being
    -- treated as a `sk-...` token because its `s` is preceded by `a`.
    IF scalar_value ~* '(^|[^[:alnum:]_])sk-[[:alnum:]_-]{12,}($|[^[:alnum:]_-])' THEN
        RETURN TRUE;
    END IF;

    -- These markers are evaluated for every scalar, including nested arrays and
    -- objects, so a secret cannot be hidden by a non-sensitive field name.
    IF scalar_value ~* 'password[[:space:]]*='
       OR scalar_value ~* '-----BEGIN[[:space:]][A-Z0-9[:space:]]*PRIVATE[[:space:]]KEY-----'
       OR scalar_value ~* 'private[[:space:]-]*key' THEN
        RETURN TRUE;
    END IF;

    RETURN FALSE;
END;
$$;

-- Preserve the public guard signature, its SECURITY INVOKER mode, its owner,
-- and its hardened search path. The implementation now delegates structurally.
CREATE OR REPLACE FUNCTION public.hermes_execution_has_secret_value(p_payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
SECURITY INVOKER
SET search_path = pg_catalog
AS $$
    SELECT public.hermes_execution_jsonb_has_secret_value(p_payload, NULL)
$$;

ALTER FUNCTION public.hermes_execution_normalize_secret_key(TEXT)
    OWNER TO hermes_execution_owner;
ALTER FUNCTION public.hermes_execution_is_opaque_secret_reference(TEXT)
    OWNER TO hermes_execution_owner;
ALTER FUNCTION public.hermes_execution_jsonb_has_secret_value(JSONB, TEXT)
    OWNER TO hermes_execution_owner;
ALTER FUNCTION public.hermes_execution_has_secret_value(JSONB)
    OWNER TO hermes_execution_owner;

REVOKE ALL ON FUNCTION public.hermes_execution_normalize_secret_key(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_execution_is_opaque_secret_reference(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_execution_jsonb_has_secret_value(JSONB, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_execution_has_secret_value(JSONB) FROM PUBLIC;

COMMIT;
