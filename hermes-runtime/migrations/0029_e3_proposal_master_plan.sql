BEGIN;

CREATE TABLE IF NOT EXISTS public.entry_proposals (
  proposal_id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL UNIQUE REFERENCES public.entry_drafts(draft_id),
  creator_subject TEXT NOT NULL,
  version BIGINT NOT NULL CHECK (version >= 1),
  latest_revision_number BIGINT NOT NULL CHECK (latest_revision_number >= 1),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS entry_proposals_creator_updated_idx ON public.entry_proposals(creator_subject, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.entry_proposal_revisions (
  proposal_revision_id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL REFERENCES public.entry_proposals(proposal_id),
  revision_number BIGINT NOT NULL CHECK (revision_number >= 1),
  source_draft_id TEXT NOT NULL REFERENCES public.entry_drafts(draft_id),
  source_draft_revision_id TEXT NOT NULL REFERENCES public.entry_draft_revisions(revision_id),
  source_understanding_id TEXT NOT NULL REFERENCES public.entry_understandings(understanding_id),
  source_understanding_revision_id TEXT NOT NULL REFERENCES public.entry_understanding_revisions(understanding_revision_id),
  compiler_name TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  canonical_content JSONB NOT NULL,
  canonical_content_hash CHAR(64) NOT NULL CHECK (canonical_content_hash ~ '^[0-9a-f]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(proposal_id, revision_number),
  UNIQUE(proposal_id, canonical_content_hash)
);
CREATE INDEX IF NOT EXISTS entry_proposal_revisions_source_idx ON public.entry_proposal_revisions(source_draft_revision_id, source_understanding_revision_id);

CREATE TABLE IF NOT EXISTS public.entry_master_plans (
  master_plan_id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL UNIQUE REFERENCES public.entry_proposals(proposal_id),
  draft_id TEXT NOT NULL REFERENCES public.entry_drafts(draft_id),
  creator_subject TEXT NOT NULL,
  version BIGINT NOT NULL CHECK (version >= 1),
  latest_revision_number BIGINT NOT NULL CHECK (latest_revision_number >= 1),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS entry_master_plans_creator_updated_idx ON public.entry_master_plans(creator_subject, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.entry_master_plan_revisions (
  master_plan_revision_id TEXT PRIMARY KEY,
  master_plan_id TEXT NOT NULL REFERENCES public.entry_master_plans(master_plan_id),
  revision_number BIGINT NOT NULL CHECK (revision_number >= 1),
  proposal_revision_id TEXT NOT NULL REFERENCES public.entry_proposal_revisions(proposal_revision_id),
  proposal_content_hash CHAR(64) NOT NULL CHECK (proposal_content_hash ~ '^[0-9a-f]{64}$'),
  source_draft_revision_id TEXT NOT NULL REFERENCES public.entry_draft_revisions(revision_id),
  source_understanding_revision_id TEXT NOT NULL REFERENCES public.entry_understanding_revisions(understanding_revision_id),
  compiler_name TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  canonical_content JSONB NOT NULL,
  canonical_content_hash CHAR(64) NOT NULL CHECK (canonical_content_hash ~ '^[0-9a-f]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(master_plan_id, revision_number),
  UNIQUE(master_plan_id, canonical_content_hash)
);
CREATE INDEX IF NOT EXISTS entry_master_plan_revisions_source_idx ON public.entry_master_plan_revisions(proposal_revision_id, source_draft_revision_id, source_understanding_revision_id);

CREATE TABLE IF NOT EXISTS public.entry_proposal_plan_command_receipts (
  command_id TEXT PRIMARY KEY,
  actor_subject TEXT NOT NULL,
  command_type TEXT NOT NULL CHECK (command_type IN ('GENERATE_PROPOSAL', 'GENERATE_MASTER_PLAN')),
  idempotency_key TEXT NOT NULL,
  request_fingerprint CHAR(64) NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  status TEXT NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED')),
  result_payload JSONB,
  error_code TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(actor_subject, command_type, idempotency_key)
);
CREATE INDEX IF NOT EXISTS entry_proposal_plan_receipts_actor_created_idx ON public.entry_proposal_plan_command_receipts(actor_subject, created_at DESC);

CREATE OR REPLACE FUNCTION public.hermes_e3_reject_immutable_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'E3 immutable authority record';
END;
$$;

DROP TRIGGER IF EXISTS hermes_e3_proposal_revision_immutable ON public.entry_proposal_revisions;
CREATE TRIGGER hermes_e3_proposal_revision_immutable
BEFORE UPDATE OR DELETE ON public.entry_proposal_revisions
FOR EACH ROW EXECUTE FUNCTION public.hermes_e3_reject_immutable_change();

DROP TRIGGER IF EXISTS hermes_e3_master_plan_revision_immutable ON public.entry_master_plan_revisions;
CREATE TRIGGER hermes_e3_master_plan_revision_immutable
BEFORE UPDATE OR DELETE ON public.entry_master_plan_revisions
FOR EACH ROW EXECUTE FUNCTION public.hermes_e3_reject_immutable_change();

REVOKE ALL ON public.entry_proposals, public.entry_proposal_revisions,
  public.entry_master_plans, public.entry_master_plan_revisions,
  public.entry_proposal_plan_command_receipts FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON public.entry_proposals, public.entry_master_plans,
  public.entry_proposal_plan_command_receipts TO hermes_control_plane_runtime;
GRANT SELECT, INSERT ON public.entry_proposal_revisions, public.entry_master_plan_revisions
  TO hermes_control_plane_runtime;
GRANT SELECT ON public.entry_proposals, public.entry_proposal_revisions,
  public.entry_master_plans, public.entry_master_plan_revisions,
  public.entry_proposal_plan_command_receipts TO hermes_read_only_runtime;

COMMIT;
