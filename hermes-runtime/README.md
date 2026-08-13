# Hermes Runtime: P0 Authority plus P1 Resource, Situation, Diagnosis and Planner Slices

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

ResourceAccount -> atomic multi-dimensional Reservation(expected_version)
-> immutable UsageRecord -> exactly-once Settlement/release
-> threshold status -> authoritative Project Budget Fact

Whitelisted Event -> immutable sequence-bounded AnalysisContext
-> deterministic classification + canonical fingerprint
-> guarded Situation create/update/supersede/resolve
-> Situation Event + Outbox + Inbox + contiguous Checkpoint

OPEN Situation + exact version + frozen AnalysisContext
-> normalized Verification Findings and scoped Evidence refs
-> deterministic `diagnosis-rules/1.0`
-> immutable Diagnosis + current pointer + Event/Outbox/Receipt

OPEN Situation + exact version + frozen AnalysisContext
-> exact current Diagnosis when required
-> deterministic `action-registry/1.0` and `planner-rules/1.0`
-> immutable PlanningRun + CandidateActions + current pointer
-> action.candidates_planned Event + Outbox + CommandReceipt

Current CandidateAction
-> deterministic `policy-bundle/1.0` and typed constraint merge
-> immutable PolicyDecision + current pointer + Event/Outbox/Receipt

Current CandidateAction
-> deterministic `risk-model/1.0`
-> immutable RiskAssessment + current pointer + Event/Outbox/Receipt

Current CandidateAction + current PolicyDecision + current RiskAssessment
-> authoritative locked ResourceAccount feasibility
-> deterministic `selection-weight-profile/1.0` ActionScore
-> `selection-conflict-rules/1.0` conflict/concurrency filtering
-> immutable DecisionRecord + SelectedAction refs
-> atomic ResourceReservation + budget.reserved + decision.recorded
-> Outbox + CommandReceipt
```

It does not implement Web APIs, Human Gate lifecycle, ExecutionRequest,
Scheduler/Lease/fencing, Worker selection, SandboxProfile compilation, dynamic
Capability Registry, Agent execution coupling, Kafka, Redis, Kubernetes, LLM
planning/policy/risk/selection or full Event Sourcing. FI-16/FI-17 are closed
only for the Accounting preparation and settlement portions; P2/P3 execution
coupling remains future work.

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
- Resource Accounting supports the twelve V1.2 integer dimensions, atomic Reservation, Usage, Settlement, thresholds and Budget Fact invalidation.
- `hermes_accounting_runtime` executes only guarded Accounting functions and has no direct balance or Budget Fact write privilege.
- `hermes_situation_runtime` executes only guarded Situation functions; it cannot write Situation tables directly or mutate Project, Task or ResourceAccount authority.
- Situation classification uses `situation-rules/1.0`; fingerprinting uses `situation-fingerprint/1.0` and a Project-scoped active unique constraint.
- `hermes_diagnosis_runtime` executes only the guarded Diagnosis function; it cannot write Diagnosis tables directly or mutate Situation, Project, Task, Artifact or Evidence authority.
- Diagnosis uses deterministic `diagnosis-rules/1.0`; `UNKNOWN` with `root_cause = NULL` is a valid result when Evidence is insufficient, unsupported or contradicted.
- `hermes_planner_runtime` executes only the guarded Planner function; it cannot
  write Planning tables directly, mutate upstream authority or create
  ResourceReservations/ExecutionRequests.
- Candidate planning uses deterministic `action-registry/1.0`,
  `planner-rules/1.0` and `resource-estimator/1.0`.
- CandidateAction is not authorization, risk approval, selection, queueing,
  leasing, Worker assignment or execution. ResourceEstimate is not Reservation.
- `hermes_policy_runtime` executes only the guarded Policy function; PolicyDecision
  is immutable and `ALLOW` only means the Candidate may enter later checks.
- `hermes_risk_runtime` executes only the guarded Risk function; RiskAssessment
  never authorizes or selects an Action and cannot change PolicyDecision.
- Policy uses `policy-bundle/1.0`; Risk uses `risk-model/1.0`; both bind to the
  exact current PlanningRun/CandidateAction and reject stale contexts.
- `hermes_selection_runtime` executes only the guarded Selection function.
  Selection reads authoritative PlanningRun/CandidateAction/Policy/Risk and
  locked ResourceAccount state; it cannot accept caller-provided score,
  authorization, selected refs or `budget_ok`.
- ActionScore uses `selection-weight-profile/1.0` and
  `selection-normalizer/1.0`, stores eight integer basis-point dimensions, and
  uses `DEFAULT_NO_HISTORY` until a formal historical-success authority exists.
- Selection applies Policy -> Risk constraints -> Budget -> Score -> Conflict ->
  Select. `DENY` and unauthenticated `REQUIRE_HUMAN` are filtered before scoring.
- DecisionRecord, candidate dispositions, ActionScores, score dimensions and
  selected-action refs are immutable. `selection_heads` is only a current
  pointer/version.
- Non-zero selected actions receive exact ResourceReservations in the same
  PostgreSQL transaction as `decision.recorded`, `budget.reserved`, Outbox rows
  and CommandReceipt finalization.
- SelectedAction refs are execution intent only. They are not ExecutionRequest,
  queue item, lease, Worker assignment, Sandbox profile or Human Gate state.

Only `ControlPlane` receives a `PostgresRuntimeStore`. Accounting uses
`ResourceAccounting` with a `PostgresResourceAccountingStore`; Selection uses
`ActionSelection` with a `PostgresSelectionStore`. The migrations define and
test separate NOLOGIN capability roles for authority, Accounting, Situation,
Diagnosis, Planner, Policy, Risk, Selection, Relay, Consumer, Redrive, Worker and
read-only access. A production deployment MUST create distinct login credentials
and grant each process only its matching capability role.

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
