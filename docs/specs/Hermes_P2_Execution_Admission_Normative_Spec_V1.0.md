# Hermes P2 Execution Admission Normative Specification V1.0

**Status:** NORMATIVE DRAFT
**Version:** 1.0.0
**Phase:** P2-0 contract closure plus P2-1/P2-2 implementation notes
**Related:** [Runtime Normative Specification](Hermes_Runtime_Normative_Spec_V1.0.md), [Command/Event Protocol](Hermes_Command_Event_Protocol_V1.0.md), [Execution Lease Protocol](Hermes_Execution_Lease_Protocol_V1.0.md), [Conformance Tests](Hermes_Conformance_Test_Spec_V1.0.md), [ADR index](../../ARCHITECTURE_DECISIONS.md)

## 1. Scope and status

This specification closes the P2 execution contract before implementing
Scheduler, Lease or Worker lifecycle. P2-1 implements Capability Registry,
immutable Context Bundle and backend-neutral SandboxProfile Compiler authority
facts as freeze-object prerequisites. P2-2 implements `execution.prepare_request`
for admission, Reservation handoff, immutable ExecutionRequest creation and
durable PostgreSQL Queue enqueue. P2-2 does not implement claim/dequeue,
Scheduler, Lease, fencing, Worker lifecycle, Result admission or real sandbox
execution.

It specifies normative P2 requirements. Runtime implementation status is tracked
by slice in [`../P2_EXECUTION_ACCEPTANCE_MATRIX.md`](../P2_EXECUTION_ACCEPTANCE_MATRIX.md).

Already implemented by P0/P1:

- authoritative Project/Task state, Event Log, Outbox and CommandReceipt;
- Worker/Verifier identity separation and minimal AgentRun authority;
- ResourceReservation, UsageRecord and Settlement accounting primitives;
- Situation, Diagnosis, CandidateAction, PolicyDecision, RiskAssessment,
  ActionScore, DecisionRecord and SelectedAction refs;
- Selection-created ACTIVE ResourceReservations for non-zero selected actions.

Implemented by P2-1:

- versioned Capability schemas and immutable WorkerTemplate revisions;
- separate mutable WorkerTemplate availability/admission state;
- deterministic capability matching with exact revision and availability
  version evidence;
- immutable Context Bundle manifest refs/hashes with selector vocabulary and
  size limits;
- backend-neutral `contract-only/1.0` SandboxProfile compilation and
  conformance checking.

Implemented by P2-2:

- `execution.prepare_request` admission command with canonical payload hash and
  scoped idempotency;
- immutable `QUEUED` ExecutionRequest snapshot with exact IDs, versions and
  hashes for DecisionRecord, SelectedAction, PolicyDecision, RiskAssessment,
  ResourceReservation, Capability Match, WorkerTemplate revision, Context Bundle,
  SandboxProfile, VerificationPlan, Artifact inputs and lock intents;
- atomic P1 Reservation handoff through a unique binding row without second
  balance debit;
- durable enqueue-side PostgreSQL Queue item with deterministic read ordering;
- same-transaction `execution.request_prepared`, `execution.queued`, Outbox rows
  and APPLIED CommandReceipt;
- stable rejection receipts/audit without effective Request/Queue/Event/Outbox;
- FI-16 execution Request/Queue/Reservation coupling fault-injection coverage.

Implemented by P2-3:

- minimal Scheduler admission/registration with bounded holder identity;
- durable Queue claim over Scheduler current-state tables;
- PostgreSQL-clock Lease acquire, renew, expiry takeover and relinquish/requeue;
- monotonic per-ExecutionRequest fencing token allocation by PostgreSQL;
- current Lease validation primitive for later Result/Usage admission;
- actual execution lock ownership using the ADR-0045 scope vocabulary;
- same-transaction Lease/Queue/Request/Lock/Event/Outbox/Receipt authority
  changes;
- CT-002, P2-LOCK-001 and Scheduler/Lease parts of FI-10/FI-11.

P2 requirements specified here:

