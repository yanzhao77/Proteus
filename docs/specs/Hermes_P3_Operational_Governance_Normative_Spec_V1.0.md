# Hermes P3 Operational Governance Normative Specification V1.0

Status: SPECIFIED; P3-1 through P3-6 runtime authority implemented
Phase: P3-0 contract closure; P3-1 Human Gate + Project Waiting/Resume; P3-2 Checkpoint + Replay + Reconcile; P3-3 Quarantine + Evidence Invalidation; P3-4 Decision Explain/Audit/Trace; P3-5 Docker target 1.0 Production Execution; P3-6 End-to-End Hardening
Date: 2026-08-14

This specification closes the P3 operational governance contracts for Hermes
Runtime V1.2. It defines the authority boundaries required before P3 runtime
implementation work and records the slices now implemented. P3-1 implements the
Human Gate and Project waiting/resume runtime boundary in
[`0018_human_gate_waiting_resume.sql`](../../hermes-runtime/migrations/0018_human_gate_waiting_resume.sql),
[`HumanGateAuthority`](../../hermes-runtime/src/hermes_runtime/application/human_gates.py)
and the PostgreSQL/domain/permission tests listed in the P3 acceptance matrix.
P3-2 implements the Checkpoint, Replay and Reconcile runtime boundary in
[`0019_checkpoint_replay_reconcile.sql`](../../hermes-runtime/migrations/0019_checkpoint_replay_reconcile.sql),
[`ReplayReconcileAuthority`](../../hermes-runtime/src/hermes_runtime/application/replay_reconcile.py)
and the PostgreSQL/domain/permission tests listed in the P3 acceptance matrix.
P3-3 implements quarantine review/adoption/redrive and Evidence invalidation in
[`0020_quarantine_evidence_invalidation.sql`](../../hermes-runtime/migrations/0020_quarantine_evidence_invalidation.sql),
[`QuarantineAuthority`](../../hermes-runtime/src/hermes_runtime/application/quarantine.py)
and
[`EvidenceInvalidationAuthority`](../../hermes-runtime/src/hermes_runtime/application/evidence_invalidation.py).
P3-4 implements Decision Explain, Audit and Trace runtime in
[`0021_decision_explain_audit_trace.sql`](../../hermes-runtime/migrations/0021_decision_explain_audit_trace.sql)
and [`DecisionExplainAuthority`](../../hermes-runtime/src/hermes_runtime/application/explain.py).
P3-5 implements Docker target 1.0 production execution and side-effect receipt
authority in
[`0022_production_docker_execution.sql`](../../hermes-runtime/migrations/0022_production_docker_execution.sql),
[`ProductionExecutionAuthority`](../../hermes-runtime/src/hermes_runtime/application/docker_execution.py)
and [`DockerExecutionAdapter`](../../hermes-runtime/src/hermes_runtime/infrastructure/docker_adapter.py).
P3-6 adds cross-slice end-to-end hardening tests and the completion summary.
This runtime still does not implement Human Gate UI, production
IdP/OIDC/SAML integration, non-Docker execution targets, cloud credential
integrations or real third-party irreversible side-effect integrations.

Normative priority remains:

```text
Core Runtime Design V1.2 invariants
-> Runtime / Command / Lease / P2 normative specs
-> ACCEPTED ADR
-> Acceptance matrices
-> completion summaries
-> V1.0 vision and V1.1 history
```

## 1. P0-P2 completion boundary

P0-P2 are complete for the execution authority chain through bounded autonomous
recovery loop entry:

```text
CompletionClaim
-> independent VerificationResult
-> guarded Task PASS/FAIL transition
-> authoritative Project state + EventLog + Outbox
-> Analysis/Situation/Diagnosis/Planning
-> Policy/Risk/Budget/Selection/Reservation
-> Capability/Context/SandboxProfile freeze
-> ExecutionRequest queue
-> Scheduler Lease + fencing token
-> Worker lifecycle + fenced Result admission
-> minimal stale payload quarantine
-> exact Reservation settlement/release
-> structured Feedback + bounded RecoveryCycle/Attempt ledger
```

