-- P2-1: Capability Registry, immutable Context Bundle and SandboxProfile Compiler authority.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_capability_owner') THEN
        CREATE ROLE hermes_capability_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hermes_capability_runtime') THEN
        CREATE ROLE hermes_capability_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.capability_schemas (
    capability_name TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    description TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (content_hash LIKE 'sha256:%'),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (capability_name, schema_version)
);

CREATE TABLE IF NOT EXISTS public.worker_template_revisions (
    template_id TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK (revision >= 1),
    project_id TEXT REFERENCES public.projects(project_id),
    runtime_kind TEXT NOT NULL,
    capabilities TEXT[] NOT NULL,
    trust_level TEXT NOT NULL CHECK (trust_level IN ('UNTRUSTED','STANDARD','ELEVATED','PRIVILEGED')),
    allowed_tools TEXT[] NOT NULL DEFAULT '{}',
    supported_sandbox_features TEXT[] NOT NULL DEFAULT '{}',
    resource_envelope JSONB NOT NULL DEFAULT '{}'::jsonb,
    constraint_ranges JSONB NOT NULL DEFAULT '{}'::jsonb,
    concurrency_capacity INTEGER NOT NULL CHECK (concurrency_capacity >= 0),
    schema_version TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (content_hash LIKE 'sha256:%'),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (template_id, revision),
    UNIQUE (template_id, revision, content_hash)
);

CREATE TABLE IF NOT EXISTS public.worker_template_capabilities (
    template_id TEXT NOT NULL,
    revision BIGINT NOT NULL,
    capability_name TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    PRIMARY KEY (template_id, revision, capability_name),
    FOREIGN KEY (template_id, revision)
        REFERENCES public.worker_template_revisions(template_id, revision),
    FOREIGN KEY (capability_name, schema_version)
        REFERENCES public.capability_schemas(capability_name, schema_version)
);

CREATE TABLE IF NOT EXISTS public.worker_template_availability (
    template_id TEXT NOT NULL,
    revision BIGINT NOT NULL,
    availability_status TEXT NOT NULL CHECK (availability_status IN ('AVAILABLE','DRAINING','DISABLED')),
    admission_status TEXT NOT NULL CHECK (admission_status IN ('ADMISSIBLE','NOT_ADMISSIBLE')),
    availability_version BIGINT NOT NULL CHECK (availability_version >= 1),
    reason TEXT NOT NULL,
    command_id TEXT NOT NULL REFERENCES public.command_receipts(command_id),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (template_id, revision),
    FOREIGN KEY (template_id, revision)
        REFERENCES public.worker_template_revisions(template_id, revision)
);

CREATE TABLE IF NOT EXISTS public.capability_match_records (
    match_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    decision_id TEXT NOT NULL REFERENCES public.decision_records(decision_id),
    action_id TEXT NOT NULL REFERENCES public.candidate_actions(action_id),
    status TEXT NOT NULL CHECK (status IN ('MATCHED','NOT_ADMISSIBLE')),
    reason_code TEXT NOT NULL,
    requirements_hash TEXT NOT NULL CHECK (requirements_hash LIKE 'sha256:%'),
    matcher_version TEXT NOT NULL,
    template_id TEXT,
    template_revision BIGINT,
    availability_version BIGINT,
    template_content_hash TEXT CHECK (template_content_hash IS NULL OR template_content_hash LIKE 'sha256:%'),
    requirement JSONB NOT NULL,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (status = 'MATCHED' AND template_id IS NOT NULL AND template_revision IS NOT NULL
         AND availability_version IS NOT NULL AND template_content_hash IS NOT NULL)
        OR
        (status = 'NOT_ADMISSIBLE' AND template_id IS NULL AND template_revision IS NULL)
    ),
    FOREIGN KEY (template_id, template_revision, template_content_hash)
        REFERENCES public.worker_template_revisions(template_id, revision, content_hash),
    UNIQUE (project_id, requirements_hash, matcher_version)
);