- execution admission;
- reservation handoff;
- ExecutionRequest preparation and queued semantics;
- action routing;
- WorkerTemplate, Context Bundle and SandboxProfile freeze points;
- AgentRun evolution, Lease, fencing and stale-result admission;
- lock scope vocabulary;
- CT/FI ownership across P2-1 through P2-5 and P3.

## 2. Normative conflict closure

P2-0 resolves these conflicts:

| Conflict | Resolution |
| --- | --- |
| Task `READY` was sometimes described as scheduler-ready. | `READY` means Task DAG dependencies are satisfied only. It is not execution-admissible. |
| P1 Selection creates ACTIVE Reservation, while the Execution Lease Protocol said PREPARING reserves resources. | P2 MUST bind and hand off the existing P1 Reservation. It MUST NOT create a second Reservation for the same Decision/Action/Preparation. |
| SelectedAction could be mistaken for queue item. | SelectedAction is immutable execution intent. Only an admitted ExecutionRequest may enter Queue. |
| Capability, Context and Sandbox checks were described near Scheduler acquisition. | They MUST complete and freeze before `QUEUED`; Scheduler only leases runnable admitted requests. |
| P0 AgentRun has identity but not execution lifecycle. | P2 evolves the same AgentRun model; it MUST NOT create a parallel Run model. |
| Quarantine is both P2 and P3. | P2 MUST minimally durably admit stale payloads to quarantine; P3 owns full operational adoption, redrive and retention workflows. |

## 3. Authority boundary

| Authority | Owns | Cannot do |
| --- | --- | --- |
| Control Plane | Execution admission, ExecutionRequest creation/preparation, cancellation, recovery commands | execute Worker code, produce Verification verdicts, bypass Policy/Risk/Budget |
| Selection Authority | DecisionRecord, SelectedAction refs, Selection-created ResourceReservation | create ExecutionRequest, Lease, AgentRun lifecycle or SandboxProfile |
| Resource Accounting | ResourceAccount, Reservation, UsageRecord, Settlement | select actions, authorize execution, decide Task PASS/FAIL |
| Capability Registry Authority | WorkerTemplate revisions and capability availability facts | select actions or weaken Policy |
| Context Authority | immutable Context Bundle manifest and hashes | include secret values or mutable implicit context |
| Sandbox Compiler Authority | compiled SandboxProfile and constraint translation evidence | weaken mandatory Policy/Risk constraints |
| Scheduler | atomic Lease acquire/renew/requeue within admitted queue | prepare request, decide business success, change Task state |
| Worker | execute one current leased request and submit Result/usage/artifact candidates | mutate authority, pass Task, settle current reservation without admission |
| Verification Engine | formal PASS/FAIL over exact Artifact hash and plan | execute implementation run, accept Worker token as verdict |
| Recovery Service | explicit reconcile/quarantine/adoption commands according to scope | silently adopt stale data or overwrite authority from replay |

## 4. READY is not execution-admissible

`Task READY` means only:

```text
all authoritative Task DEPENDS_ON edges are satisfied
and the Task DAG remains acyclic
and the READY calculation was committed by the graph authority
```

`READY` does not prove:

- Project or Task state currently allows execution;
- Policy still allows execution;
- Risk mitigations are satisfied;
- ResourceReservation exists;
- WorkerTemplate exists or is trusted;
- Context Bundle is frozen;
- SandboxProfile compiled successfully;
- lock scopes can be obtained;
- ExecutionRequest may be queued.

P2 MUST define execution-admissible through a separate admission result or through
ExecutionRequest preparation invariants. A Task state expansion is not required.

## 5. Execution Admission

### 5.1 Admission input

The admission command is specified as `execution.prepare_request`. Its canonical
payload MUST include:

- `command_id`, `idempotency_key`, actor, reason and expected version;
- Project ID and Task ID;
- DecisionRecord ID and selection version;
- SelectedAction ref and action content hash;
- PlanningRun ID and input hash;
- PolicyDecision ID, result and input hash;
- RiskAssessment ID, residual risk, required/available mitigations and input hash;
- ResourceReservation ID and account/version binding;
- required Artifact refs and exact hashes;
- current VerificationPlan ID/version;
- WorkerTemplate revision selector;
- Context selector and expected Context Bundle hash/version if retrying;
- Sandbox compiler version and expected SandboxProfile hash/version if retrying;
- lock scope declarations;
- retry/preparation policy version.

