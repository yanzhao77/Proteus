# Hermes Runtime: P0 Authority and Delivery Slices

This package implements these authority, delivery and accounting slices:

```text
CompletionClaim
-> authoritative WORKER AgentRun + Artifact provenance
-> exact Artifact hash VerificationResult
-> current versioned VerificationPlan + structured required CheckResults
-> independent VERIFIER AgentRun and execution context
-> Control Plane guarded PASS/FAIL transition
-> PostgreSQL Event Log + transactional Outbox + CommandReceipt

feedback.created
-> idempotent Repair Task creation
-> project-versioned Graph Patch
-> acyclic Task dependencies + cyclic typed Work Graph
-> authoritative READY calculation

Explicit Project Command
-> deterministic Project State Machine Guard
-> fail-closed Project Guard facts for Evidence/Policy/Budget/Gate
-> PostgreSQL guarded authority function
-> Project state + Event Log + Outbox + CommandReceipt

Committed Outbox -> leased one-shot Relay -> durable local publisher
-> conditional publish/retry/DLQ -> authorized identity-preserving redrive

Event Envelope -> schema validation -> partition-contiguous Consumer
-> effect + Inbox + Checkpoint atomically -> bounded gap parking/drain

Resource reservation -> idempotent settlement/release
-> authoritative balance + immutable accounting entries
```

It does not implement Web APIs, Scheduler/Lease, Human Gate, Agent integration, Kafka, Redis, Kubernetes or full Event Sourcing. Resource Accounting is present as a focused domain and PostgreSQL persistence slice; it is not yet integrated with Scheduler/Lease or a complete Worker lifecycle.

## Authority boundary

- Worker calls `SubmitCompletionClaim`; it cannot produce a verdict or write Task state.
- Control Plane admits minimal WORKER/VERIFIER AgentRun identity; this is not Scheduler or Lease implementation.
- CompletionClaim must reference a same-Project/same-Task WORKER Run and binds Artifact provenance to it.
- Verification calls `RecordVerificationResult`; recording does not update Task state.
- VerificationResult must reference the current active Plan/version and an independent VERIFIER Run/context; verdict is recomputed from required Checks.
- Control Plane calls `ApplyVerifiedTaskTransition`; it validates identity, Evidence, exact Artifact hash, expected version and Guard.
- PostgreSQL commits authority state, Event Log, Outbox and CommandReceipt in one local transaction.
- Task scheduling uses only `Task -DEPENDS_ON-> Task`; other typed Work Graph edges may cycle.
- A successful Graph Patch increments one Project-scoped graph version exactly once.
- Project state is committed only by Control Plane through semantic Commands.
- Project transitions fail closed without authoritative Guard facts; `supporting_refs` are lookup hints, not permission.
- Runtime roles cannot directly update `projects`; a deferred invariant rejects a Project version without its matching Event and Outbox message.
- Event ordering is partition-local; checkpoints never advance across a missing sequence.
- Relay claims commit before transport I/O and use expiring owner plus claim token isolation.
- Delivery is at least once; duplicate business effects are prevented by Consumer Inbox identity.

Only `ControlPlane` receives a `PostgresRuntimeStore`. The migrations define and test separate NOLOGIN capability roles for authority, Relay, Consumer, Redrive, Worker and read-only access. A production deployment MUST create distinct login credentials and grant each process only its matching capability role.

## Run pure domain tests

```bash
cd hermes-runtime
PYTHONPATH=src python3 -m unittest tests.test_domain_authority -v
```

## Run PostgreSQL integration tests

The test contract requires PostgreSQL 14+ and Psycopg 3. A disposable local database is sufficient:

```bash
docker run --rm --name hermes-p0-postgres \
  -e POSTGRES_PASSWORD=hermes \
  -e POSTGRES_DB=hermes_test \
  -p 55432:5432 \
  -d postgres:16-alpine

python3 -m pip install -r requirements.txt
HERMES_TEST_DATABASE_URL='postgresql://postgres:hermes@127.0.0.1:55432/hermes_test' \
  PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Without `HERMES_TEST_DATABASE_URL`, discovery skips PostgreSQL tests rather than treating SQLite or a mock as proof.

## Run one Relay batch

`OutboxRelay.run_once(batch_size)` is the application entry point. A one-shot local runner is available as:

```bash
HERMES_DATABASE_URL='postgresql://...' PYTHONPATH=src \
  python3 -m hermes_runtime.relay_once --owner relay-1 --batch-size 100
```

It uses the durable `PostgresLocalPublisher` adapter. No permanent background loop or external broker is included.