P2 deliberately stops before:

- Human Gate request/decision lifecycle and identity authority;
- Project waiting records and resume-context authority;
- full checkpoint/replay/reconcile operations;
- quarantine review, adoption, redrive, retention and reviewer workflow;
- Evidence invalidation propagation and re-verification workflow;
- immutable Decision Explain / audit / trace query model;
- production Worker process manager, real Docker/Process sandbox target and
  external side-effect reconciliation.

These are P3 responsibilities and MUST NOT be claimed as implemented by P3-0.
P3-1 closes the first two bullets for PostgreSQL runtime authority;
checkpoint/replay/reconcile is closed by P3-2; quarantine and Evidence
invalidation are closed by P3-3; immutable Explain/Audit/Trace is closed by
P3-4; Docker target 1.0 and side-effect receipt authority are closed by P3-5.
P3-6 verifies the cross-slice boundary without adding a new durable authority
migration.

## 2. P3 conflict and GAP closure

The existing V1.2 and P0-P2 specifications intentionally left several P3
contracts short-form. P3-0 resolves them as follows:

| GAP | Closure |
| --- | --- |
| Human Gate was independent but under-specified. | Gate Request and Gate Decision are separate authorities; Main Hermes can request/display but cannot approve. |
| Project waiting states risk state explosion. | Keep Project mainline state plus typed waiting records and immutable resume context. |
| CT-009/CT-010 were one-paragraph tests. | Expand them into complete test contracts with actors, commands, rejection codes, concurrency, expiry, crash and replay rules. |
| Replay could be misread as full Event Sourcing. | Replay rebuilds consumer/read/recovery state only; authority repair uses guarded Commands. |
| FI-12 was a single broad scenario. | Split into checkpoint corruption/loss, duplicate, gap, replay, reconcile, crash recovery and authority protection sub-scenarios. |
| P2 quarantine was minimal stale admission. | P3 owns operational lifecycle, reviewer authority, adoption/redrive and retention. |
| Evidence invalidation lacked propagation rules. | Invalidation is append-only, versioned, fail-closed and never rewrites historical VerificationResults. |
| Decision Explain could drift if recomputed at query time. | Explain uses immutable snapshots or versioned fact graph references captured at decision time. |
| Production execution boundary was backend-neutral only. | P3-5 must choose a provable sandbox target; until then the decision gate and minimum semantics are locked here. |

## 3. Authority model

All P3 operational actions MUST enter through explicit semantic Commands with:

- actor type and actor ID;
- authorization reference;
- human-meaningful reason;
- idempotency key;
- canonical payload hash;
- expected aggregate version;
- tenant, project, task and action scope where applicable;
- correlation ID, causation ID and trace ID;
- local PostgreSQL transaction that writes authoritative state, Event Log,
  Outbox and CommandReceipt together;
- rejection audit for fail-closed outcomes.

P3 operational roles MUST NOT receive generic Project, Task, Verification,
Worker execution, Lease, Accounting or Event/Outbox table write privileges.
Implementation MUST preserve `SECURITY DEFINER` owner hardening and narrow
runtime roles.

## 4. Human Gate authority

Human Gate is an independent authority from Main Hermes.

### 4.1 Actors and permissions

| Actor | Allowed |
| --- | --- |
| Main Hermes / Recovery Controller | Create Gate Request and display current state. |
| Policy Engine | Declare `REQUIRE_HUMAN`; it does not approve. |
| User / authorized Operator | Submit a scoped Gate Decision. |
| Human Gate authority | Validate identity, authorization, scope, expiry, version and self-approval rules; apply the Decision. |
| Control Plane | Consume only applied/current Gate Decisions as Guard facts. |
| Worker / Scheduler / Planner / Verifier | No approval, rejection, application or Project/Task mutation authority. |

Main Hermes MUST NOT self-approve a request it created. If the requester and
approver resolve to the same authorization subject, the decision MUST be rejected
with `GATE_SELF_APPROVAL_FORBIDDEN` unless a later high-risk multi-approval ADR
defines a stronger explicit exception. High-risk dual-control policy is deferred,
but the data model MUST preserve reviewer slots and authorization references so
P3-4/P3-6 can audit it.