### 5.2 Admission checklist

Execution Admission MUST fail closed unless all checks pass:

| Check | Evidence required | Failure reason |
| --- | --- | --- |
| Task dependencies | current graph READY fact | `EXEC_ADMISSION_TASK_NOT_READY` |
| Project state | current Project state allows execution | `EXEC_ADMISSION_PROJECT_STATE_BLOCKED` |
| Task state | current Task state allows execution attempt | `EXEC_ADMISSION_TASK_STATE_BLOCKED` |
| Human Gate | no blocking open Gate for this action/scope | `EXEC_ADMISSION_HUMAN_GATE_BLOCKED` |
| Artifact inputs | all required inputs readable with exact hash | `EXEC_ADMISSION_ARTIFACT_MISMATCH` |
| VerificationPlan | current ACTIVE plan exists | `EXEC_ADMISSION_VERIFICATION_PLAN_MISSING` |
| Policy | current PolicyDecision is ALLOW and bound to action hash | `EXEC_ADMISSION_POLICY_NOT_ALLOW` |
| Risk | RiskAssessment current and mandatory mitigations verified | `EXEC_ADMISSION_RISK_UNSATISFIED` |
| Reservation | ACTIVE ResourceReservation bound to Decision/Action | `EXEC_ADMISSION_RESERVATION_INVALID` |
| WorkerTemplate | matching available trusted revision exists | `EXEC_ADMISSION_WORKER_TEMPLATE_UNAVAILABLE` |
| Action routing | selected action is worker-executable | `EXEC_ADMISSION_ACTION_ROUTE_UNSUPPORTED` |
| Context | immutable Context Bundle frozen | `EXEC_ADMISSION_CONTEXT_FREEZE_FAILED` |
| Sandbox | SandboxProfile compiled and tight enough | `EXEC_ADMISSION_SANDBOX_COMPILE_FAILED` |
| Lock scopes | required execution locks acquired or prepared in canonical order | `EXEC_ADMISSION_LOCK_CONFLICT` |
| Version freshness | expected versions match all current authorities | `EXEC_ADMISSION_VERSION_CONFLICT` |

### 5.3 Admission output

A successful admission transaction MUST atomically persist:

- ExecutionRequest in `PREPARING` then `QUEUED`, or an equivalent single
  transaction with all `QUEUED` invariants satisfied;
- immutable admission result/evidence refs;
- Reservation handoff binding;
- frozen WorkerTemplate revision ref;
- frozen Context Bundle manifest hash;
- frozen SandboxProfile hash and compiler version;
- lock scope set and acquisition/preparation facts;
- `execution.request_prepared` and `execution.queued` Events;
- Outbox messages for those Events;
- applied CommandReceipt.

If implementation splits `PREPARING` and `QUEUED` across commands, `PREPARING`
MUST be non-runnable and MUST have deterministic cleanup/retry behavior.

## 6. ExecutionRequest state machine

```text
PREPARING -> QUEUED -> LEASED -> RUNNING -> RESULT_SUBMITTED
          -> SUCCEEDED | FAILED | CANCELLED | TIMED_OUT

PREPARING -> PREPARATION_FAILED
QUEUED/LEASED/RUNNING -> CANCEL_REQUESTED -> CANCELLED | TIMED_OUT
LEASED/RUNNING -> QUEUED        (expired lease and retry policy allows)
RESULT_SUBMITTED -> QUARANTINED (stale token or invalid identity)
```

`SUCCEEDED` means the execution adapter completed its protocol and submitted
admissible artifacts/results. It does not mean Task `PASSED`.

