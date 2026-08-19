-- E1 EntryDraft Core: isolated pre-Production intent authority.
-- Does not alter Project, Task, Execution, Gate, P6 or any existing runtime table.

CREATE TABLE IF NOT EXISTS public.entry_drafts (
    draft_id TEXT PRIMARY KEY,
    creator_subject TEXT NOT NULL CHECK (length(btrim(creator_subject)) > 0),
    title TEXT NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 240),
    raw_input TEXT NOT NULL CHECK (length(btrim(raw_input)) BETWEEN 1 AND 20000),
    state TEXT NOT NULL CHECK (state IN ('DRAFT', 'SUBMITTED', 'ARCHIVED')),
    version BIGINT NOT NULL CHECK (version >= 1),
    latest_revision_number INTEGER NOT NULL CHECK (latest_revision_number >= 1),
    last_command_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS entry_drafts_creator_updated_idx
    ON public.entry_drafts (creator_subject, updated_at DESC, draft_id);

CREATE TABLE IF NOT EXISTS public.entry_draft_revisions (
    revision_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL REFERENCES public.entry_drafts(draft_id),
    revision_number INTEGER NOT NULL CHECK (revision_number >= 1),
    title TEXT NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 240),
    raw_input TEXT NOT NULL CHECK (length(btrim(raw_input)) BETWEEN 1 AND 20000),
    created_by_subject TEXT NOT NULL CHECK (length(btrim(created_by_subject)) > 0),
    draft_version BIGINT NOT NULL CHECK (draft_version >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (draft_id, revision_number)
);
CREATE INDEX IF NOT EXISTS entry_draft_revisions_draft_revision_idx
    ON public.entry_draft_revisions (draft_id, revision_number ASC);

CREATE TABLE IF NOT EXISTS public.entry_draft_transition_records (
    transition_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL REFERENCES public.entry_drafts(draft_id),
    command_id TEXT NOT NULL,
    previous_state TEXT,
    new_state TEXT NOT NULL CHECK (new_state IN ('DRAFT', 'SUBMITTED', 'ARCHIVED')),
    draft_version BIGINT NOT NULL CHECK (draft_version >= 1),
    actor_subject TEXT NOT NULL CHECK (length(btrim(actor_subject)) > 0),
    reason TEXT NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 1000),
    idempotency_key TEXT NOT NULL CHECK (length(btrim(idempotency_key)) BETWEEN 1 AND 256),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (command_id)
);
CREATE INDEX IF NOT EXISTS entry_draft_transition_records_draft_idx
    ON public.entry_draft_transition_records (draft_id, occurred_at ASC);

CREATE TABLE IF NOT EXISTS public.entry_draft_command_receipts (
    command_id TEXT PRIMARY KEY,
    creator_subject TEXT NOT NULL CHECK (length(btrim(creator_subject)) > 0),
    draft_id TEXT,
    command_type TEXT NOT NULL CHECK (command_type IN ('entry_draft.create', 'entry_draft.revise', 'entry_draft.submit', 'entry_draft.archive')),
    idempotency_key TEXT NOT NULL CHECK (length(btrim(idempotency_key)) BETWEEN 1 AND 256),
    request_hash TEXT NOT NULL CHECK (request_hash LIKE 'sha256:%'),
    status TEXT NOT NULL CHECK (status IN ('PROCESSING', 'APPLIED', 'REJECTED')),
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (creator_subject, command_type, idempotency_key)
);
CREATE INDEX IF NOT EXISTS entry_draft_command_receipts_draft_idx
    ON public.entry_draft_command_receipts (draft_id, created_at DESC);

CREATE OR REPLACE FUNCTION public.hermes_entry_draft_reject_immutable_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$;
DROP TRIGGER IF EXISTS entry_draft_revisions_immutable ON public.entry_draft_revisions;
CREATE TRIGGER entry_draft_revisions_immutable
BEFORE UPDATE OR DELETE ON public.entry_draft_revisions
FOR EACH ROW EXECUTE FUNCTION public.hermes_entry_draft_reject_immutable_change();
DROP TRIGGER IF EXISTS entry_draft_transitions_immutable ON public.entry_draft_transition_records;
CREATE TRIGGER entry_draft_transitions_immutable
BEFORE UPDATE OR DELETE ON public.entry_draft_transition_records
FOR EACH ROW EXECUTE FUNCTION public.hermes_entry_draft_reject_immutable_change();

REVOKE ALL ON public.entry_drafts, public.entry_draft_revisions,
    public.entry_draft_transition_records, public.entry_draft_command_receipts FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON public.entry_drafts, public.entry_draft_revisions,
    public.entry_draft_transition_records, public.entry_draft_command_receipts TO hermes_control_plane_runtime;
GRANT SELECT ON public.entry_drafts, public.entry_draft_revisions,
    public.entry_draft_transition_records, public.entry_draft_command_receipts TO hermes_read_only_runtime;
