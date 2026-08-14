# Hermes Runtime: P0-P3 Authority Runtime Slices

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

SelectedAction execution intent
-> versioned Capability schema + immutable WorkerTemplate revision
-> separate availability/admission state
-> deterministic capability match record with exact revision/version
-> immutable Context Bundle manifest refs/hashes
-> backend-neutral `contract-only/1.0` SandboxProfile hash
-> Event/Outbox/CommandReceipt

Admitted SelectedAction execution
-> `execution.prepare_request` fail-closed admission validation
-> existing P1 ResourceReservation handoff/binding
-> immutable `QUEUED` ExecutionRequest snapshot
-> durable pending PostgreSQL Queue item
-> `execution.request_prepared` + `execution.queued`
-> Outbox + CommandReceipt

QUEUED ExecutionRequest
-> Scheduler registration/admission
-> PostgreSQL durable Queue claim
-> atomic execution lock acquisition
-> monotonic fencing token allocation
-> ACTIVE Lease in current authority tables
-> renew / PostgreSQL-clock expiry takeover / relinquish requeue
-> `execution.lease_*` Events
-> Outbox + CommandReceipt

LEASED ExecutionRequest
-> `execution.start_run` Worker admission
-> P2 WORKER AgentRun binding on the existing P0 AgentRun model
-> RUNNING current state
-> fenced Artifact/Evidence Candidate and Usage sample admission
-> immutable structured ExecutionResult
-> current-token terminal admission or stale-payload quarantine
-> CompletionClaim bridge without Verification PASS
-> ResourceReservation settlement/release in the same transaction
-> terminal Request/Queue/Run state and Lease/lock release
-> Events + Outbox + CommandReceipt

FAILED ExecutionResult
-> `recovery.emit_feedback` structured failure taxonomy
-> immutable execution_feedback_records + compatibility feedback_records
-> `feedback.created` + `recovery.cycle_started`
-> Situation / Diagnosis / Planner consumption
-> bounded RecoveryCycle / RecoveryAttempt ledger
-> retry / repair / switch-worker / collaboration / replan / human-gate protocol
-> later execution and independent Verification links
-> Recovery completion without Task PASS/FAIL authority

Checkpoint / Inbox / Event Log
-> versioned and hash-checked contiguous checkpoint authority
-> isolated replay session and target generation
-> shadow projection rebuild / idempotent consumer replay / authority audit boundary
-> verified generation digest and atomic read-model pointer activation
-> reconcile observe / finding / immutable plan / authorized apply
-> whitelisted checkpoint repair only when Inbox+effect continuity is proven
-> no Project/Task/Accounting/Lease/Verification authority rebuild

