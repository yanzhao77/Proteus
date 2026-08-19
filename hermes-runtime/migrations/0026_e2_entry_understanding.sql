BEGIN;
CREATE TABLE IF NOT EXISTS public.entry_understandings (
  understanding_id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL UNIQUE REFERENCES public.entry_drafts(draft_id),
  creator_subject TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('READY','NEEDS_CLARIFICATION')),
  version BIGINT NOT NULL CHECK (version >= 1),
  latest_revision_number BIGINT NOT NULL CHECK (latest_revision_number >= 1),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS entry_understandings_creator_updated_idx ON public.entry_understandings(creator_subject, updated_at DESC);
CREATE TABLE IF NOT EXISTS public.entry_understanding_revisions (
  understanding_revision_id TEXT PRIMARY KEY,
  understanding_id TEXT NOT NULL REFERENCES public.entry_understandings(understanding_id),
  revision_number BIGINT NOT NULL CHECK (revision_number >= 1),
  source_draft_id TEXT NOT NULL REFERENCES public.entry_drafts(draft_id),
  source_draft_revision_number BIGINT NOT NULL CHECK (source_draft_revision_number >= 1),
  source_raw_input TEXT NOT NULL,
  interpreted_intent TEXT NOT NULL CHECK (length(trim(interpreted_intent)) > 0),
  objective TEXT,
  user_constraints JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(user_constraints)='array'),
  explicit_requirements JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(explicit_requirements)='array'),
  ambiguities JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(ambiguities)='array'),
  open_questions JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(open_questions)='array'),
  confidence NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  provider_metadata JSONB,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(understanding_id, revision_number)
);
CREATE TABLE IF NOT EXISTS public.entry_clarifications (
  clarification_id TEXT PRIMARY KEY,
  understanding_id TEXT NOT NULL REFERENCES public.entry_understandings(understanding_id),
  understanding_revision_id TEXT NOT NULL REFERENCES public.entry_understanding_revisions(understanding_revision_id),
  question TEXT NOT NULL CHECK (length(trim(question)) > 0),
  rationale TEXT,
  state TEXT NOT NULL CHECK (state IN ('OPEN','ANSWERED')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  answered_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS entry_clarifications_understanding_state_idx ON public.entry_clarifications(understanding_id, state);
CREATE TABLE IF NOT EXISTS public.entry_clarification_answers (
  answer_id TEXT PRIMARY KEY,
  clarification_id TEXT NOT NULL REFERENCES public.entry_clarifications(clarification_id),
  answer TEXT NOT NULL CHECK (length(trim(answer)) > 0),
  answered_by_subject TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(clarification_id)
);
CREATE TABLE IF NOT EXISTS public.entry_understanding_assumptions (
  assumption_id TEXT PRIMARY KEY,
  understanding_id TEXT NOT NULL REFERENCES public.entry_understandings(understanding_id),
  understanding_revision_id TEXT NOT NULL REFERENCES public.entry_understanding_revisions(understanding_revision_id),
  statement TEXT NOT NULL CHECK (length(trim(statement)) > 0),
  basis TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.entry_understanding_transition_records (
  transition_id TEXT PRIMARY KEY,
  understanding_id TEXT NOT NULL REFERENCES public.entry_understandings(understanding_id),
  command_id TEXT NOT NULL,
  previous_state TEXT,
  new_state TEXT NOT NULL CHECK (new_state IN ('READY','NEEDS_CLARIFICATION')),
  understanding_version BIGINT NOT NULL,
  actor_subject TEXT NOT NULL,
  reason TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.entry_understanding_command_receipts (
  command_id TEXT PRIMARY KEY,
  creator_subject TEXT NOT NULL,
  understanding_id TEXT,
  command_type TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('PROCESSING','APPLIED','REJECTED')),
  result JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  UNIQUE(creator_subject, command_type, idempotency_key)
);
CREATE OR REPLACE FUNCTION public.hermes_e2_reject_immutable_change() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME; END; $$;
DROP TRIGGER IF EXISTS hermes_e2_understanding_revision_immutable ON public.entry_understanding_revisions;
CREATE TRIGGER hermes_e2_understanding_revision_immutable BEFORE UPDATE OR DELETE ON public.entry_understanding_revisions FOR EACH ROW EXECUTE FUNCTION public.hermes_e2_reject_immutable_change();
DROP TRIGGER IF EXISTS hermes_e2_answer_immutable ON public.entry_clarification_answers;
CREATE TRIGGER hermes_e2_answer_immutable BEFORE UPDATE OR DELETE ON public.entry_clarification_answers FOR EACH ROW EXECUTE FUNCTION public.hermes_e2_reject_immutable_change();
DROP TRIGGER IF EXISTS hermes_e2_assumption_immutable ON public.entry_understanding_assumptions;
CREATE TRIGGER hermes_e2_assumption_immutable BEFORE UPDATE OR DELETE ON public.entry_understanding_assumptions FOR EACH ROW EXECUTE FUNCTION public.hermes_e2_reject_immutable_change();
DROP TRIGGER IF EXISTS hermes_e2_transition_immutable ON public.entry_understanding_transition_records;
CREATE TRIGGER hermes_e2_transition_immutable BEFORE UPDATE OR DELETE ON public.entry_understanding_transition_records FOR EACH ROW EXECUTE FUNCTION public.hermes_e2_reject_immutable_change();
GRANT SELECT, INSERT, UPDATE ON public.entry_understandings, public.entry_clarifications, public.entry_understanding_command_receipts TO hermes_control_plane_runtime;
GRANT SELECT, INSERT ON public.entry_understanding_revisions, public.entry_clarification_answers, public.entry_understanding_assumptions, public.entry_understanding_transition_records TO hermes_control_plane_runtime;
COMMIT;