| State | Runnable? | Meaning |
| --- | --- | --- |
| `PREPARING` | No | Admission transaction is assembling and validating execution prerequisites. |
| `PREPARATION_FAILED` | No | Admission failed after a durable preparation record; no Scheduler may lease it. |
| `QUEUED` | Yes | All admission checks passed and inputs are frozen. Scheduler may atomically acquire Lease. |
| `LEASED` | Owned | Scheduler/Worker owns current fencing token but Worker has not acknowledged RUNNING or implementation chooses to combine states. |
| `RUNNING` | Owned | Worker is executing current token. |
| `RESULT_SUBMITTED` | No new lease | Result payload is durably received and awaits admission/finalization. |
| `SUCCEEDED` | Terminal | Execution protocol succeeded; Verification still determines Task PASS/FAIL. |
| `FAILED` | Terminal or retryable by policy | Execution protocol failed; business failure returns to Situation/Diagnosis/Planner. |
| `CANCEL_REQUESTED` | Owned or pending expiry | Cancellation has been requested and current token is known. |
| `CANCELLED` | Terminal | Cancellation completed and reservation disposition is recorded. |
| `TIMED_OUT` | Terminal or retryable by policy | Lease/execution timeout exceeded policy. |
| `QUARANTINED` | Terminal for payload, not request necessarily | Stale or invalid payload was stored for audit without authority mutation. |

## 7. QUEUED invariants

An ExecutionRequest MUST NOT enter `QUEUED` unless it binds:

- Project and Task;
- DecisionRecord and SelectedAction;
- PolicyDecision and RiskAssessment;
- ResourceReservation;
- WorkerTemplate revision;
- Context Bundle hash/version;
- SandboxProfile hash/compiler version;
- VerificationPlan version;
- Artifact refs and hashes;
- normalized lock scopes;
- retry policy;
- command, idempotency and expected version metadata.

Unknown, disabled or unroutable action types MUST NOT enter `QUEUED`.

## 8. Reservation handoff

P1 Selection creates ACTIVE ResourceReservation for every non-zero selected
action. P2 handoff binds that existing Reservation to the ExecutionRequest.

Rules:

1. The same DecisionRecord/SelectedAction/Preparation MUST NOT create a second
   Reservation.
2. Handoff MUST verify Reservation owner, action, amount, account, version,
   currency and ACTIVE status.
3. Handoff and ExecutionRequest `QUEUED` transition MUST commit in the same
   local transaction.
4. If admission fails before `QUEUED`, the outcome MUST be deterministic:
   release if the selected execution intent cannot be retried without replan;
   retain only if the same preparation can retry idempotently and has a bounded
   expiry/reconcile policy.
5. Cancellation and permanent execution failure MUST settle known usage and
   release unused reservation.
6. Transient retry under the same ExecutionRequest retains the same Reservation
   and increments fencing token on lease re-grant.
7. Strategy switch or new selected action requires a new Decision/SelectedAction
   and MUST NOT mutate the old Reservation into a different business intent.

FI-16 and FI-17 are not fully closed by P1. P1 covers Accounting primitives; P2
must close ExecutionRequest coupling; P3 closes full reconcile operations.

## 9. Action routing

Action routing is independent from Planner and Selection. Planner may propose an
action, Policy may allow it, and Selection may select it, but P2 admission must
still route it to an implemented authority.

| Route | Examples | P2 behavior |
| --- | --- | --- |
| Worker-executable | `diagnose`, `run_deeper_test`, bounded `repair`, `retry` | May create ExecutionRequest only after all admission checks pass. |
| Control Plane internal | `pause`, selected state/control actions | Must be handled by Control Plane command, not Worker queue. |
| Human Gate | `request_resource`, `human_gate`, approval-needed production changes | Must route to Human Gate authority; P2 worker queue rejects. |
| Recovery/Reconcile | orphan release, stale adoption, settlement repair | Must route to recovery service command. |
| Unsupported | disabled/unknown action type, missing WorkerTemplate | Fail closed with `EXEC_ADMISSION_ACTION_ROUTE_UNSUPPORTED`. |

P2-0 does not implement routing code; it specifies the contract for P2-1/P2-2.