### 4.2 Request and Decision separation

Gate Request lifecycle:

```text
REQUESTED -> APPROVED / REJECTED / EXPIRED / CANCELLED / SUPERSEDED
```

`APPROVED` and `REJECTED` mean a Decision has been accepted by Human Gate
authority, not that Project or Task state changed. `SUPERSEDED` means a newer
Request for the same scope/action replaces the old Request. `CANCELLED` requires
requester or operator authorization. `EXPIRED` is time-derived and fail-closed.

A Gate Request MUST include:

- `gate_request_id`, tenant, project, optional task, action and lock scope;
- requester actor and request authority;
- reason, question, allowed options and requested constraints;
- source PolicyDecision / RecoveryCycle / Situation / DecisionRecord refs;
- supporting Evidence refs and hashes;
- immutable `resume_context_ref` and hash;
- requested expiry and default timeout behavior;
- current scope versions and expected request version;
- idempotency key and payload hash.

A Gate Decision MUST include:

- `gate_decision_id` and parent request ID/version;
- approver actor, authorization reference and identity-provider assertion ref;
- selected option or structured clarification;
- decision reason and supporting Evidence refs;
- constraints accepted/modified;
- expiry of the approval itself;
- signature or signed assertion boundary reference;
- idempotency key and payload hash.

Identity-provider and signature verification are interface boundaries in P3-0:
the Human Gate authority consumes a validated identity assertion reference and
signature-verification result, but P3-0 does not select an IdP SDK.

### 4.3 Application and expiry

Human Gate MUST NOT directly update Project, Task, ExecutionRequest,
VerificationResult, Lease, Accounting or Worker authority. It may write a Gate
Decision fact. Control Plane MAY consume that fact inside a later guarded
Command.

Expired approval facts cannot authorize execution, queueing, resume or state
transition. Resume MUST reload the current Gate Decision, Project/Task versions,
Evidence validity, Policy, Risk, Budget and lock/lease state. Historical boolean
approval is never sufficient.

## 5. Project waiting and resume context

P3 MUST avoid Project state combination explosion. The authoritative model is:

```text
Project mainline state
+ typed project_waiting_record
+ immutable resume_context
```

### 5.1 Waiting triggers

The following triggers MAY create a waiting record:

| Waiting kind | Producer | Typical trigger |
| --- | --- | --- |
| `HUMAN` | Human Gate / Control Plane | Policy or exhaustion requires a Gate. |
| `RESOURCE` | Resource Accounting / Control Plane | Budget hard stop or reserved resource unavailable. |
| `DEPENDENCY` | Work Graph / Control Plane | External dependency, upstream artifact or Task prerequisite unavailable. |
| `RECOVERY` | Recovery Controller / Reconciler | Checkpoint/reconcile/quarantine/evidence workflow needs controlled repair. |

Task waiting is task-local runnable-state suppression. Project waiting pauses the
project mainline or a defined project write scope. A Task may wait without
putting the whole Project into waiting if the mainline can continue safely.

### 5.2 Resume context

Resume context is immutable and MUST include:

- project ID, mainline state and version at pause;
- waiting kind, waiting scope and blocked command;
- causation Event, Situation, Diagnosis, PlanningRun, CandidateAction,
  PolicyDecision, RiskAssessment, DecisionRecord and Reservation refs as
  applicable;
- Gate Request/Decision refs if human-gated;
- Evidence, Artifact, VerificationPlan and VerificationResult refs plus hashes;
- Budget snapshot ref and ResourceAccount versions;
- Work Graph snapshot/version and open Task refs;
- open ExecutionRequest, Lease, AgentRun and fencing token refs where relevant;
- replay cursor/checkpoint ref;
- created-at, expiry and content hash.

Resume does not restore by blindly writing the old state. It submits a guarded
resume Command that reloads current facts and re-executes the current Guard. If
Policy, Budget, Evidence or version has changed, resume either proceeds under
current authority or fails closed with a stable rejection code.