Quarantine / Evidence / Explain / Docker
-> append-only quarantine review/adoption/redrive requests
-> append-only Evidence invalidation and re-verification requirements
-> immutable Decision Explain snapshots, reference graph and audit traces
-> Docker target 1.0 run plans, process observations and side-effect receipts
-> P3 end-to-end hardening without Task PASS authority bypass
```

It still does not provide Web APIs, Human Gate UI, production IdP/OIDC/SAML
integration, Kafka, Redis, Kubernetes, LLM planning/policy/risk/selection,
browser/VM/GPU execution targets, cloud credential integrations, third-party
irreversible side-effect integrations or full Event Sourcing.
P4-0 through P4-5 add productization facades and ports for API, Human Gate
identity assertions, local Artifact/Secret/Retention and observability exports
without adding a second authority path or production web/IdP/cloud dependency.
P5 defines the deployable single-node product boundary for adding FastAPI
transport, supervised runtime loops, production OIDC/Human Gate UI,
S3-compatible Artifact storage, Vault-compatible secret handling,
OTLP-compatible telemetry and deployment operations without replacing
PostgreSQL authority.
P5-1 implements the FastAPI transport as an application factory over the P4
ProductApiFacade. Importing the module does not connect to PostgreSQL, start
loops or mutate authority.
FI-16 is closed for ExecutionRequest/Queue/Reservation handoff. CT-002 and
P2-LOCK-001 are closed by P2-3. P2-4 closes CT-003 core, FI-09 core, FI-10
Worker stale-token isolation and FI-17 P2 run/settlement coupling. P2-5 closes
structured Feedback emission and bounded autonomous recovery loop entry. P3-1
closes the database-backed Human Gate lifecycle and Project waiting/resume
authority. P3-2 closes checkpoint/replay/reconcile runtime authority and
FI-12A through FI-12G. P3-3 closes quarantine review/adoption/redrive and
Evidence invalidation runtime authority. P3-4 closes Decision Explain/Audit/Trace
runtime. P3-5 closes Docker target 1.0 production execution and side-effect
receipt authority. P3-6 closes cross-slice hardening. Human Gate UI, production
IdP integration, non-Docker execution targets and real cloud/third-party
irreversible side-effect integrations remain productization work.

P2 execution contracts are specified and tracked in
[`docs/specs/Hermes_P2_Execution_Admission_Normative_Spec_V1.0.md`](../docs/specs/Hermes_P2_Execution_Admission_Normative_Spec_V1.0.md)
and [`docs/P2_EXECUTION_ACCEPTANCE_MATRIX.md`](../docs/P2_EXECUTION_ACCEPTANCE_MATRIX.md).
They define that Task `READY` is not execution-admissible, P2 hands off the
existing P1 Selection Reservation instead of reserving again, and `QUEUED` means
Capability, Context, Sandbox, Policy/Risk, Reservation, VerificationPlan,
Artifact and lock prerequisites are already frozen.

P2-1 implements only the freeze-object prerequisites: Capability Registry,
WorkerTemplate revision/availability, Context Bundle manifest and
SandboxProfile Compiler.

P2-2 implements only the preparation/enqueue side: `execution.prepare_request`,
immutable `QUEUED` ExecutionRequest, Reservation binding/handoff, durable pending
Queue item, same-transaction Events/Outbox/Receipt and stable rejection receipts.
`PREPARING` is transaction-local in the current implementation; no durable
runnable `PREPARING` row exists. P2-2 still does not claim Queue items, acquire
leases, mint fencing tokens, spawn Workers, execute sandboxed code, accept
Results or settle execution usage.

P2-3 implements Scheduler/Lease/Fencing/Lock authority only:
`scheduler.register`, `scheduler.acquire_lease`, `scheduler.renew_lease`,
`scheduler.relinquish_lease` and `validate_current_lease`. It keeps P2-2
snapshot tables immutable and stores mutable Scheduler state in
`execution_request_current_states`, `execution_queue_current_states`,
`execution_leases`, `execution_fencing_counters` and
`execution_lock_ownerships`.

P2-4 implements the Worker lifecycle and fenced Result admission core. Migration
`0016_worker_lifecycle_result_admission.sql` establishes database-side Worker
assignment, AgentRun binding, candidate admission, minimal quarantine,
CompletionClaim bridging, terminal Result admission and settlement/release
coupling. The domain model, application commands and PostgreSQL adapter are
present, with five domain tests, eight PostgreSQL integration/concurrency/
fault-injection tests and six permission tests. Real Docker/Process sandbox
execution, external Worker spawning, P2-5 feedback/replan and P3 quarantine
retention/adoption/reconcile operations remain outside this slice.

P2-5 implements structured Feedback and bounded autonomous recovery loop entry.
Migration `0017_feedback_recovery_loop.sql` establishes
`execution_feedback_records`, `recovery_cycles`, `recovery_attempts` and minimal
`recovery_collaboration_requests`, with guarded Recovery Controller functions for
emitting execution failure feedback, planning bounded attempts and completing
attempt ledger entries. It connects failed P2-4 ExecutionResults back through the
existing P1 Situation, Diagnosis and Planner chain, then proves that final Task
PASS still requires independent Verification plus Control Plane transition. It
does not implement Human Gate UX, production Worker process management, real
Docker/Process sandbox execution or P3 replay/quarantine reconciliation.

P3-0 is contract-only documentation. It defines the next operational governance
authorities in
[`docs/specs/Hermes_P3_Operational_Governance_Normative_Spec_V1.0.md`](../docs/specs/Hermes_P3_Operational_Governance_Normative_Spec_V1.0.md)
and tracks them in
[`docs/P3_OPERATIONAL_GOVERNANCE_ACCEPTANCE_MATRIX.md`](../docs/P3_OPERATIONAL_GOVERNANCE_ACCEPTANCE_MATRIX.md).
It adds ADR-0053 through ADR-0059 for Human Gate, Project waiting/resume,
checkpoint/replay/reconcile, quarantine adoption/redrive, Evidence
invalidation, Decision Explain/audit/trace and production execution boundaries.
No P3 runtime code, SQL migration or tests are included in P3-0.

P3-1 implements the PostgreSQL Human Gate and Project waiting/resume authority.
Migration `0018_human_gate_waiting_resume.sql` separates Gate Request, Gate
Decision and Decision Application records, and binds typed Project waiting
records to immutable ResumeContext hashes. Main Hermes/Recovery may request a
Gate, authorized humans/operators may decide, and only Control Plane may apply an
approved Decision after rechecking current Gate, Decision, Waiting,
ResumeContext, Project version, approver authorization, Evidence, Policy and
Budget facts. The P3-1 runtime adds `HumanGateAuthority` and
`PostgresHumanGateStore`, with six pure domain tests, nine PostgreSQL
integration/concurrency/fault tests and four permission tests. PostgreSQL 14 and
PostgreSQL 16 full regression both discovered 369 tests and passed on
2026-08-14; no-DB discovery also found 369 tests and passed with database tests
skipped.

P3-2 implements Checkpoint + Replay + Reconcile authority as a PostgreSQL
overlay on the existing Event Log, Outbox, Inbox and Checkpoint system.
Migration `0019_checkpoint_replay_reconcile.sql` adds versioned/hash-checked
consumer checkpoints, immutable checkpoint history, replay sessions, replay
generations, shadow projection events, generation pointers, reconcile findings
and reconcile plans/repairs. Replay supports read-model rebuild, idempotent
consumer replay and authority-audit modes inside isolated target generations,
then atomically activates a verified generation pointer. Reconcile separates
observe, finding, dry-run/apply plan and authorized apply; the implemented
repair path advances a checkpoint only when existing Inbox and effect records
prove contiguous committed work. Replay/Reconcile cannot rebuild or patch
Project, Task, Accounting, Lease, Worker, Verification or Event Log authority.
P3-3 quarantine operations, Evidence invalidation propagation, P3-4
explain/query runtime and P3-5 production sandbox/external side-effect
reconciliation remain outside this slice.

P3-3 implements Quarantine Operations and Evidence Invalidation authority as a
PostgreSQL overlay. Migration `0020_quarantine_evidence_invalidation.sql` keeps
the original P2 quarantine envelope immutable, adds expected-version lifecycle
pointers plus append-only operation/adoption/redrive ledgers, and ensures
adoption only records a guarded semantic command shell instead of passing a
Task. Redrive requires a new command/idempotency identity while preserving
original causation. The same migration adds append-only Evidence invalidation,
stale dependency and re-verification requirement ledgers; it does not delete
Evidence, rewrite historical VerificationResults or flip `PASSED` Tasks to
`FAILED`. Human Gate Decision insertion and Decision Application fail closed
when referenced Evidence has been invalidated. P3-3 adds pure domain,
PostgreSQL integration/concurrency/fault-injection and permission tests for
both authorities.

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
- `hermes_recovery_runtime` executes only guarded Recovery functions. It cannot
  directly write Task, Verification, Worker execution, Event Log, Outbox,
  Accounting or upstream P1 authority tables.
- Recovery Feedback is a structured fact and planning input, not a state
  transition. RecoveryAttempt completion records links to later execution,
  result and verification facts, but cannot mark a Task `PASSED` or `FAILED`.
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
- `hermes_capability_runtime` executes only guarded Capability/Context/Sandbox
  functions. It cannot directly mutate WorkerTemplate revisions, availability,
  Context Bundles, SandboxProfiles, upstream Selection/Policy/Risk/Accounting
  state, Project or Task authority.
- WorkerTemplate trust uses `UNTRUSTED < STANDARD < ELEVATED < PRIVILEGED`.
  Trust changes require a new immutable revision; availability is mutable but
  versioned separately.
- Context Bundle selectors are typed and bounded. Bundles store refs, versions
  and hashes only; secret values are rejected before authority writes.
- SandboxProfile compilation uses `contract-only/1.0`, intersects allowlists,
  unions deny/mitigation requirements, tightens numeric upper bounds and rejects
  unknown or unsupported mandatory constraints.
- `hermes_execution_runtime` executes only the guarded
  `execution.prepare_request` path. It cannot directly insert or update
  ExecutionRequest, Reservation binding or Queue tables.
- ExecutionRequest `QUEUED` means admission inputs are frozen, exact versions and
  hashes are bound, the P1 Reservation is handed off once, and a future Scheduler
  may attempt Lease acquisition. It does not mean leased, running, succeeded or
  Task `PASSED`.
- Lock intents are normalized, deduplicated and frozen on the Request. Actual
  lock/Lease ownership and fencing are owned by P2-3 Scheduler authority.
- `hermes_scheduler_runtime` executes only guarded Scheduler functions. It
  cannot directly mutate Lease, token, lock, Queue or Request current-state
  tables, and Worker/Verifier/Capability/Accounting/Planner/Execution runtimes
  cannot claim Queue items or mint fencing tokens.
- Lease profile `p2-default/1` uses integer millisecond limits: 30000 initial
  TTL, 10000 renew interval, 30000 max extension, 300000 max lifetime, immediate
  takeover after DB-clock expiry, zero requeue backoff and single-item claim.
- Queue claim fairness is best effort by priority, available_at, enqueued_at and
  queue_item_id; locked or scope-conflicting head items may be skipped so another
  eligible item can run.
- `hermes_worker_runtime` executes only five guarded Worker admission functions:
  `hermes_start_worker_run`,
  `hermes_record_execution_artifact_candidate`,
  `hermes_record_execution_evidence_candidate`,
  `hermes_record_execution_usage_sample` and
  `hermes_submit_execution_result`.
- Worker runtime cannot directly insert/update AgentRun, Result, Candidate,
  Usage, CompletionClaim, VerificationResult, Task, Event Log, Outbox, Lease or
  Accounting authority tables, and cannot execute internal settlement,
  quarantine, validation or event helper functions.
- P2 Worker execution extends `agent_runs`; no second ExecutionRun model exists.
  A current Worker Run binds one request/attempt/Lease/token/frozen
  WorkerTemplate/Context/Sandbox/Reservation tuple.
- Accepted `ExecutionResult(SUCCEEDED)` may create an Artifact and
  CompletionClaim, but never creates a VerificationResult and never marks a Task
  `PASSED` or `FAILED`.
- Stale Worker payloads are committed to minimal immutable quarantine with an
  Event/Outbox and do not mutate current Result, Usage, Settlement, Artifact,
  Task or Verification authority.
- Terminal Result admission commits Result, CompletionClaim link,
  settlement/release link, Request/Queue/Run terminal state, Lease/lock release,
  Events, Outbox and CommandReceipt in one PostgreSQL transaction.
- `hermes_gate_request_runtime` can only request Human Gates with immutable
  ResumeContext bindings; it cannot approve or apply Decisions.
- `hermes_gate_decision_runtime` can only submit scoped authorized human/operator
  Decisions; it cannot mutate Project, Task, Waiting or Application state.
- `hermes_control_plane_runtime` enters Project waiting and applies/expires/
  cancels/supersedes Gate requests through guarded semantic functions; it cannot
  forge Human Decisions.
- Human Decision approval never directly resumes a Project. Application rechecks
  current Gate, Decision, Waiting, ResumeContext hash, Project version, approver
  authorization, Evidence, Policy and Budget before committing
  `human_gate.decision_applied` and `project.resumed`.
- `hermes_replay_runtime` executes only guarded Replay functions. It can create
  isolated sessions/generations, build shadow projection rows and activate a
  verified generation pointer; it cannot write Project, Task, Accounting,
  Lease, Worker, Verification or Event Log authority directly.
- `hermes_reconcile_runtime` observes authority/read-model mismatches and
  creates immutable dry-run/apply plans only; it cannot apply repairs or patch
  authority tables.
- `hermes_reconcile_apply_runtime` applies whitelisted semantic repairs only.
  In P3-2 the only implemented mutating repair is
  `ADVANCE_CHECKPOINT_IF_EFFECT_CONTIGUOUS`, guarded by existing Inbox/effect
  continuity and checkpoint version/hash checks.

Only `ControlPlane` receives a `PostgresRuntimeStore`. Accounting uses
`ResourceAccounting` with a `PostgresResourceAccountingStore`; Selection uses
`ActionSelection` with a `PostgresSelectionStore`; P2-1 execution-preparation
freeze objects use `ExecutionPreparationAuthority` with a
`PostgresCapabilityStore`; P2-2 request preparation uses
`ExecutionPreparation` with a `PostgresExecutionStore`; P2-3 scheduling uses
`ExecutionScheduler` with a `PostgresSchedulerStore`; P2-4 Worker execution uses
`WorkerExecution` with a `PostgresWorkerExecutionStore`; P3-1 Human Gate uses
`HumanGateAuthority` with a `PostgresHumanGateStore`; P3-2 Replay/Reconcile
uses `ReplayReconcileAuthority` with a `PostgresReplayReconcileStore`; P3-3
quarantine operations use `QuarantineAuthority` with a
`PostgresQuarantineStore`; Evidence invalidation uses
`EvidenceInvalidationAuthority` with a `PostgresEvidenceInvalidationStore`;
P3-4 Decision Explain/Audit/Trace uses `DecisionExplainAuthority` with a
`PostgresExplainStore`; P3-5 production Docker execution uses
`ProductionExecutionAuthority`, `PostgresProductionExecutionStore` and
`DockerExecutionAdapter`. The
migrations define and test separate NOLOGIN capability roles for authority,
Accounting, Situation, Diagnosis, Planner, Policy, Risk, Selection,
Capability/Context/Sandbox, Relay, Consumer, Redrive, Worker, Human Gate
request/decision, Replay/Reconcile, Quarantine review/adoption/redrive,
Evidence invalidation, Explain capture/query, Docker adapter, side-effect,
metrics and read-only access. A
production deployment MUST create distinct login credentials and grant each
process only its matching capability role.

The P3-4 runtime adds immutable explain snapshots, reference graph nodes/edges
and audit trace records in `0021_decision_explain_audit_trace.sql`. Historical
Explain records are not recomputed with newer rules, late facts create new
captures instead of mutating old snapshots, missing links are explicit
`MISSING` nodes, and query access is scoped by tenant/project authorization.
The P3-5 runtime adds Docker target 1.0 with deterministic run plans,
deny-by-default network, read-only root filesystem, non-root user, cap drop,
no-new-privileges, bounded output, declared artifact export and side-effect
receipt/reconcile facts in `0022_production_docker_execution.sql`.
P3-6 adds cross-slice E2E hardening tests and
`docs/Hermes_P3_COMPLETION_SUMMARY.md`; it does not introduce a new durable
authority migration.
A PostgreSQL-backed run is required to validate migrations, concurrency and
permissions; discovery without project dependencies or without
`HERMES_TEST_DATABASE_URL` is not phase acceptance.

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
