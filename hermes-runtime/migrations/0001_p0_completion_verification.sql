CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN (
            'READY', 'RUNNING', 'COMPLETION_CLAIMED',
            'VERIFYING', 'PASSED', 'FAILED'
        )
    ),
    version BIGINT NOT NULL CHECK (version >= 0),
    current_artifact_id TEXT,
    current_artifact_hash TEXT,
    current_verification_id TEXT,
    completion_worker_identity TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (current_artifact_id IS NULL AND current_artifact_hash IS NULL)
        OR
        (current_artifact_id IS NOT NULL AND current_artifact_hash LIKE 'sha256:%')
    )
);

CREATE TABLE IF NOT EXISTS verifier_identities (
    verifier_id TEXT PRIMARY KEY,
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    content_hash TEXT NOT NULL CHECK (content_hash LIKE 'sha256:%'),
    media_type TEXT NOT NULL,
    produced_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (task_id, artifact_id, content_hash)
);

ALTER TABLE tasks
    DROP CONSTRAINT IF EXISTS tasks_current_artifact_fk;
ALTER TABLE tasks
    ADD CONSTRAINT tasks_current_artifact_fk
    FOREIGN KEY (task_id, current_artifact_id, current_artifact_hash)
    REFERENCES artifacts(task_id, artifact_id, content_hash)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE IF NOT EXISTS command_receipts (
    command_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    command_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PROCESSING', 'APPLIED', 'REJECTED')),
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (project_id, command_type, idempotency_key)
);

CREATE TABLE IF NOT EXISTS completion_claims (
    claim_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    run_id TEXT NOT NULL,
    worker_identity TEXT NOT NULL,
    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
    artifact_hash TEXT NOT NULL CHECK (artifact_hash LIKE 'sha256:%'),
    summary TEXT NOT NULL,
    command_id TEXT NOT NULL UNIQUE REFERENCES command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (task_id, run_id)
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
    artifact_hash TEXT NOT NULL CHECK (artifact_hash LIKE 'sha256:%'),
    producer_identity TEXT NOT NULL,
    valid BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS verification_results (
    verification_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
    artifact_hash TEXT NOT NULL CHECK (artifact_hash LIKE 'sha256:%'),
    verifier_identity TEXT NOT NULL REFERENCES verifier_identities(verifier_id),
    criteria TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (
        verdict IN ('PASS', 'FAIL', 'INCONCLUSIVE', 'ERROR', 'CANCELLED')
    ),
    correlation_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    command_id TEXT NOT NULL UNIQUE REFERENCES command_receipts(command_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (task_id, artifact_id, artifact_hash, criteria, verifier_identity)
);

ALTER TABLE tasks
    DROP CONSTRAINT IF EXISTS tasks_current_verification_fk;
ALTER TABLE tasks
    ADD CONSTRAINT tasks_current_verification_fk
    FOREIGN KEY (current_verification_id)
    REFERENCES verification_results(verification_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE IF NOT EXISTS verification_evidence (
    verification_id TEXT NOT NULL REFERENCES verification_results(verification_id),
    evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
    PRIMARY KEY (verification_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS event_log (
    sequence BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    producer_type TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    command_id TEXT NOT NULL REFERENCES command_receipts(command_id),
    correlation_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS outbox_messages (
    message_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE REFERENCES event_log(event_id),
    topic TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    sequence BIGINT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING', 'PUBLISHED', 'DEAD_LETTERED')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_records (
    audit_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    source_command_id TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_command_id, reason_code)
);

CREATE TABLE IF NOT EXISTS consumer_inbox (
    consumer_id TEXT NOT NULL,
    event_id TEXT NOT NULL REFERENCES event_log(event_id),
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (consumer_id, event_id)
);

CREATE TABLE IF NOT EXISTS consumer_effects (
    consumer_id TEXT NOT NULL,
    event_id TEXT NOT NULL REFERENCES event_log(event_id),
    effect_count INTEGER NOT NULL CHECK (effect_count = 1),
    PRIMARY KEY (consumer_id, event_id)
);

CREATE TABLE IF NOT EXISTS consumer_checkpoints (
    consumer_id TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    last_sequence BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (consumer_id, partition_key)
);

CREATE OR REPLACE FUNCTION hermes_reject_immutable_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only/immutable', TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS event_log_immutable ON event_log;
CREATE TRIGGER event_log_immutable
BEFORE UPDATE OR DELETE ON event_log
FOR EACH ROW EXECUTE FUNCTION hermes_reject_immutable_change();

DROP TRIGGER IF EXISTS verification_results_immutable ON verification_results;
CREATE TRIGGER verification_results_immutable
BEFORE UPDATE OR DELETE ON verification_results
FOR EACH ROW EXECUTE FUNCTION hermes_reject_immutable_change();

DROP TRIGGER IF EXISTS evidence_immutable ON evidence;
CREATE TRIGGER evidence_immutable
BEFORE UPDATE OR DELETE ON evidence
FOR EACH ROW EXECUTE FUNCTION hermes_reject_immutable_change();

DROP TRIGGER IF EXISTS artifacts_immutable ON artifacts;
CREATE TRIGGER artifacts_immutable
BEFORE UPDATE OR DELETE ON artifacts
FOR EACH ROW EXECUTE FUNCTION hermes_reject_immutable_change();

COMMENT ON TABLE tasks IS
'Authoritative Task state. Only the Control Plane command store may mutate rows.';
COMMENT ON TABLE event_log IS
'Append-only facts; not the sole source of authoritative state.';
COMMENT ON TABLE outbox_messages IS
'Transport records inserted in the same local transaction as authority changes.';