### 5.3 Conflict and terminal rules

- Stale Gate Decisions cannot resume a Project.
- Multiple concurrent Gates are aggregated by waiting scope. Resume is allowed
  only when all blocking Gates in that scope have current applied Decisions.
- Cancel has precedence over waiting and MAY close waiting records as cancelled.
- Terminal Projects (`ACCEPTED`, `FAILED`, `CANCELLED`) cannot resume.
- Waiting record supersession MUST preserve audit history and original context
  hash.

## 6. Checkpoint, Replay and Reconcile

Hermes remains:

```text
Authoritative State
+ Append-only Event Log
+ Transactional Outbox
+ Checkpoint / Replay / Reconcile
```

It is not full Event Sourcing. Replay MUST NOT unconditionally overwrite
authoritative Project, Task, Accounting, Lease, ExecutionRequest or Verification
state.

### 6.1 Checkpoint authority

Consumer checkpoints are partition/version scoped:

- stream name and partition key;
- last contiguous sequence;
- consumer group and consumer code version;
- schema version and checkpoint payload hash;
- read-model/projection snapshot ref;
- retention/replay window metadata;
- created/advanced by an authorized consumer or Reconciler Command.

Checkpoints MUST NOT advance across an Event gap. Duplicates are ignored through
Inbox identity. Unknown non-critical fields are preserved/ignored per schema
rules. Unknown critical schema/state transitions fail closed and park/DLQ the
Event with `EVENT_SCHEMA_UNSUPPORTED`.

### 6.2 Replay

Replay MAY rebuild:

- consumer state;
- read models;
- audit/explain projections;
- checkpoint candidates;
- recovery views after a snapshot.

Replay start and end boundaries MUST be explicit: checkpoint, snapshot schema
version, stream, partition, start sequence, end sequence and retention window.
If the retained window no longer covers the requested start, replay MUST fail
with `REPLAY_WINDOW_UNAVAILABLE`.

### 6.3 Reconcile

Reconcile compares authoritative state, Event Log, Outbox, Inbox, Checkpoint and
external facts. It detects at least:

- orphan Lease;
- unsettled usage;
- stale Reservation;
- missing Outbox publication;
- Event/outbox exists but consumer side effect missing;
- consumer effect exists but checkpoint not advanced;
- late/stale Worker Result;
- invalid Evidence reference;
- checkpoint corruption;
- partition gap;
- poison Event or unsupported schema.

Repair MUST be planned separately from execution. Dry-run explain produces an
auditable reconcile plan. Applying a plan submits guarded Commands; it MUST NOT
directly patch authority tables. Concurrent Reconcilers use expected plan
version and lock scope; stale plans fail with `RECONCILE_PLAN_STALE`.

### 6.4 P3-2 implementation boundary

P3-2 implements this section as a PostgreSQL authority overlay, not as full
Event Sourcing. The implemented model adds generation-scoped checkpoints,
checkpoint hashes, immutable checkpoint history, replay sessions/generations,
shadow projection rows, generation pointers, reconcile findings and immutable
plans.

Replay may create and activate a read-model generation pointer after verifying a
shadow projection digest. Replay may not overwrite Project, Task, Accounting,
Lease, Worker, Verification or Event Log authority. Reconcile observe/plan may
surface all supported finding kinds; apply is restricted to whitelisted semantic
repairs. The only mutating P3-2 repair currently implemented is
`ADVANCE_CHECKPOINT_IF_EFFECT_CONTIGUOUS`, and only when Inbox/effect continuity
proves the checkpoint can advance without skipping a gap.

Unsupported repairs remain `BLOCKED`/planned until the owning guarded Command is
implemented by a later slice. External irreversible side-effect replay is not
implemented.

## 7. CT-009, CT-010 and FI-12 contracts

### 7.1 CT-009 — Human Gate requires resume context

Preconditions:

- Policy or Recovery Controller has produced a fact requiring Human Gate.
- Project/Task/action scope versions are known.
- Caller attempts `human_gate.request`.

Actors:

