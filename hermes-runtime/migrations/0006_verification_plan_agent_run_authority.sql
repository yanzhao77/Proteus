-- P0 closure: authoritative VerificationPlan and minimal AgentRun identity.

CREATE TABLE IF NOT EXISTS public.agent_runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    run_kind TEXT NOT NULL CHECK (run_kind IN ('WORKER', 'VERIFIER')),
    agent_identity TEXT NOT NULL,
    context_identity TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ADMITTED', 'COMPLETED', 'INVALIDATED')),
    created_by TEXT NOT NULL,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    version BIGINT NOT NULL DEFAULT 1 CHECK (version >= 1),
    UNIQUE (run_id, project_id, task_id, run_kind, agent_identity)
);

CREATE TABLE IF NOT EXISTS public.verification_plans (
    verification_plan_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES public.tasks(task_id),
    project_id TEXT NOT NULL,
    version BIGINT NOT NULL CHECK (version >= 1),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'SUPERSEDED', 'INVALIDATED')),
    artifact_selectors JSONB NOT NULL,
    aggregation_rule TEXT NOT NULL CHECK (aggregation_rule = 'all_required_pass'),
    independence TEXT NOT NULL CHECK (independence = 'worker_context_excluded'),
    created_by TEXT NOT NULL,
    command_id TEXT NOT NULL UNIQUE REFERENCES public.command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at TIMESTAMPTZ,
    PRIMARY KEY (verification_plan_id, version),
    UNIQUE (task_id, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS verification_plans_one_active_per_task
    ON public.verification_plans(task_id) WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS public.verification_plan_checks (
    verification_plan_id TEXT NOT NULL,
    plan_version BIGINT NOT NULL,
    check_id TEXT NOT NULL,
    type TEXT NOT NULL,
    runner_profile TEXT NOT NULL,
    required BOOLEAN NOT NULL,
    timeout_seconds INTEGER NOT NULL CHECK (timeout_seconds > 0),
    pass_condition TEXT NOT NULL,
    evidence_level TEXT NOT NULL CHECK (evidence_level IN ('E0','E1','E2','E3','E4')),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (verification_plan_id, plan_version, check_id),
    UNIQUE (verification_plan_id, plan_version, ordinal),
    FOREIGN KEY (verification_plan_id, plan_version)
        REFERENCES public.verification_plans(verification_plan_id, version)
);

ALTER TABLE public.tasks
    ADD COLUMN IF NOT EXISTS current_verification_plan_id TEXT,
    ADD COLUMN IF NOT EXISTS current_verification_plan_version BIGINT,
    ADD COLUMN IF NOT EXISTS completion_worker_run_id TEXT,
    ADD COLUMN IF NOT EXISTS completion_worker_context_identity TEXT;

ALTER TABLE public.tasks DROP CONSTRAINT IF EXISTS tasks_current_verification_plan_fk;
ALTER TABLE public.tasks ADD CONSTRAINT tasks_current_verification_plan_fk
    FOREIGN KEY (current_verification_plan_id, current_verification_plan_version)
    REFERENCES public.verification_plans(verification_plan_id, version)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE public.artifacts ADD COLUMN IF NOT EXISTS produced_by_run_id TEXT;
ALTER TABLE public.artifacts DROP CONSTRAINT IF EXISTS artifacts_produced_by_run_fk;
ALTER TABLE public.artifacts ADD CONSTRAINT artifacts_produced_by_run_fk
    FOREIGN KEY (produced_by_run_id) REFERENCES public.agent_runs(run_id);

ALTER TABLE public.completion_claims DROP CONSTRAINT IF EXISTS completion_claims_run_fk;
ALTER TABLE public.completion_claims ADD CONSTRAINT completion_claims_run_fk
    FOREIGN KEY (run_id) REFERENCES public.agent_runs(run_id) NOT VALID;

ALTER TABLE public.verification_results
    ADD COLUMN IF NOT EXISTS authority_status TEXT NOT NULL DEFAULT 'LEGACY'
        CHECK (authority_status IN ('LEGACY', 'AUTHORITATIVE')),
    ADD COLUMN IF NOT EXISTS plan_id TEXT,
    ADD COLUMN IF NOT EXISTS plan_version BIGINT,
    ADD COLUMN IF NOT EXISTS project_id TEXT,
    ADD COLUMN IF NOT EXISTS verifier_run_id TEXT,
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

ALTER TABLE public.verification_results
    DROP CONSTRAINT IF EXISTS verification_results_task_id_artifact_id_artifact_hash_crit_key;

ALTER TABLE public.verification_results
    DROP CONSTRAINT IF EXISTS verification_results_plan_fk;
ALTER TABLE public.verification_results ADD CONSTRAINT verification_results_plan_fk
    FOREIGN KEY (plan_id, plan_version)
    REFERENCES public.verification_plans(verification_plan_id, version);
ALTER TABLE public.verification_results
    DROP CONSTRAINT IF EXISTS verification_results_verifier_run_fk;
ALTER TABLE public.verification_results ADD CONSTRAINT verification_results_verifier_run_fk
    FOREIGN KEY (verifier_run_id) REFERENCES public.agent_runs(run_id);
ALTER TABLE public.verification_results
    DROP CONSTRAINT IF EXISTS verification_results_authority_shape;
ALTER TABLE public.verification_results ADD CONSTRAINT verification_results_authority_shape
    CHECK (
        authority_status = 'LEGACY'
        OR (plan_id IS NOT NULL AND plan_version IS NOT NULL
            AND project_id IS NOT NULL AND verifier_run_id IS NOT NULL
            AND started_at IS NOT NULL AND completed_at IS NOT NULL)
    );

CREATE TABLE IF NOT EXISTS public.verification_check_results (
    verification_id TEXT NOT NULL REFERENCES public.verification_results(verification_id),
    check_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PASS','FAIL','INCONCLUSIVE','ERROR','CANCELLED')),
    finding_codes JSONB NOT NULL,
    evidence_refs JSONB NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (verification_id, check_id)
);

CREATE OR REPLACE FUNCTION public.hermes_task_pass_authority_invariant()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF NEW.state = 'PASSED' AND NOT EXISTS (
        SELECT 1
        FROM public.verification_results v
        JOIN public.verification_plans p
          ON p.verification_plan_id = v.plan_id AND p.version = v.plan_version
        WHERE v.verification_id = NEW.current_verification_id
          AND v.authority_status = 'AUTHORITATIVE'
          AND v.task_id = NEW.task_id AND v.project_id = NEW.project_id
          AND v.artifact_id = NEW.current_artifact_id
          AND v.artifact_hash = NEW.current_artifact_hash
          AND v.plan_id = NEW.current_verification_plan_id
          AND v.plan_version = NEW.current_verification_plan_version
          AND v.verdict = 'PASS' AND p.status = 'ACTIVE'
          AND NOT EXISTS (
              SELECT 1 FROM public.verification_plan_checks pc
              LEFT JOIN public.verification_check_results cr
                ON cr.verification_id = v.verification_id
               AND cr.check_id = pc.check_id
              WHERE pc.verification_plan_id = p.verification_plan_id
                AND pc.plan_version = p.version AND pc.required
                AND (cr.check_id IS NULL OR cr.status <> 'PASS')
          )
          AND NOT EXISTS (
              SELECT 1 FROM public.verification_check_results cr
              LEFT JOIN public.verification_plan_checks pc
                ON pc.verification_plan_id = p.verification_plan_id
               AND pc.plan_version = p.version AND pc.check_id = cr.check_id
              WHERE cr.verification_id = v.verification_id AND pc.check_id IS NULL
          )
    ) THEN
        RAISE EXCEPTION 'TASK_PASS_VERIFICATION_AUTHORITY_INVARIANT_VIOLATION';
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS tasks_require_authoritative_verification ON public.tasks;
CREATE CONSTRAINT TRIGGER tasks_require_authoritative_verification
AFTER INSERT OR UPDATE OF state,current_artifact_id,current_artifact_hash,
    current_verification_id,current_verification_plan_id,
    current_verification_plan_version ON public.tasks
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.hermes_task_pass_authority_invariant();

CREATE OR REPLACE FUNCTION public.hermes_reject_plan_content_change()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'verification plan is authority-preserved';
    END IF;
    IF NEW.verification_plan_id <> OLD.verification_plan_id
       OR NEW.version <> OLD.version OR NEW.task_id <> OLD.task_id
       OR NEW.project_id <> OLD.project_id
       OR NEW.artifact_selectors <> OLD.artifact_selectors
       OR NEW.aggregation_rule <> OLD.aggregation_rule
       OR NEW.independence <> OLD.independence
       OR NEW.created_by <> OLD.created_by OR NEW.command_id <> OLD.command_id
    THEN RAISE EXCEPTION 'verification plan content is immutable'; END IF;
    IF OLD.status <> 'ACTIVE' OR NEW.status NOT IN ('SUPERSEDED','INVALIDATED') THEN
        RAISE EXCEPTION 'invalid verification plan lifecycle transition';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS verification_plans_guarded_update ON public.verification_plans;
CREATE TRIGGER verification_plans_guarded_update
BEFORE UPDATE OR DELETE ON public.verification_plans
FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_plan_content_change();

CREATE OR REPLACE FUNCTION public.hermes_guard_agent_run_update()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'agent_runs is authority-preserved'; END IF;
    IF NEW.run_id <> OLD.run_id OR NEW.project_id <> OLD.project_id
       OR NEW.task_id <> OLD.task_id OR NEW.run_kind <> OLD.run_kind
       OR NEW.agent_identity <> OLD.agent_identity
       OR NEW.context_identity <> OLD.context_identity
       OR NEW.created_by <> OLD.created_by OR NEW.command_id <> OLD.command_id
       OR NEW.created_at <> OLD.created_at OR NEW.version <> OLD.version + 1
       OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
       OR NEW.status <> 'INVALIDATED' OR OLD.status = 'INVALIDATED'
    THEN RAISE EXCEPTION 'invalid AgentRun authority transition'; END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS agent_runs_immutable ON public.agent_runs;
DROP TRIGGER IF EXISTS agent_runs_guarded_update ON public.agent_runs;
CREATE TRIGGER agent_runs_guarded_update BEFORE UPDATE OR DELETE ON public.agent_runs
FOR EACH ROW EXECUTE FUNCTION public.hermes_guard_agent_run_update();
DROP TRIGGER IF EXISTS verification_plan_checks_immutable ON public.verification_plan_checks;
CREATE TRIGGER verification_plan_checks_immutable BEFORE UPDATE OR DELETE ON public.verification_plan_checks
FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_immutable_change();
DROP TRIGGER IF EXISTS verification_check_results_immutable ON public.verification_check_results;
CREATE TRIGGER verification_check_results_immutable BEFORE UPDATE OR DELETE ON public.verification_check_results
FOR EACH ROW EXECUTE FUNCTION public.hermes_reject_immutable_change();

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='hermes_closure_owner') THEN
        CREATE ROLE hermes_closure_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='hermes_verifier_runtime') THEN
        CREATE ROLE hermes_verifier_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END $$;