## 10. Capability, Context and Sandbox freeze

Before `QUEUED`, P2 MUST freeze:

- WorkerTemplate revision and capability match evidence;
- immutable Context Bundle manifest and hash;
- compiled SandboxProfile hash, compiler version and constraint mapping evidence.

Capability matching MUST be deterministic and replayable. WorkerTemplate metadata
MUST include at least capabilities, revision, availability, trust level, allowed
tools, adapter type, sandbox support and deprecation/disabled state.

Context Bundle MUST use a minimal selector and immutable manifest. It may contain
secret handles but MUST NOT contain secret values in Event, Context, Artifact,
Outbox, CommandReceipt or logs.

SandboxProfile Compiler MUST fail closed when a mandatory Policy/Risk constraint
cannot be represented. The compiled profile may only preserve or tighten
constraints; it MUST NOT widen network, filesystem, environment, secret,
production, tool or external API permissions.

P2-1 fixes the first trust taxonomy, selector vocabulary and compiler target in
[ADR-0048](../adr/ADR-0048-p2-capability-context-sandbox-minimums.md). The
current compiler target is `contract-only/1.0`; it produces an auditable
SandboxProfile contract but does not start Docker, Process or Kubernetes
isolation. Lock scopes are normalized into capability requirements and sandbox
profiles, but canonical lock acquisition remains P2-2/P2-3.

Registry or Policy updates after `QUEUED`:

- do not silently mutate the frozen request;
- may prevent lease acquisition or renew only through explicit invalidation
  policy;
- require audit Event/Outbox if they cancel, invalidate or requeue a request.

## 11. AgentRun P2 evolution

P2 MUST extend the existing P0 AgentRun model instead of creating another run
table/model.

Required relationships:

```text
ExecutionRequest 1 -> 0..N attempts
attempt 1 -> 1 AgentRun(kind=WORKER)
AgentRun 1 -> current Lease owner/token while leased/running
AgentRun 1 -> Result payload candidates
AgentRun 1 -> UsageRecord samples
AgentRun 1 -> Artifact/Evidence candidates
CompletionClaim -> AgentRun + ExecutionRequest + token
VerificationResult -> independent AgentRun(kind=VERIFIER)
```

AgentRun admission/start/heartbeat/finish/invalidate/expire/quarantine MUST be
authority commands with scoped actor permissions. Worker identity may submit
narrow heartbeat/result/usage/artifact candidate commands only when request,
lease owner, fencing token, run identity and expected versions match.

### 11.1 P2-4 implementation checkpoint

Migration `0016_worker_lifecycle_result_admission.sql` implements the P2-4 core
by extending the existing P0 `agent_runs` model. It does not introduce a second
ExecutionRun table. A current WORKER AgentRun binds exactly one
ExecutionRequest, execution attempt, Lease, Lease version, fencing token,
WorkerTemplate revision/content hash, Context Bundle/hash, SandboxProfile/hash
and ResourceReservation.

`execution.start_run` owns the `LEASED -> RUNNING` transition. It requires a
current ACTIVE Lease, PostgreSQL-clock validity, matching Scheduler holder,
matching Worker identity and matching frozen request scope. Competing Workers
for the same request/attempt are serialized by PostgreSQL constraints and locks.
Lease takeover, expiry or supersession invalidates the old Worker Run; late
payloads from that old Run cannot regain authority.

## 12. Lease, fencing and stale result

Lease acquisition MUST be one PostgreSQL atomic conditional operation or
row-lock transaction. The PostgreSQL authority clock decides expiry.

Every grant or re-grant increments a monotonic fencing token. Heartbeat/renew
for the current owner keeps the token. Every Worker-originating authority write
MUST carry:

- ExecutionRequest ID;
- AgentRun ID;
- attempt ID;
- lease owner identity;
- fencing token;
- request version;
- lease version;
- payload hash;
- idempotency key.

These writes include Result, UsageRecord sample, Artifact candidate, Evidence
candidate and CompletionClaim.