- requester: Main Hermes, Recovery Controller or Control Plane;
- authority: Human Gate;
- forbidden approvers: requester self-subject, Worker, Scheduler, Planner,
  Verifier.

Expected success:

- Request is `REQUESTED` with valid immutable resume context and Event/Outbox
  `human_gate.requested`.

Expected rejection:

- missing/broken context: `GATE_RESUME_GUARD_FAILED`;
- stale request version: `GATE_REQUEST_STALE`;
- scope mismatch: `GATE_SCOPE_MISMATCH`;
- invalid Evidence: `GATE_EVIDENCE_INVALID`.

Concurrency and crash:

- duplicate idempotency key + same payload returns original CommandResult;
- same idempotency key + different payload conflicts through the generic command
  idempotency protocol;
- if crash occurs after Gate row but before Outbox, local transaction rollback
  leaves no open Gate;
- replay may rebuild the Gate read model but not open a missing Gate without the
  original committed Command/Event.

Authority boundary:

- no Project/Task state mutation occurs while opening the Gate.

### 7.2 CT-010 — Exhausted strategy Gate is complete

Preconditions:

- RecoveryCycle is `EXHAUSTED` or autonomous ladder cannot continue.
- Attempt ledger contains every attempted strategy, worker/template, outcome,
  evidence/result refs, remaining options and recommendation.

Command:

- `human_gate.request` with type `decision` or `exception`, causation
  `recovery.cycle_exhausted`.

Expected success:

- Gate Request includes attempts, strategies tried, agents/workers consulted,
  remaining options, recommendation, risks, exact question, supporting evidence,
  resume context and timeout behavior.
- Event/Outbox contains references and hashes, not secret values or raw logs.

Expected rejection:

- incomplete attempt ledger: `GATE_RESUME_GUARD_FAILED`;
- expired/superseded request on decision application:
  `GATE_DECISION_EXPIRED` or `GATE_DECISION_SUPERSEDED`;
- self approval: `GATE_SELF_APPROVAL_FORBIDDEN`.

### 7.3 FI-12 — Control Plane restart with checkpoint/replay/reconcile

FI-12 MUST be split into sub-scenarios:

| Sub-scenario | Expected behavior |
| --- | --- |
| FI-12A checkpoint damaged | Detect `CHECKPOINT_CORRUPT`, park checkpoint, rebuild candidate from last valid checkpoint and Event stream. |
| FI-12B checkpoint lost | Rebuild from retained snapshot/start cursor; fail `REPLAY_WINDOW_UNAVAILABLE` if unavailable. |
| FI-12C duplicate Event | Inbox uniqueness prevents duplicate effect; checkpoint remains contiguous. |
| FI-12D Event gap | Park later Events, reject checkpoint advance with `EVENT_GAP_DETECTED`. |
| FI-12E reconcile dry-run | Produce immutable plan and explain; no authority mutation. |
| FI-12F reconcile apply crash | Retried idempotent Commands complete or return previous result; no direct table patch. |
| FI-12G authority protection | Replay/reconcile never replaces newer Project/Task/Accounting/Lease state by fold. |

## 8. Quarantine operations

P2 minimal stale-payload admission stores immutable records. P3 adds operations:

```text
QUARANTINED
-> UNDER_REVIEW
-> DISCARDED
-> ADOPTION_REQUESTED
-> ADOPTED
-> REDRIVE_REQUESTED
-> REDRIVEN
-> EXPIRED
```

Payloads entering quarantine include stale fencing Results, wrong owner/run
payloads, schema-unsupported payloads, sandbox-violation envelopes, unverifiable
Artifact/Evidence candidates, duplicate terminal submissions and security
review candidates.

Every quarantine record MUST preserve:

- immutable original envelope hash;
- redacted safe summary;
- payload classification and retention deadline;
- request/run/lease/fencing/current-token refs;
- reviewer identity and authorization refs for operations;
- reason, Evidence refs, expected version and idempotency key;
- original causation and correlation IDs.

