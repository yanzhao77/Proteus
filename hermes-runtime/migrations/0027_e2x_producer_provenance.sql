BEGIN;
CREATE TABLE IF NOT EXISTS public.entry_understanding_provenance (
  understanding_revision_id TEXT PRIMARY KEY REFERENCES public.entry_understanding_revisions(understanding_revision_id),
  source_draft_revision_id TEXT NOT NULL REFERENCES public.entry_draft_revisions(revision_id),
  producer TEXT NOT NULL,
  provider TEXT,
  model TEXT,
  model_version TEXT,
  provider_request_id TEXT,
  correlation_id TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  request_started_at TIMESTAMPTZ NOT NULL,
  completed_at TIMESTAMPTZ NOT NULL,
  latency_ms BIGINT CHECK (latency_ms >= 0),
  retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
  input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
  output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
  total_tokens INTEGER CHECK (total_tokens IS NULL OR total_tokens >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION public.hermes_e2x_reject_provenance_change() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION '% is immutable', TG_TABLE_NAME; END; $$;
DROP TRIGGER IF EXISTS hermes_e2x_provenance_immutable ON public.entry_understanding_provenance;
CREATE TRIGGER hermes_e2x_provenance_immutable BEFORE UPDATE OR DELETE ON public.entry_understanding_provenance FOR EACH ROW EXECUTE FUNCTION public.hermes_e2x_reject_provenance_change();
GRANT SELECT, INSERT ON public.entry_understanding_provenance TO hermes_control_plane_runtime;
COMMIT;