Old token, wrong owner, wrong run, stale request version or mismatched payload
MUST NOT mutate current authority. Stale payload MUST be stored in durable
quarantine with audit metadata sufficient for later P3 review.

P2 implements minimal quarantine admission. P3 owns quarantine retention,
operator review, adoption, redrive and reconcile workflows.

In P2-4, Worker-originating Artifact Candidate, Evidence Candidate, Usage sample
and terminal Result submissions share one current-token validation path. A
current terminal Result may create an Artifact and CompletionClaim and may settle
or release the bound ResourceReservation, but it MUST NOT create a
VerificationResult and MUST NOT mark Task `PASSED` or `FAILED`. Stale or invalid
payloads are appended to minimal immutable quarantine with Event/Outbox in the
same transaction and do not mutate current execution, artifact, usage,
settlement, task or verification authority.

## 13. Lock scopes

P2 lock scopes use this minimum vocabulary:

| Scope kind | Example canonical ID | Protects |
| --- | --- | --- |
| `repository` | `repository:repo-main` | whole repository mutation |
| `workspace` | `workspace:proj_001:default` | workspace-level filesystem/process operations |
| `branch_ref` | `branch_ref:repo-main:refs/heads/main` | branch/ref mutation |
| `artifact_namespace` | `artifact_namespace:proj_001:build` | artifact name/current-pointer namespace |
| `external_environment` | `external_environment:staging` | shared external environment/API side effects |
| `deployment_target` | `deployment_target:prod:service-a` | deployment or production target |

Canonical form:

```text
<kind>:<normalized stable identifier>
```

Rules:

- unknown critical lock kind fails closed;
- lock acquisition order is lexicographic by `(kind_order, canonical_id)`;
- every request stores normalized lock scopes before `QUEUED`;
- Scheduler Lease does not replace domain locks;
- lock conflict decisions must be deterministic and auditable.

Default kind order:

```text
repository
workspace
branch_ref
artifact_namespace
external_environment
deployment_target
```

P2-3 closes the actual lock acquisition part of this contract. P2-2 immutable
Request snapshots retain the normalized lock intents and lock hash; P2-3
Scheduler functions acquire current lock ownership in PostgreSQL and bind each
active lock to `lease_id + fencing_token`. Conflicting active scopes fail closed
or are skipped during best-effort Queue scanning; non-conflicting requests may be
leased by different Scheduler holders.

### 13.1 P2-3 Scheduler/Lease boundary

P2-3 current state is intentionally separate from the immutable P2-2
`execution_requests` and `execution_queue_items` snapshots. The mutable
Scheduler authority owns:

- `QUEUED -> LEASED`;
- `LEASED -> QUEUED` for relinquish/requeue;
- expired `LEASED -> LEASED` takeover through a new Lease grant and larger token.

It does not own `RUNNING`, Result submission, UsageRecord, CompletionClaim,
Artifact/Evidence Candidate, VerificationResult or Task `PASSED/FAILED`.

The P2-3 default profile is `p2-default/1` with integer millisecond limits:
30000 initial TTL, 10000 renew interval, 30000 max extension, 300000 max
lifetime, immediate takeover after DB-clock expiry, zero requeue backoff and
single-item acquisition.

Fencing tokens are PostgreSQL-assigned and monotonic per ExecutionRequest.
Renew keeps the token; takeover and requeue/reacquire allocate a larger token.
`validate_current_lease` proves current holder/token/version for later slices
but MUST NOT be used in P2-3 to accept Worker Result payloads.

## 14. Idempotency, expected version and concurrency

Every P2 authority command MUST follow the Command/Event Protocol:

- idempotency scope is command-specific and documented;
- same key/same canonical payload returns original result;
- same key/different payload returns stable conflict;
- expected version mismatch returns a version conflict and writes no authority
  mutation except optional rejection audit;
- concurrent contenders must be resolved by PostgreSQL unique constraints,
  conditional updates or row locks;
- external sandbox/adapter work MUST NOT occur inside authority transactions.

## 15. PostgreSQL transaction boundary

Each authority-changing command MUST atomically commit:

```text
authority rows
Event Log row(s)
Outbox row(s)
CommandReceipt result
```

Examples:

- Admission success commits ExecutionRequest, admission evidence,
  Reservation handoff, Context/Sandbox refs, lock refs, Events and Outbox.
- Lease acquire commits current owner/token/version and `execution.leased`.
- Result admission commits payload disposition, candidate artifacts/usage refs or
  quarantine, Events and Outbox.

No HTTP call, Worker process spawn, sandbox execution, broker publish, or
external tool call may be part of the database transaction.

## 16. Event and Outbox rules

Minimum P2 Events:

| Event | Producer | Slice |
| --- | --- | --- |
| `execution.request_prepared` | Control Plane | P2-2 |
| `execution.queued` | Control Plane | P2-2 |
| `execution.preparation_failed` | Control Plane | P2-2 |
| `execution.leased` | Scheduler | P2-3 |
| `execution.heartbeat_recorded` | Scheduler/Worker narrow command | P2-3/P2-4 |
| `execution.lease_renewed` | Scheduler | P2-3 |
| `execution.running` | Scheduler/Worker narrow command | P2-4 |
| `execution.result_submitted` | Worker narrow command | P2-4 |
| `execution.result_quarantined` | Control Plane/Result admission | P2-4 minimal, P3 full |
| `execution.succeeded` | Control Plane/Result admission | P2-4 |
| `execution.failed` | Control Plane/Result admission | P2-4 |
| `execution.cancel_requested` | Control Plane | P2-4/P3 |
| `execution.cancelled` | Control Plane/Recovery | P2-4/P3 |
| `execution.timed_out` | Scheduler/Recovery | P2-4/P3 |

Every Event MUST have an Outbox row in the same transaction. Event payloads carry
refs and hashes, not secret values or full logs.

## 17. Crash points

P2 test design MUST include crash points at least:

- after CommandReceipt placeholder;
- after admission evidence, before Reservation handoff;
- after Reservation handoff, before ExecutionRequest `QUEUED`;
- after Context Bundle creation, before SandboxProfile creation;
- after SandboxProfile creation, before `execution.queued` Event;
- after Event, before Outbox;
- after Outbox, before CommandReceipt finalization;
- after Lease acquire update, before Event;
- after Result payload durable receipt, before quarantine/admission disposition;
- after usage sample receipt, before settlement;
- after settlement, before release remainder;
- after commit, before response.

Pre-commit failures must roll back all authority changes in the transaction.
Post-commit retries must return the durable result or proceed by explicit
reconcile command.

## 18. Retry classification

| Category | Same ExecutionRequest? | Reservation handling | Required output |
| --- | --- | --- | --- |
| Adapter startup transient | Yes, if retry budget remains | retain | new Lease token on re-grant |
| Worker crash before result | Yes, if retry policy allows | retain until retry/timeout decision | expired lease and regrant Event |
| Capability temporarily unavailable | Maybe, if frozen template still valid and retry policy allows | retain bounded or release on preparation failure | `execution.preparation_failed` or retry |
| Sandbox compile failure from unsupported mandatory constraint | No | release unless a new compatible selection is prepared | fail closed, Situation/Feedback |
| Business/test failure | No silent retry | settle/release then Feedback/Situation/Diagnosis/Planner/RecoveryAttempt | execution failed + structured feedback + bounded recovery ledger |
| Cancellation | No | settle known usage, release remainder | cancelled/timed_out |
| Strategy switch/replan | New Decision/Action | old Reservation settled/released; new P1/P2 chain | new Decision/ExecutionRequest |

## 19. Replay and audit fields

ExecutionRequest and related audit records MUST preserve:

- request ID/version/state;
- project/task IDs;
- DecisionRecord/SelectedAction refs;
- Policy/Risk/Reservation refs;
- WorkerTemplate revision;
- Context Bundle hash;
- SandboxProfile hash/compiler version;
- lock scopes;
- attempts and AgentRun refs;
- lease owner/token/version history;
- command/idempotency refs;
- artifact/evidence candidate hashes;
- usage sample IDs and settlement refs;
- event IDs/outbox IDs;
- rejection/quarantine reason codes.

