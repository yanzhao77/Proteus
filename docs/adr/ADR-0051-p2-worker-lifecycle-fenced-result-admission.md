# ADR-0051: P2 Worker Lifecycle, Fenced Result Admission and Settlement Coupling

## Status

ACCEPTED

## Phase

P2-4

## Context

P2-3 ends at an authoritative `LEASED` ExecutionRequest with an ACTIVE Lease,
execution locks and a PostgreSQL-assigned fencing token. P2-4 must admit a
Worker without creating a second execution-run model, move the current request to
`RUNNING`, accept only current-token Worker payloads, quarantine stale payloads,
bridge successful execution to CompletionClaim, and settle or release the
Selection-created ResourceReservation exactly once.

The slice must preserve these boundaries:

- `LEASED != RUNNING`;
- `ExecutionResult SUCCEEDED != Verification PASS`;
- `ExecutionRequest SUCCEEDED != Task PASSED`;
- Worker CompletionClaim is not an authoritative verdict;
- Worker cannot directly write Task, Verification, Event/Outbox, Lease/fencing
  or Accounting authority tables.

## Decision

P2-4 extends the existing P0 `agent_runs` table for Worker execution lifecycle
instead of introducing an `ExecutionRun` table.

Worker execution authority is stored in:

- `agent_runs` P2 binding columns for `execution_request_id`,
  `execution_attempt`, `lease_id`, `lease_version`, `fencing_token`,
  Scheduler holder, WorkerTemplate revision, Context Bundle, SandboxProfile and
  ResourceReservation;
- `execution_worker_assignments`;
- `execution_artifact_candidates`;
- `execution_evidence_candidates`;
- `execution_usage_admissions`;
- immutable `execution_results`;
- immutable `execution_quarantine_records`;
- immutable `execution_result_claim_links`;
- immutable `execution_result_settlement_links`.

`execution.start_run` is the only P2-4 command that transitions a current
request from `LEASED` to `RUNNING`. It verifies, in one PostgreSQL transaction:

- request is currently `LEASED`;
- submitted Lease is the current ACTIVE Lease and has not expired according to
  `clock_timestamp()`;
- submitted Lease version and fencing token match current authority;
- Scheduler holder matches the Lease holder;
- WorkerTemplate revision/content hash, Context Bundle/hash, SandboxProfile/hash
  and ResourceReservation match the frozen ExecutionRequest;
- ResourceReservation is still ACTIVE;
- at most one current WORKER AgentRun exists per request/attempt.

Worker identity is distinct from Scheduler holder identity. The Worker caller
must use `actor_type='worker'` and `actor_id == worker_agent_identity`; free text
cannot elevate WorkerTemplate, context or sandbox identity.

All later Worker-originating writes pass through a shared validation primitive
that checks request/run/attempt/Lease/token/context/expected-version/current-lock
ownership. Current-token writes admit:

- Artifact Candidates;
- Evidence Candidates;
- Usage samples, recorded in the existing P1 UsageRecord model and linked by
  `execution_usage_admissions`;
- one immutable structured ExecutionResult per request/attempt/run.

Stale or invalid Worker payloads are routed to minimal durable quarantine. The
quarantine row and `execution.result_quarantined` Event/Outbox are committed in
the same transaction and do not mutate Artifact, Usage, Settlement,
ExecutionRequest terminal state, Task state or Verification authority. P3 owns
quarantine retention, review, adoption, redrive and reconcile operations.

On an accepted terminal Result:

- an immutable `execution_results` row is written first;
- `SUCCEEDED` may promote the selected Artifact Candidate to the existing
  `artifacts` table and create an existing P0 CompletionClaim;
- no VerificationResult is created and Task is not marked `PASSED` or `FAILED`;
- ResourceReservation settlement or release is performed exactly once in the
  same database transaction;
- AgentRun becomes `SUCCEEDED` or `FAILED`;
- ExecutionRequest current state becomes `SUCCEEDED`, `FAILED` or `CANCELLED`;
- Queue state becomes `TERMINAL`;
- Lease and lock ownership are released by setting Lease state to
  `RELINQUISHED` with a business terminal reason.

If a Lease is superseded or expires through Scheduler authority while a Worker
AgentRun is still current, a trigger invalidates or expires the old Worker
AgentRun and assignment. The old Worker cannot recover authority; late payloads
are quarantined.

## Consequences

- P0/P1 AgentRun, CompletionClaim and Accounting models remain canonical; P2-4
  adds bindings and link tables rather than parallel concepts.
- `ExecutionResult SUCCEEDED` closes execution transport/protocol outcome only.
  Formal `PASS/FAIL` remains Verification Engine authority.
- FI-09 is closed for P2 core by stale Result quarantine and no authority
  mutation.
- FI-10 is closed across Scheduler/Lease and Worker late-token isolation.
- FI-17 is closed for P2 core by single-transaction Result/Usage/Settlement
  coupling and concurrent terminal Result isolation. P3 reconcile remains
  separate.
- CT-003 core is closed by current-token admission, stale-token quarantine and
  Task-state isolation. CT-003 full quarantine operations remain P3.
- Real Docker/Process sandbox execution, business retry/replan feedback, Human
  Gate, full quarantine operations and external side-effect reconcile remain
  later scope.

## Evidence

- `hermes-runtime/migrations/0016_worker_lifecycle_result_admission.sql`
- `hermes-runtime/src/hermes_runtime/domain/worker_execution.py`
- `hermes-runtime/src/hermes_runtime/application/workers.py`
- `hermes-runtime/src/hermes_runtime/infrastructure/postgres_worker_execution.py`
- `hermes-runtime/tests/test_worker_execution_domain.py`
- `hermes-runtime/tests/test_worker_execution_postgres.py`
- `hermes-runtime/tests/test_worker_execution_permissions.py`