Adoption is never direct INSERT into normal authority. Adoption submits a new
guarded Command that re-evaluates current Policy, Lease, Fencing, versions,
Evidence validity and Project/Task Guards. A stale Result cannot be human-clicked
into Task `PASSED`. Redrive uses a new Command/idempotency identity while
preserving original causation. Discarded/expired records retain audit summaries.
Secret and Artifact bodies remain protected; only handles/hashes may enter
operational Events.

P3-3 implementation note: runtime operations are stored as an overlay on top of
P2 minimal quarantine. `execution_quarantine_records` remains the immutable
source of the original envelope/hash/fencing/run/request references.
`quarantine_current_states` is only the expected-version lifecycle pointer;
`quarantine_operations`, adoption requests and redrive requests are append-only
facts linked to CommandReceipt, Event Log and Outbox.

## 9. Evidence invalidation

Evidence invalidation is append-only and fail-closed.

The invalidation Command MUST include producer, reason, affected Evidence refs,
expected versions, payload hash, idempotency key and propagation scope.

Invalidation affects:

- Evidence current validity;
- VerificationResults that referenced the Evidence;
- Policy/Risk/Budget/Gate/Decision records that used it;
- affected Tasks and Projects through guarded current-state Commands.

Rules:

- Do not delete Evidence.
- Do not rewrite historical VerificationResults.
- Do not directly change a `PASSED` Task to `FAILED`.
- Historical Decisions preserve the Evidence hashes used at the time.
- New Decisions cannot use invalidated Evidence.
- Unknown impact fails closed with `REVERIFICATION_REQUIRED`.
- Human Gate approval depending on invalidated Evidence is not current and cannot
  authorize resume/execution.
- Concurrency uses expected Evidence and dependent-decision versions.

Already `PASSED` Tasks enter a current Guard workflow: mark current evidence
dependency stale, require re-verification, and let Control Plane decide whether
the Project enters `WAITING` or `RECOVERY` through explicit Commands.

P3-3 implementation note: `evidence_current_states` is the expected-version
validity pointer. `evidence_invalidation_records`,
`evidence_dependency_stale_records` and `reverification_requirements` are
append-only. Human Gate Decision insertion and Decision Application reject
invalidated Evidence with `GATE_EVIDENCE_INVALID`; no invalidation command
updates Evidence, VerificationResult or Task terminal state directly.

## 10. Decision Explain, audit and trace

Explain MUST be based on immutable snapshots or immutable references to versioned
facts captured at decision time. Query-time recomputation with new rules is
forbidden.

Explain records MUST answer:

- why a Situation was produced;
- why a Diagnosis was selected;
- candidate Actions and rejected alternatives;
- Policy denial/requires-human reasons;
- Risk score inputs and model version;
- Budget feasibility and Selection impact;
- WorkerTemplate/template revision selection;
- Gate reason and approver/rejector;
- Evidence and version refs;
- model/rule/compiler versions;
- Command/Event causation for each state change;
- ResourceReservation, Usage and Settlement;
- Lease/token/AgentRun/ExecutionResult provenance;
- quarantine review/adoption/redrive rationale.

All explain/audit records carry correlation ID, causation ID, trace ID,
project/task/decision/request/run refs, redaction class, retention policy and
authorization scope. Metrics are observability, not authority. Missing trace
links are reported as missing; they MUST NOT be fabricated.

## 11. Production execution boundary

P2 `contract-only/1.0` SandboxProfile is not a production sandbox.

P3-5 MUST choose at least one provable target:

- Docker adapter, if runtime flags, filesystem/network isolation, cgroup limits,
  timeout/kill and artifact collection can be proven in tests; or
- restricted Process adapter, only for local/trusted tasks where OS-level limits,
  working directory isolation, timeout/kill and secret-handle discipline can be
  proven.

P3-0 does not decide Docker versus Process priority. The decision gate is:

1. Can SandboxProfile compile to concrete runtime flags with target/version?
2. Can the adapter prove deny-by-default network/filesystem/secret behavior?
3. Can the Worker process manager spawn, heartbeat, timeout, kill and collect
   artifacts without bypassing fencing?