## 20. P2/P3 slice ownership

| Slice | Owns | Does not own |
| --- | --- | --- |
| P2-1 | Capability Registry, WorkerTemplate, Context Bundle, SandboxProfile contract and freeze tests | ExecutionRequest queue or Worker execution |
| P2-2 | Execution Admission, Reservation handoff, ExecutionRequest preparation and durable Queue | Lease competition or result admission |
| P2-3 | Scheduler, atomic Lease, fencing token, heartbeat, renew and takeover | Artifact/Usage final admission |
| P2-4 | AgentRun execution lifecycle, Worker result/usage/artifact candidate admission, minimal quarantine | full reconcile/adoption operations |
| P2-5 | Feedback emission from execution outcomes, deterministic failure taxonomy, RecoveryCycle/Attempt ledger, bounded retry/repair/switch-worker/collaboration/replan protocol and loop entry back through Situation/Diagnosis/Planner | Human Gate UX, full replay/reconcile, quarantine adoption/redrive, production Worker process manager |
| P3 | Human Gate, checkpoint/replay/reconcile operations, full quarantine retention/adoption/redrive, evidence invalidation workflows | P2 minimal execution safety |

P3-0 specifies the P3 side of this boundary in
[`Hermes_P3_Operational_Governance_Normative_Spec_V1.0.md`](Hermes_P3_Operational_Governance_Normative_Spec_V1.0.md)
and [`P3_OPERATIONAL_GOVERNANCE_ACCEPTANCE_MATRIX.md`](../P3_OPERATIONAL_GOVERNANCE_ACCEPTANCE_MATRIX.md).
It is documentation-only and does not add runtime code, migrations or tests.

### 20.1 P2-5 implemented recovery boundary

P2-5 Recovery Controller MAY emit structured Feedback only from a failed P2-4
`ExecutionResult`. It MUST NOT emit Feedback from `SUCCEEDED` execution results
and MUST NOT retry business/test failures inside the Scheduler path.

Recovery Controller owns `execution_feedback_records`, `recovery_cycles`,
`recovery_attempts` and minimal collaboration request records. It does not own
Task verdict authority, Verification authority, Worker result authority,
Accounting settlement authority or Queue/Lease authority.

Each autonomous RecoveryCycle MUST have a bounded `max_attempts`. When attempts
are exhausted, P2-5 records a blocked `human_gate` attempt and marks the cycle
`EXHAUSTED`; P3 owns the actual Human Gate lifecycle and resume context.

RecoveryAttempt completion MAY link to a later ExecutionRequest, ExecutionResult
and VerificationResult, but those links are audit facts only. Task `PASSED` or
`FAILED` still requires an authoritative VerificationResult and Control Plane
verified transition.

## 21. CT/FI ownership

| Scenario | Closure owner | Notes |
| --- | --- | --- |
| CT-002 | P2-3 | atomic scheduler lease competition |
| CT-003 core | P2-4 | stale token rejected and durably quarantined |
| CT-003 full | P3 | operational quarantine review/adoption/redrive |
| FI-09 | P2-4 core, P3 full | same stale-result boundary as CT-003 |
| FI-10 | P2-3/P2-4 | heartbeat loss, regrant and stale old operations |
| FI-11 | P2-3 | scheduler crash while holding lease |
| FI-16 execution coupling | P2-2 | admission/request creation must not leak reservation |
| FI-17 run/settlement coupling | P2-4 core, P3 full reconcile | P1 accounting primitives are already implemented |
| CT-009 | P3 | Human Gate resume context |
| CT-010 | P3 | exhaustion Gate completeness |
| FI-12 | P3 | checkpoint/replay/reconcile restart |

## 22. Open questions

- exact ExecutionRequest table schema and index set;
- lock timeout profiles per action route;
- lease TTL and heartbeat interval profiles;
- external side-effect idempotency requirements per tool adapter;
- quarantine retention duration and adoption authority workflow.
