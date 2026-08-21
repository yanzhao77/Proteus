BEGIN;

CREATE TABLE IF NOT EXISTS public.entry_approval_command_receipts (
  command_id TEXT PRIMARY KEY,
  creator_subject TEXT NOT NULL,
  command_type TEXT NOT NULL CHECK (command_type IN ('APPROVE_ENTRY_PLAN', 'RECONCILE_ENTRY_PLAN')),
  idempotency_key TEXT NOT NULL,
  request_fingerprint CHAR(64) NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  status TEXT NOT NULL CHECK (status IN ('PROCESSING', 'SUCCEEDED', 'FAILED')),
  result_payload JSONB,
  error_code TEXT,
  correlation_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(creator_subject, command_type, idempotency_key)
);

CREATE TABLE IF NOT EXISTS public.entry_approval_bridges (
  bridge_id TEXT PRIMARY KEY,
  approval_command_id TEXT NOT NULL UNIQUE REFERENCES public.entry_approval_command_receipts(command_id),
  creator_subject TEXT NOT NULL,
  approver_subject TEXT NOT NULL,
  draft_id TEXT NOT NULL REFERENCES public.entry_drafts(draft_id),
  source_draft_revision_id TEXT NOT NULL REFERENCES public.entry_draft_revisions(revision_id),
  source_understanding_revision_id TEXT NOT NULL REFERENCES public.entry_understanding_revisions(understanding_revision_id),
  proposal_revision_id TEXT NOT NULL REFERENCES public.entry_proposal_revisions(proposal_revision_id),
  proposal_content_hash CHAR(64) NOT NULL CHECK (proposal_content_hash ~ '^[0-9a-f]{64}$'),
  master_plan_id TEXT NOT NULL REFERENCES public.entry_master_plans(master_plan_id),
  master_plan_revision_id TEXT NOT NULL REFERENCES public.entry_master_plan_revisions(master_plan_revision_id),
  master_plan_content_hash CHAR(64) NOT NULL CHECK (master_plan_content_hash ~ '^[0-9a-f]{64}$'),
  compiler_version TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  compiled_blueprint JSONB NOT NULL,
  compiled_blueprint_hash CHAR(64) NOT NULL CHECK (compiled_blueprint_hash ~ '^[0-9a-f]{64}$'),
  required_acknowledgements JSONB NOT NULL,
  acknowledged_refs JSONB NOT NULL,
  intended_project_id TEXT NOT NULL UNIQUE,
  project_command_id TEXT NOT NULL UNIQUE,
  graph_command_id TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK (status IN ('PROCESSING', 'PROJECT_CREATED', 'GRAPH_APPLIED', 'VERIFICATION_APPLYING', 'MATERIALIZED', 'RECONCILIATION_REQUIRED', 'FAILED_TERMINAL')),
  project_id TEXT,
  materialized_at TIMESTAMPTZ,
  correlation_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(draft_id, master_plan_revision_id)
);
CREATE INDEX IF NOT EXISTS entry_approval_bridges_creator_updated_idx ON public.entry_approval_bridges(creator_subject, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.entry_approval_bridge_steps (
  step_id TEXT PRIMARY KEY,
  bridge_id TEXT NOT NULL REFERENCES public.entry_approval_bridges(bridge_id),
  step_name TEXT NOT NULL CHECK (step_name IN ('CREATE_PROJECT', 'APPLY_GRAPH', 'CREATE_VERIFICATION_PLAN')),
  child_command_id TEXT NOT NULL UNIQUE,
  child_receipt_ref TEXT,
  intended_target_id TEXT NOT NULL,
  request_hash CHAR(64) NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  result_code TEXT,
  status TEXT NOT NULL CHECK (status IN ('PENDING', 'SUCCEEDED', 'RECONCILIATION_REQUIRED', 'FAILED_TERMINAL')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS entry_approval_bridge_steps_bridge_idx ON public.entry_approval_bridge_steps(bridge_id, created_at);

CREATE TABLE IF NOT EXISTS public.entry_approval_bridge_transitions (
  transition_id TEXT PRIMARY KEY,
  bridge_id TEXT NOT NULL REFERENCES public.entry_approval_bridges(bridge_id),
  from_status TEXT,
  to_status TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.entry_approval_materialized_bindings (
  bridge_id TEXT PRIMARY KEY REFERENCES public.entry_approval_bridges(bridge_id),
  draft_id TEXT NOT NULL REFERENCES public.entry_drafts(draft_id),
  master_plan_id TEXT NOT NULL REFERENCES public.entry_master_plans(master_plan_id),
  master_plan_revision_id TEXT NOT NULL REFERENCES public.entry_master_plan_revisions(master_plan_revision_id),
  project_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(draft_id, master_plan_revision_id),
  UNIQUE(project_id)
);

CREATE OR REPLACE FUNCTION public.hermes_e4_reject_immutable_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'E4 immutable authority record';
END;
$$;

CREATE OR REPLACE FUNCTION public.hermes_e4_reject_frozen_bridge_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.approval_command_id IS DISTINCT FROM NEW.approval_command_id
     OR OLD.creator_subject IS DISTINCT FROM NEW.creator_subject
     OR OLD.approver_subject IS DISTINCT FROM NEW.approver_subject
     OR OLD.draft_id IS DISTINCT FROM NEW.draft_id
     OR OLD.source_draft_revision_id IS DISTINCT FROM NEW.source_draft_revision_id
     OR OLD.source_understanding_revision_id IS DISTINCT FROM NEW.source_understanding_revision_id
     OR OLD.proposal_revision_id IS DISTINCT FROM NEW.proposal_revision_id
     OR OLD.proposal_content_hash IS DISTINCT FROM NEW.proposal_content_hash
     OR OLD.master_plan_id IS DISTINCT FROM NEW.master_plan_id
     OR OLD.master_plan_revision_id IS DISTINCT FROM NEW.master_plan_revision_id
     OR OLD.master_plan_content_hash IS DISTINCT FROM NEW.master_plan_content_hash
     OR OLD.compiler_version IS DISTINCT FROM NEW.compiler_version
     OR OLD.policy_version IS DISTINCT FROM NEW.policy_version
     OR OLD.compiled_blueprint IS DISTINCT FROM NEW.compiled_blueprint
     OR OLD.compiled_blueprint_hash IS DISTINCT FROM NEW.compiled_blueprint_hash
     OR OLD.required_acknowledgements IS DISTINCT FROM NEW.required_acknowledgements
     OR OLD.acknowledged_refs IS DISTINCT FROM NEW.acknowledged_refs
     OR OLD.intended_project_id IS DISTINCT FROM NEW.intended_project_id
     OR OLD.project_command_id IS DISTINCT FROM NEW.project_command_id
     OR OLD.graph_command_id IS DISTINCT FROM NEW.graph_command_id
     OR OLD.correlation_id IS DISTINCT FROM NEW.correlation_id THEN
    RAISE EXCEPTION 'E4 frozen bridge authority record';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS hermes_e4_bridge_frozen_immutable ON public.entry_approval_bridges;
CREATE TRIGGER hermes_e4_bridge_frozen_immutable
BEFORE UPDATE ON public.entry_approval_bridges
FOR EACH ROW EXECUTE FUNCTION public.hermes_e4_reject_frozen_bridge_change();

CREATE OR REPLACE FUNCTION public.hermes_e4_reject_receipt_rewrite()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- The only legitimate UPDATE is the transaction-local first fill of the
  -- initially NULL result payload that commits with the frozen bridge record.
  IF OLD.result_payload IS NULL AND NEW.result_payload IS NOT NULL
     AND OLD.command_id IS NOT DISTINCT FROM NEW.command_id
     AND OLD.creator_subject IS NOT DISTINCT FROM NEW.creator_subject
     AND OLD.command_type IS NOT DISTINCT FROM NEW.command_type
     AND OLD.idempotency_key IS NOT DISTINCT FROM NEW.idempotency_key
     AND OLD.request_fingerprint IS NOT DISTINCT FROM NEW.request_fingerprint
     AND OLD.status IS NOT DISTINCT FROM NEW.status
     AND OLD.error_code IS NOT DISTINCT FROM NEW.error_code
     AND OLD.correlation_id IS NOT DISTINCT FROM NEW.correlation_id THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'E4 immutable authority record';
END;
$$;
DROP TRIGGER IF EXISTS hermes_e4_receipt_immutable ON public.entry_approval_command_receipts;
CREATE TRIGGER hermes_e4_receipt_immutable
BEFORE UPDATE OR DELETE ON public.entry_approval_command_receipts
FOR EACH ROW EXECUTE FUNCTION public.hermes_e4_reject_receipt_rewrite();
DROP TRIGGER IF EXISTS hermes_e4_step_immutable ON public.entry_approval_bridge_steps;
CREATE TRIGGER hermes_e4_step_immutable BEFORE UPDATE OR DELETE ON public.entry_approval_bridge_steps FOR EACH ROW EXECUTE FUNCTION public.hermes_e4_reject_immutable_change();
DROP TRIGGER IF EXISTS hermes_e4_transition_immutable ON public.entry_approval_bridge_transitions;
CREATE TRIGGER hermes_e4_transition_immutable BEFORE UPDATE OR DELETE ON public.entry_approval_bridge_transitions FOR EACH ROW EXECUTE FUNCTION public.hermes_e4_reject_immutable_change();
DROP TRIGGER IF EXISTS hermes_e4_binding_immutable ON public.entry_approval_materialized_bindings;
CREATE TRIGGER hermes_e4_binding_immutable BEFORE UPDATE OR DELETE ON public.entry_approval_materialized_bindings FOR EACH ROW EXECUTE FUNCTION public.hermes_e4_reject_immutable_change();

REVOKE ALL ON public.entry_approval_command_receipts, public.entry_approval_bridges,
  public.entry_approval_bridge_steps, public.entry_approval_bridge_transitions,
  public.entry_approval_materialized_bindings FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON public.entry_approval_command_receipts, public.entry_approval_bridges TO hermes_control_plane_runtime;
GRANT SELECT, INSERT ON public.entry_approval_bridge_steps, public.entry_approval_bridge_transitions,
  public.entry_approval_materialized_bindings TO hermes_control_plane_runtime;
GRANT SELECT ON public.entry_approval_command_receipts, public.entry_approval_bridges,
  public.entry_approval_bridge_steps, public.entry_approval_bridge_transitions,
  public.entry_approval_materialized_bindings TO hermes_read_only_runtime;

COMMIT;