4. Can stdout/stderr be bounded and redacted?
5. Can usage be measured or marked untrusted with reconcile?
6. Can external side effects carry idempotency key, side-effect receipt and
   fencing token?
7. Can irreversible effects require Human Gate or fail closed?
8. Can adapter crash and stale Worker termination be reconciled?

External side effects are not authoritative state changes. They require
idempotency, receipt capture, causation, fencing token propagation and reconcile.
If a side effect exists without a matching receipt/checkpoint, Reconcile must
surface it and repair through guarded Commands.

## 12. Stable P3 rejection codes

### Human Gate

- `GATE_REQUEST_NOT_FOUND`
- `GATE_REQUEST_STALE`
- `GATE_DECISION_EXPIRED`
- `GATE_DECISION_SUPERSEDED`
- `GATE_APPROVER_UNAUTHORIZED`
- `GATE_SELF_APPROVAL_FORBIDDEN`
- `GATE_SCOPE_MISMATCH`
- `GATE_EVIDENCE_INVALID`
- `GATE_RESUME_GUARD_FAILED`

### Replay/Reconcile

- `CHECKPOINT_VERSION_CONFLICT`
- `CHECKPOINT_CORRUPT`
- `EVENT_GAP_DETECTED`
- `EVENT_SCHEMA_UNSUPPORTED`
- `REPLAY_WINDOW_UNAVAILABLE`
- `RECONCILE_PLAN_STALE`
- `RECONCILE_AUTHORITY_MISMATCH`

### Quarantine

- `QUARANTINE_RECORD_NOT_FOUND`
- `QUARANTINE_ALREADY_RESOLVED`
- `QUARANTINE_REVIEW_UNAUTHORIZED`
- `QUARANTINE_ADOPTION_GUARD_FAILED`
- `QUARANTINE_REDRIVE_CONFLICT`
- `QUARANTINE_RETENTION_EXPIRED`

### Evidence

- `EVIDENCE_ALREADY_INVALIDATED`
- `EVIDENCE_INVALIDATION_SCOPE_MISMATCH`
- `EVIDENCE_DEPENDENCY_STALE`
- `REVERIFICATION_REQUIRED`

## 13. P3 slice roadmap

| Slice | Dependency | Scope | Exit criteria |
| --- | --- | --- | --- |
| P3-1 Human Gate + Waiting/Resume | P2-5 | Gate Request/Decision authority, waiting records, immutable resume context, CT-009/010. | Gate lifecycle and resume fail closed under stale/expired/current guard changes. |
| P3-2 Checkpoint/Replay/Reconcile | P3-1 data contracts where waiting interacts with recovery | checkpoint authority, replay plan, gaps/DLQ, reconcile dry-run/apply, FI-12. | FI-12 sub-scenarios pass without authority overwrite. |
| P3-3 Quarantine + Evidence Invalidation | P3-2 reconcile facts | review/adoption/redrive/discard, Evidence invalidation and re-verification triggers. | stale/adopt/redrive cannot bypass current Guards or Verification. |
| P3-4 Decision Explain + Audit/Trace | P3-1 through P3-3 facts | immutable explain refs, audit query model, trace/retention/redaction. | Explain answers decision lineage from captured facts only. |
| P3-5 Production Execution Adapter | P2 execution contracts + P3 reconcile | one real sandbox target, process lifecycle, fencing propagation, side-effect receipt. | spawn/kill/timeout/usage/artifact/side-effect tests pass. |
| P3-6 End-to-End Hardening | P3-1 through P3-5 | Human approval, execution, quarantine, replay/reconcile, Evidence invalidation, audit explain. | PostgreSQL 14/16 full P3 matrix passes; P3 completion matrix can be marked PASS. |

## 14. Open questions

- Identity provider and signature-verification implementation.
- Multi-approver / dual-control threshold policy for high-risk production
  operations.
- Retention durations by tenant/data class.
- Production sandbox target priority: Docker first, restricted Process first, or
  both with explicit risk tiers.
- External artifact object store and secret-handle provider.
- Observability backend selection; OpenTelemetry remains a candidate, not a
  requirement.