ALTER TABLE public.agent_runs OWNER TO hermes_closure_owner;
ALTER TABLE public.verification_plans OWNER TO hermes_closure_owner;
ALTER TABLE public.verification_plan_checks OWNER TO hermes_closure_owner;
ALTER TABLE public.verification_check_results OWNER TO hermes_closure_owner;
ALTER FUNCTION public.hermes_task_pass_authority_invariant() OWNER TO hermes_closure_owner;
ALTER FUNCTION public.hermes_reject_plan_content_change() OWNER TO hermes_closure_owner;
ALTER FUNCTION public.hermes_guard_agent_run_update() OWNER TO hermes_closure_owner;

GRANT SELECT ON public.tasks, public.artifacts, public.evidence,
    public.verification_results, public.command_receipts
    TO hermes_closure_owner;

REVOKE ALL ON public.agent_runs, public.verification_plans,
    public.verification_plan_checks, public.verification_check_results FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_task_pass_authority_invariant() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_reject_plan_content_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hermes_guard_agent_run_update() FROM PUBLIC;
REVOKE ALL ON public.agent_runs, public.verification_plans,
    public.verification_plan_checks, public.verification_results,
    public.verification_check_results FROM hermes_worker_runtime;
REVOKE ALL ON public.tasks FROM hermes_verifier_runtime;
GRANT SELECT ON public.tasks, public.artifacts, public.evidence,
    public.verification_plans, public.verification_plan_checks,
    public.agent_runs TO hermes_verifier_runtime;
GRANT SELECT ON public.agent_runs, public.verification_plans,
    public.verification_plan_checks, public.verification_check_results
    TO hermes_read_only_runtime;
GRANT SELECT ON public.agent_runs, public.verification_plans,
    public.verification_plan_checks, public.verification_check_results
    TO hermes_control_plane_runtime;

COMMENT ON COLUMN public.verification_results.authority_status IS
'Rows predating migration 0006 remain LEGACY and cannot authorize Task PASS/FAIL.';
COMMENT ON TABLE public.agent_runs IS
'Minimal P0 run identity authority only; no Scheduler, Lease or lifecycle implementation.';