CREATE TABLE IF NOT EXISTS public.context_bundles (
    bundle_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    decision_id TEXT NOT NULL REFERENCES public.decision_records(decision_id),
    action_id TEXT NOT NULL REFERENCES public.candidate_actions(action_id),
    template_id TEXT NOT NULL,
    template_revision BIGINT NOT NULL,
    selector_schema_version TEXT NOT NULL,
    builder_version TEXT NOT NULL,
    manifest JSONB NOT NULL,
    manifest_hash TEXT NOT NULL UNIQUE CHECK (manifest_hash LIKE 'sha256:%'),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (template_id, template_revision)
        REFERENCES public.worker_template_revisions(template_id, revision)
);

CREATE TABLE IF NOT EXISTS public.context_bundle_items (
    bundle_id TEXT NOT NULL REFERENCES public.context_bundles(bundle_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    ref_type TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    task_id TEXT,
    ref_version BIGINT,
    content_hash TEXT NOT NULL CHECK (content_hash LIKE 'sha256:%'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (bundle_id, ordinal)
);

CREATE TABLE IF NOT EXISTS public.sandbox_profiles (
    profile_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES public.projects(project_id),
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    action_id TEXT NOT NULL REFERENCES public.candidate_actions(action_id),
    template_id TEXT NOT NULL,
    template_revision BIGINT NOT NULL,
    context_bundle_hash TEXT NOT NULL REFERENCES public.context_bundles(manifest_hash),
    compiler_version TEXT NOT NULL,
    target TEXT NOT NULL,
    profile JSONB NOT NULL,
    profile_hash TEXT NOT NULL UNIQUE CHECK (profile_hash LIKE 'sha256:%'),
    constraints_hash TEXT NOT NULL CHECK (constraints_hash LIKE 'sha256:%'),
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (template_id, template_revision)
        REFERENCES public.worker_template_revisions(template_id, revision)
);

CREATE OR REPLACE FUNCTION public.hermes_reject_capability_history_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'capability_schemas','worker_template_revisions',
        'worker_template_capabilities','capability_match_records',
        'context_bundles','context_bundle_items','sandbox_profiles'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS capability_immutable ON public.%I', table_name);
        EXECUTE format(
            'CREATE TRIGGER capability_immutable BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_capability_history_change()',
            table_name
        );
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_capability_has_secret_value(p_payload JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
    SELECT p_payload::text ~* '("(api[_-]?token|password|credential|private[_-]?key)"[[:space:]]*:|private key|sk-[A-Za-z0-9]{12,}|password=)'
$$;

CREATE OR REPLACE FUNCTION public.hermes_apply_execution_preparation_fact_internal(
    p_fact_type TEXT,
    p_payload JSONB,
    p_project_id TEXT,
    p_expected_version BIGINT,
    p_command_id TEXT,
    p_idempotency_key TEXT,
    p_request_hash TEXT,
    p_command_type TEXT,
    p_actor_type TEXT,
    p_actor_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    command_row public.command_receipts%ROWTYPE;
    event_id TEXT;
    event_sequence BIGINT;
    event_type TEXT;
    event_payload JSONB;
    target_version BIGINT := 1;
    template JSONB;
    bundle JSONB;
    profile JSONB;
    match JSONB;
    capability TEXT;
    availability_row public.worker_template_availability%ROWTYPE;
    current_template public.worker_template_revisions%ROWTYPE;
    decision_row public.decision_records%ROWTYPE;
    action_row public.candidate_actions%ROWTYPE;
    task_row public.tasks%ROWTYPE;
    item RECORD;
BEGIN
    IF p_actor_type NOT IN ('capability_registry','context_builder','sandbox_compiler') THEN
        RAISE EXCEPTION 'CAPABILITY_AUTHORITY_REQUIRED';
    END IF;
    IF NULLIF(btrim(p_actor_id), '') IS NULL THEN
        RAISE EXCEPTION 'CAPABILITY_AUTHORITY_REQUIRED';
    END IF;
    SELECT * INTO command_row FROM public.command_receipts
    WHERE command_id = p_command_id
      AND project_id = p_project_id
      AND command_type = p_command_type
      AND idempotency_key = p_idempotency_key
      AND request_hash = p_request_hash
      AND status = 'PROCESSING'
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'CAPABILITY_COMMAND_SEMANTICS_MISMATCH';
    END IF;
    IF public.hermes_capability_has_secret_value(p_payload) THEN
        RAISE EXCEPTION 'SECRET_VALUE_FORBIDDEN';
    END IF;
    IF p_fault_point = 'after_receipt_placeholder' THEN
        RAISE EXCEPTION 'INJECTED_CAPABILITY_CRASH_AFTER_RECEIPT';
    END IF;

    IF p_fact_type = 'capability_schema' THEN
        IF p_actor_type <> 'capability_registry' THEN
            RAISE EXCEPTION 'CAPABILITY_REGISTRY_AUTHORITY_REQUIRED';
        END IF;
        INSERT INTO public.capability_schemas(
            capability_name, schema_version, description, content_hash,
            command_id, actor_type, actor_id
        ) VALUES (
            p_payload->>'capability_name', p_payload->>'schema_version',
            p_payload->>'description', p_payload->>'content_hash',
            p_command_id, p_actor_type, p_actor_id
        ) ON CONFLICT (capability_name, schema_version) DO NOTHING;
        event_type := 'capability.schema_registered';
        event_payload := jsonb_build_object(
            'capability_name', p_payload->>'capability_name',
            'schema_version', p_payload->>'schema_version',
            'content_hash', p_payload->>'content_hash',
            'entity_version', 1
        );
    ELSIF p_fact_type = 'worker_template_revision' THEN
        IF p_actor_type <> 'capability_registry' THEN
            RAISE EXCEPTION 'CAPABILITY_REGISTRY_AUTHORITY_REQUIRED';
        END IF;
        template := p_payload->'template';
        IF EXISTS (
            SELECT 1 FROM public.worker_template_revisions
            WHERE template_id = template->>'template_id'
              AND revision = (template->>'revision')::BIGINT
        ) THEN
            RAISE EXCEPTION 'WORKER_TEMPLATE_REVISION_EXISTS';
        END IF;
        IF (template->>'revision')::BIGINT <> p_expected_version + 1 THEN
            RAISE EXCEPTION 'WORKER_TEMPLATE_VERSION_CONFLICT';
        END IF;
        INSERT INTO public.worker_template_revisions(
            template_id, revision, project_id, runtime_kind, capabilities,
            trust_level, allowed_tools, supported_sandbox_features,
            resource_envelope, constraint_ranges, concurrency_capacity,
            schema_version, content_hash, command_id, actor_type, actor_id
        ) VALUES (
            template->>'template_id', (template->>'revision')::BIGINT,
            NULLIF(template->>'project_id',''), template->>'runtime_kind',
            ARRAY(SELECT jsonb_array_elements_text(template->'capabilities')),
            template->>'trust_level',
            ARRAY(SELECT jsonb_array_elements_text(template->'allowed_tools')),
            ARRAY(SELECT jsonb_array_elements_text(template->'supported_sandbox_features')),
            template->'resource_envelope', template->'constraint_ranges',
            (template->>'concurrency_capacity')::INTEGER,
            template->>'schema_version', p_payload->>'content_hash',
            p_command_id, p_actor_type, p_actor_id
        );
        INSERT INTO public.worker_template_capabilities(
            template_id, revision, capability_name, schema_version
        )
        SELECT template->>'template_id', (template->>'revision')::BIGINT,
               value, 'capability-schema/1.0'
        FROM jsonb_array_elements_text(template->'capabilities') AS caps(value);
        INSERT INTO public.worker_template_availability(
            template_id, revision, availability_status, admission_status,
            availability_version, reason, command_id, actor_type, actor_id
        ) VALUES (
            template->>'template_id', (template->>'revision')::BIGINT,
            'DISABLED', 'NOT_ADMISSIBLE', 1, 'created disabled until activated',
            p_command_id, p_actor_type, p_actor_id
        );
        target_version := 1;
        event_type := 'worker_template.revision_created';
        event_payload := jsonb_build_object(
            'template_id', template->>'template_id',
            'revision', (template->>'revision')::BIGINT,
            'content_hash', p_payload->>'content_hash',
            'availability_version', 1,
            'entity_version', (template->>'revision')::BIGINT
        );
    ELSIF p_fact_type = 'worker_template_availability' THEN
        IF p_actor_type <> 'capability_registry' THEN
            RAISE EXCEPTION 'CAPABILITY_REGISTRY_AUTHORITY_REQUIRED';
        END IF;
        SELECT * INTO current_template FROM public.worker_template_revisions
        WHERE template_id = p_payload->>'template_id'
          AND revision = (p_payload->>'revision')::BIGINT
        FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'WORKER_TEMPLATE_REVISION_NOT_FOUND';
        END IF;
        SELECT * INTO availability_row FROM public.worker_template_availability
        WHERE template_id = p_payload->>'template_id'
          AND revision = (p_payload->>'revision')::BIGINT
        FOR UPDATE;
        IF NOT FOUND OR availability_row.availability_version <> p_expected_version THEN
            RAISE EXCEPTION 'WORKER_TEMPLATE_AVAILABILITY_VERSION_CONFLICT';
        END IF;
        target_version := availability_row.availability_version + 1;
        UPDATE public.worker_template_availability
        SET availability_status = p_payload->>'availability_status',
            admission_status = p_payload->>'admission_status',
            availability_version = target_version,
            reason = p_command_type,
            command_id = p_command_id,
            actor_type = p_actor_type,
            actor_id = p_actor_id,
            updated_at = now()
        WHERE template_id = p_payload->>'template_id'
          AND revision = (p_payload->>'revision')::BIGINT
          AND availability_version = p_expected_version;
        event_type := 'worker_template.availability_changed';
        event_payload := jsonb_build_object(
            'template_id', p_payload->>'template_id',
            'revision', (p_payload->>'revision')::BIGINT,
            'availability_status', p_payload->>'availability_status',
            'admission_status', p_payload->>'admission_status',
            'availability_version', target_version,
            'entity_version', target_version
        );
    ELSIF p_fact_type = 'capability_match' THEN
        IF p_actor_type <> 'capability_registry' THEN
            RAISE EXCEPTION 'CAPABILITY_REGISTRY_AUTHORITY_REQUIRED';
        END IF;
        match := p_payload->'match';
        SELECT * INTO decision_row FROM public.decision_records
        WHERE decision_id = p_payload->'requirement'->>'decision_id'
          AND project_id = p_project_id
        FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'CAPABILITY_DECISION_NOT_FOUND';
        END IF;
        SELECT * INTO action_row FROM public.candidate_actions
        WHERE action_id = p_payload->'requirement'->>'action_id'
          AND project_id = p_project_id
        FOR SHARE;
        IF NOT FOUND OR action_row.content_hash <> p_payload->'requirement'->>'action_content_hash' THEN
            RAISE EXCEPTION 'CAPABILITY_ACTION_HASH_MISMATCH';
        END IF;
        IF match->>'status' = 'MATCHED' THEN
            SELECT * INTO availability_row FROM public.worker_template_availability
            WHERE template_id = match->>'template_id'
              AND revision = (match->>'template_revision')::BIGINT
              AND availability_version = (match->>'availability_version')::BIGINT
              AND availability_status = 'AVAILABLE'
              AND admission_status = 'ADMISSIBLE'
            FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'WORKER_TEMPLATE_AVAILABILITY_STALE';
            END IF;
        END IF;
        INSERT INTO public.capability_match_records(
            match_id, project_id, task_id, decision_id, action_id, status,
            reason_code, requirements_hash, matcher_version, template_id,
            template_revision, availability_version, template_content_hash,
            requirement, command_id, actor_type, actor_id
        ) VALUES (
            match->>'match_id', p_project_id, p_payload->'requirement'->>'task_id',
            p_payload->'requirement'->>'decision_id',
            p_payload->'requirement'->>'action_id',
            match->>'status', match->>'reason_code',
            match->>'requirements_hash', match->>'matcher_version',
            NULLIF(match->>'template_id',''),
            NULLIF(match->>'template_revision','')::BIGINT,
            NULLIF(match->>'availability_version','')::BIGINT,
            NULLIF(match->>'template_content_hash',''),
            p_payload->'requirement', p_command_id, p_actor_type, p_actor_id
        )
        ON CONFLICT (project_id, requirements_hash, matcher_version) DO NOTHING;
        target_version := 1;
        event_type := 'capability.match_recorded';
        event_payload := jsonb_build_object(
            'match_id', match->>'match_id',
            'status', match->>'status',
            'reason_code', match->>'reason_code',
            'requirements_hash', match->>'requirements_hash',
            'template_id', match->>'template_id',
            'template_revision', match->>'template_revision',
            'entity_version', 1
        );
    ELSIF p_fact_type = 'context_bundle' THEN
        IF p_actor_type <> 'context_builder' THEN
            RAISE EXCEPTION 'CONTEXT_BUILDER_AUTHORITY_REQUIRED';
        END IF;
        bundle := p_payload->'bundle';
        SELECT * INTO task_row FROM public.tasks
        WHERE task_id = bundle->>'task_id'
          AND project_id = p_project_id
        FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'CONTEXT_TASK_NOT_FOUND';
        END IF;
        SELECT * INTO decision_row FROM public.decision_records
        WHERE decision_id = bundle->>'decision_id'
          AND project_id = p_project_id
        FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'CONTEXT_DECISION_NOT_FOUND';
        END IF;
        SELECT * INTO action_row FROM public.candidate_actions
        WHERE action_id = bundle->>'action_id'
          AND project_id = p_project_id
        FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'CONTEXT_ACTION_NOT_FOUND';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.worker_template_revisions
            WHERE template_id = bundle->>'template_id'
              AND revision = (bundle->>'template_revision')::BIGINT
        ) THEN
            RAISE EXCEPTION 'CONTEXT_TEMPLATE_NOT_FOUND';
        END IF;
        INSERT INTO public.context_bundles(
            bundle_id, project_id, task_id, decision_id, action_id,
            template_id, template_revision, selector_schema_version,
            builder_version, manifest, manifest_hash, command_id,
            actor_type, actor_id
        ) VALUES (
            bundle->>'bundle_id', p_project_id, bundle->>'task_id',
            bundle->>'decision_id', bundle->>'action_id',
            bundle->>'template_id', (bundle->>'template_revision')::BIGINT,
            bundle->>'selector_schema_version', bundle->>'builder_version',
            bundle->'manifest', bundle->>'manifest_hash',
            p_command_id, p_actor_type, p_actor_id
        ) ON CONFLICT (manifest_hash) DO NOTHING;
        INSERT INTO public.context_bundle_items(
            bundle_id, ordinal, ref_type, ref_id, project_id, task_id,
            ref_version, content_hash, metadata
        )
        SELECT bundle->>'bundle_id', cb_item.ordinal - 1,
               cb_item.value->>'ref_type', cb_item.value->>'ref_id',
               cb_item.value->>'project_id', cb_item.value->>'task_id',
               NULLIF(cb_item.value->>'version','')::BIGINT,
               cb_item.value->>'content_hash',
               COALESCE(cb_item.value->'metadata', '{}'::jsonb)
        FROM jsonb_array_elements(COALESCE(p_payload->'items','[]'::jsonb))
             WITH ORDINALITY AS cb_item(value, ordinal)
        ON CONFLICT DO NOTHING;
        target_version := 1;
        event_type := 'context.bundle_created';
        event_payload := jsonb_build_object(
            'bundle_id', bundle->>'bundle_id',
            'manifest_hash', bundle->>'manifest_hash',
            'selector_schema_version', bundle->>'selector_schema_version',
            'builder_version', bundle->>'builder_version',
            'entity_version', 1
        );
    ELSIF p_fact_type = 'sandbox_profile' THEN
        IF p_actor_type <> 'sandbox_compiler' THEN
            RAISE EXCEPTION 'SANDBOX_COMPILER_AUTHORITY_REQUIRED';
        END IF;
        profile := p_payload->'profile';
        IF NOT EXISTS (
            SELECT 1 FROM public.context_bundles
            WHERE manifest_hash = profile->>'context_bundle_hash'
              AND project_id = p_project_id
        ) THEN
            RAISE EXCEPTION 'SANDBOX_CONTEXT_BUNDLE_NOT_FOUND';
        END IF;
        INSERT INTO public.sandbox_profiles(
            profile_id, project_id, task_id, action_id, template_id,
            template_revision, context_bundle_hash, compiler_version,
            target, profile, profile_hash, constraints_hash, command_id,
            actor_type, actor_id
        ) VALUES (
            profile->>'profile_id', p_project_id, profile->>'task_id',
            profile->>'action_id', profile->>'template_id',
            (profile->>'template_revision')::BIGINT,
            profile->>'context_bundle_hash', profile->>'compiler_version',
            profile->>'target', profile->'profile',
            profile->>'profile_hash', profile->>'constraints_hash',
            p_command_id, p_actor_type, p_actor_id
        ) ON CONFLICT (profile_hash) DO NOTHING;
        target_version := 1;
        event_type := 'sandbox.profile_compiled';
        event_payload := jsonb_build_object(
            'profile_id', profile->>'profile_id',
            'profile_hash', profile->>'profile_hash',
            'constraints_hash', profile->>'constraints_hash',
            'compiler_version', profile->>'compiler_version',
            'target', profile->>'target',
            'entity_version', 1
        );
    ELSE
        RAISE EXCEPTION 'CAPABILITY_FACT_TYPE_UNSUPPORTED';
    END IF;

    IF p_fault_point = 'after_authority_before_event' THEN
        RAISE EXCEPTION 'INJECTED_CAPABILITY_CRASH_AFTER_AUTHORITY';
    END IF;
    event_id := 'evt-' || gen_random_uuid()::text;
    INSERT INTO public.event_log(
        event_id, event_type, schema_version, producer_type, producer_id,
        project_id, partition_key, command_id, correlation_id, causation_id,
        task_id, payload
    ) VALUES (
        event_id, event_type, '1.0', p_actor_type, p_actor_id, p_project_id,
        p_project_id, p_command_id, p_command_id, p_command_id,
        COALESCE(event_payload->>'task_id', event_payload->>'action_id'),
        event_payload
    ) RETURNING sequence INTO event_sequence;
    IF p_fault_point = 'after_event_before_outbox' THEN
        RAISE EXCEPTION 'INJECTED_CAPABILITY_CRASH_AFTER_EVENT';
    END IF;
    INSERT INTO public.outbox_messages(message_id, event_id, topic, partition_key, sequence, payload)
    VALUES ('msg-' || gen_random_uuid()::text, event_id, 'hermes.runtime.events',
            p_project_id, event_sequence, event_payload);
    IF p_fault_point = 'after_outbox_before_receipt' THEN
        RAISE EXCEPTION 'INJECTED_CAPABILITY_CRASH_AFTER_OUTBOX';
    END IF;

    RETURN jsonb_build_object(
        'event_id', event_id,
        'target_version', target_version,
        'deduplicated', false
    );
END;
$$;

ALTER TABLE public.capability_schemas OWNER TO hermes_capability_owner;
ALTER TABLE public.worker_template_revisions OWNER TO hermes_capability_owner;
ALTER TABLE public.worker_template_capabilities OWNER TO hermes_capability_owner;
ALTER TABLE public.worker_template_availability OWNER TO hermes_capability_owner;
ALTER TABLE public.capability_match_records OWNER TO hermes_capability_owner;
ALTER TABLE public.context_bundles OWNER TO hermes_capability_owner;
ALTER TABLE public.context_bundle_items OWNER TO hermes_capability_owner;
ALTER TABLE public.sandbox_profiles OWNER TO hermes_capability_owner;
ALTER FUNCTION public.hermes_reject_capability_history_change() OWNER TO hermes_capability_owner;
ALTER FUNCTION public.hermes_capability_has_secret_value(JSONB) OWNER TO hermes_capability_owner;
CREATE OR REPLACE FUNCTION public.hermes_register_capability_schema(
    p_payload JSONB, p_project_id TEXT, p_expected_version BIGINT,
    p_command_id TEXT, p_idempotency_key TEXT, p_request_hash TEXT,
    p_command_type TEXT, p_actor_type TEXT, p_actor_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    SELECT public.hermes_apply_execution_preparation_fact_internal(
        'capability_schema', p_payload, p_project_id, p_expected_version,
        p_command_id, p_idempotency_key, p_request_hash, p_command_type,
        p_actor_type, p_actor_id, p_fault_point
    )
$$;

CREATE OR REPLACE FUNCTION public.hermes_create_worker_template_revision(
    p_payload JSONB, p_project_id TEXT, p_expected_version BIGINT,
    p_command_id TEXT, p_idempotency_key TEXT, p_request_hash TEXT,
    p_command_type TEXT, p_actor_type TEXT, p_actor_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    SELECT public.hermes_apply_execution_preparation_fact_internal(
        'worker_template_revision', p_payload, p_project_id, p_expected_version,
        p_command_id, p_idempotency_key, p_request_hash, p_command_type,
        p_actor_type, p_actor_id, p_fault_point
    )
$$;

CREATE OR REPLACE FUNCTION public.hermes_change_worker_template_availability(
    p_payload JSONB, p_project_id TEXT, p_expected_version BIGINT,
    p_command_id TEXT, p_idempotency_key TEXT, p_request_hash TEXT,
    p_command_type TEXT, p_actor_type TEXT, p_actor_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    SELECT public.hermes_apply_execution_preparation_fact_internal(
        'worker_template_availability', p_payload, p_project_id, p_expected_version,
        p_command_id, p_idempotency_key, p_request_hash, p_command_type,
        p_actor_type, p_actor_id, p_fault_point
    )
$$;

CREATE OR REPLACE FUNCTION public.hermes_record_capability_match(
    p_payload JSONB, p_project_id TEXT, p_expected_version BIGINT,
    p_command_id TEXT, p_idempotency_key TEXT, p_request_hash TEXT,
    p_command_type TEXT, p_actor_type TEXT, p_actor_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    SELECT public.hermes_apply_execution_preparation_fact_internal(
        'capability_match', p_payload, p_project_id, p_expected_version,
        p_command_id, p_idempotency_key, p_request_hash, p_command_type,
        p_actor_type, p_actor_id, p_fault_point
    )
$$;

CREATE OR REPLACE FUNCTION public.hermes_create_context_bundle(
    p_payload JSONB, p_project_id TEXT, p_expected_version BIGINT,
    p_command_id TEXT, p_idempotency_key TEXT, p_request_hash TEXT,
    p_command_type TEXT, p_actor_type TEXT, p_actor_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    SELECT public.hermes_apply_execution_preparation_fact_internal(
        'context_bundle', p_payload, p_project_id, p_expected_version,
        p_command_id, p_idempotency_key, p_request_hash, p_command_type,
        p_actor_type, p_actor_id, p_fault_point
    )
$$;

CREATE OR REPLACE FUNCTION public.hermes_compile_sandbox_profile(
    p_payload JSONB, p_project_id TEXT, p_expected_version BIGINT,
    p_command_id TEXT, p_idempotency_key TEXT, p_request_hash TEXT,
    p_command_type TEXT, p_actor_type TEXT, p_actor_id TEXT,
    p_fault_point TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    SELECT public.hermes_apply_execution_preparation_fact_internal(
        'sandbox_profile', p_payload, p_project_id, p_expected_version,
        p_command_id, p_idempotency_key, p_request_hash, p_command_type,
        p_actor_type, p_actor_id, p_fault_point
    )
$$;

ALTER FUNCTION public.hermes_apply_execution_preparation_fact_internal(
    TEXT,JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) OWNER TO hermes_capability_owner;
ALTER FUNCTION public.hermes_register_capability_schema(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) OWNER TO hermes_capability_owner;
ALTER FUNCTION public.hermes_create_worker_template_revision(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) OWNER TO hermes_capability_owner;
ALTER FUNCTION public.hermes_change_worker_template_availability(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) OWNER TO hermes_capability_owner;
ALTER FUNCTION public.hermes_record_capability_match(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) OWNER TO hermes_capability_owner;
ALTER FUNCTION public.hermes_create_context_bundle(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) OWNER TO hermes_capability_owner;
ALTER FUNCTION public.hermes_compile_sandbox_profile(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) OWNER TO hermes_capability_owner;

GRANT SELECT ON public.projects, public.tasks, public.artifacts, public.evidence,
    public.verification_plans, public.decision_records, public.selected_action_refs,
    public.decision_reservation_mappings, public.candidate_actions,
    public.policy_decisions, public.current_policy_decisions,
    public.risk_assessments, public.current_risk_assessments,
    public.resource_reservations, public.command_receipts
    TO hermes_capability_owner;
GRANT UPDATE ON public.tasks, public.decision_records, public.candidate_actions
    TO hermes_capability_owner;
GRANT SELECT, INSERT ON public.capability_schemas,
    public.worker_template_revisions, public.worker_template_capabilities,
    public.capability_match_records, public.context_bundles,
    public.context_bundle_items, public.sandbox_profiles
    TO hermes_capability_owner;
GRANT SELECT, INSERT, UPDATE ON public.worker_template_availability
    TO hermes_capability_owner;
GRANT SELECT, INSERT ON public.event_log, public.outbox_messages
    TO hermes_capability_owner;
GRANT SELECT, INSERT, UPDATE ON public.command_receipts
    TO hermes_capability_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_capability_owner;

REVOKE ALL ON public.capability_schemas, public.worker_template_revisions,
    public.worker_template_capabilities, public.worker_template_availability,
    public.capability_match_records, public.context_bundles,
    public.context_bundle_items, public.sandbox_profiles FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_reject_capability_history_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_capability_has_secret_value(JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_apply_execution_preparation_fact_internal(
    TEXT,JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_register_capability_schema(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_create_worker_template_revision(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_change_worker_template_availability(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_record_capability_match(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_create_context_bundle(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_compile_sandbox_profile(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC;

GRANT SELECT ON public.capability_schemas, public.worker_template_revisions,
    public.worker_template_capabilities, public.worker_template_availability,
    public.capability_match_records, public.context_bundles,
    public.context_bundle_items, public.sandbox_profiles
    TO hermes_capability_runtime, hermes_read_only_runtime;
GRANT SELECT ON public.projects, public.tasks, public.artifacts, public.evidence,
    public.verification_plans, public.decision_records, public.selected_action_refs,
    public.decision_reservation_mappings, public.candidate_actions,
    public.policy_decisions, public.current_policy_decisions,
    public.risk_assessments, public.current_risk_assessments,
    public.resource_reservations TO hermes_capability_runtime;
GRANT SELECT, INSERT, UPDATE ON public.command_receipts TO hermes_capability_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_register_capability_schema(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) TO hermes_capability_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_create_worker_template_revision(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) TO hermes_capability_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_change_worker_template_availability(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) TO hermes_capability_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_record_capability_match(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) TO hermes_capability_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_create_context_bundle(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) TO hermes_capability_runtime;
GRANT EXECUTE ON FUNCTION public.hermes_compile_sandbox_profile(
    JSONB,TEXT,BIGINT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) TO hermes_capability_runtime;

REVOKE INSERT, UPDATE, DELETE ON public.capability_schemas,
    public.worker_template_revisions, public.worker_template_capabilities,
    public.worker_template_availability, public.capability_match_records,
    public.context_bundles, public.context_bundle_items, public.sandbox_profiles,
    public.decision_records, public.selected_action_refs, public.candidate_actions,
    public.policy_decisions, public.risk_assessments, public.resource_reservations,
    public.projects, public.tasks
FROM hermes_capability_runtime, hermes_worker_runtime, hermes_verifier_runtime,
     hermes_control_plane_runtime, hermes_read_only_runtime,
     hermes_selection_runtime, hermes_policy_runtime, hermes_risk_runtime,
     hermes_accounting_runtime, hermes_planner_runtime, hermes_diagnosis_runtime,
     hermes_situation_runtime;
REVOKE CREATE ON SCHEMA public FROM hermes_capability_runtime;

COMMENT ON TABLE public.worker_template_revisions IS
'Immutable WorkerTemplate revisions. Trust changes require a new revision; availability is separate mutable authority.';
COMMENT ON TABLE public.context_bundles IS
'Immutable Context Bundle manifests containing authority refs, versions and hashes only; no mutable object bodies or secret values.';
COMMENT ON TABLE public.sandbox_profiles IS
'Immutable backend-neutral SandboxProfile compile outputs; they do not indicate real sandbox execution.';
