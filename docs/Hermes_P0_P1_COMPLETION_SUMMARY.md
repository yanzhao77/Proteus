# Hermes Runtime P0–P1 Completion Summary

Date: 2026-08-13

Version branch target: `codex/hermes-p0-p1-complete`

Code baseline before this summary: `1b07213 feat: complete Hermes P1 authority chain`

## 1. Executive summary

Hermes Runtime has completed the planned P0 and P1 implementation scope for the
V1.2 authority-first runtime. The current codebase now contains a working,
tested runtime core that can safely move from verified worker output and project
state authority through the full P1 decision chain:

```text
CompletionClaim / Verification / Project State
-> Event Log / Transactional Outbox / CommandReceipt
-> Resource Accounting
-> Situation
-> Diagnosis
-> Candidate Planning
-> PolicyDecision
-> RiskAssessment
-> Budget Feasibility
-> ActionScore
-> Action Selection
-> DecisionRecord
-> ResourceReservation
```

The system intentionally stops at selected execution intent with required
resources reserved. It does not yet create `ExecutionRequest`, run Scheduler or
Lease/Fencing, assign Workers, compile SandboxProfile, execute AgentRuns, or
apply Human Gate lifecycle.

## 2. Original target

The P0–P1 objective was not to build a generic CRUD service or API surface. The
target was to establish the runtime authority boundaries needed before any
clustered execution layer can be trusted:

1. state must be changed only through semantic authority commands;
2. every authoritative write must commit with Event Log, Outbox and
   CommandReceipt in one local PostgreSQL transaction;
3. Worker self-report must never directly pass tasks;
4. Verification must be independent from Worker execution;
5. resource accounting must reserve, use, settle and report budget status through
   authoritative, versioned PostgreSQL state;
6. P1 planning and selection must respect the chain
   Situation -> Diagnosis -> CandidateActions -> Policy -> Risk -> Budget ->
   Score -> Selection -> Reservation;
7. denied, stale, unauthenticated or over-budget actions must fail closed;
8. historical records must be immutable, with current pointers kept separate
   from authoritative audit history.

## 3. Current status

P0 and P1 are complete for the committed MVP runtime core.

The current repository includes:

- P0 authority foundation and command/event protocols;
- PostgreSQL-backed authority stores;
- migration chain through `0012_action_selection.sql`;
- dedicated owner/runtime database roles for each authority boundary;
- P0 and P1 domain/application/infrastructure modules;
- acceptance matrices for all P1 slices;
- ADR coverage through ADR-0041;
- real PostgreSQL 14 and PostgreSQL 16 full-suite validation.

## 4. P0 completed scope

P0 established the runtime foundation:

- architecture decisions and authority boundary organization;
- PostgreSQL as the MVP authority and concurrency point;
- authoritative state plus append-only Event Log;
- Transactional Outbox in the same transaction as state changes;
- scoped idempotency and duplicate command semantics;
- optimistic concurrency with expected versions;
- Project state machine and fail-closed guard facts;
- Task graph updates and authoritative READY calculation;
- CompletionClaim boundary where Worker cannot self-pass a Task;
- VerificationResult boundary where verifier output does not directly mutate
  Task state;
- independent Worker and Verifier AgentRun identity/context;
- Control Plane guarded PASS/FAIL transitions;
- Event delivery relay, consumer inbox, partition-contiguous checkpointing, DLQ
  and redrive mechanics;
- PostgreSQL permissions and security-definer hardening.

Representative ADRs: ADR-0004 through ADR-0031.

Representative migrations: `0001` through `0006`, plus later hardening carried
forward by P1.

## 5. P1 completed scope

P1 completed the pre-execution decision chain.

### 5.1 Resource Accounting

Implemented:

- twelve V1.2 resource dimensions;
- integer limits, consumed and reserved balances;
- atomic multi-dimensional Reservation with expected account version;
- immutable UsageRecord and exactly-once Settlement/release;
- threshold status and HARD_STOP handling;
- authoritative Project Budget Fact bridge;
- Accounting permission boundary and tests.

Key files:

- `hermes-runtime/migrations/0007_resource_accounting.sql`
- `hermes-runtime/src/hermes_runtime/domain/resource_accounting.py`
- `hermes-runtime/src/hermes_runtime/application/accounting.py`
- `hermes-runtime/src/hermes_runtime/infrastructure/postgres_accounting.py`

### 5.2 Situation Analyzer

Implemented:

- immutable sequence-bounded AnalysisContext;
- deterministic situation classification;
- canonical fingerprinting;
- guarded create/update/supersede/resolve lifecycle;
- Situation authority runtime role;
- contiguous checkpoint and Event/Outbox integration.

Key files:

- `hermes-runtime/migrations/0008_situation_analyzer.sql`
- `hermes-runtime/src/hermes_runtime/domain/situation.py`
- `hermes-runtime/src/hermes_runtime/application/situations.py`
- `hermes-runtime/src/hermes_runtime/infrastructure/postgres_situation.py`

### 5.3 Diagnosis Engine

Implemented:

- deterministic `diagnosis-rules/1.0`;
- normalized verification findings and evidence refs;
- immutable Diagnosis records and current pointer;
- `UNKNOWN` diagnosis with `root_cause = NULL` for insufficient or
  contradictory evidence;
- exact binding to Situation version and AnalysisContext hash.

Key files:

- `hermes-runtime/migrations/0009_diagnosis_engine.sql`
- `hermes-runtime/src/hermes_runtime/domain/diagnosis.py`
- `hermes-runtime/src/hermes_runtime/application/diagnoses.py`
- `hermes-runtime/src/hermes_runtime/infrastructure/postgres_diagnosis.py`

### 5.4 Candidate Action Planner

Implemented:

- deterministic `action-registry/1.0`, `planner-rules/1.0` and
  `resource-estimator/1.0`;
- immutable PlanningRun and CandidateActions;
- exact binding to current OPEN Situation, frozen AnalysisContext and current
  Diagnosis where required;
- CandidateAction as proposal only, not authorization, reservation or execution;
- fail-closed handling for unknown and disabled action types.

Key files:

- `hermes-runtime/migrations/0010_candidate_action_planner.sql`
- `hermes-runtime/src/hermes_runtime/domain/planner.py`
- `hermes-runtime/src/hermes_runtime/application/planning.py`
- `hermes-runtime/src/hermes_runtime/infrastructure/postgres_planner.py`

### 5.5 Policy and Risk

Implemented:

- deterministic `policy-bundle/1.0`;
- Policy outputs limited to `ALLOW`, `DENY`, `REQUIRE_HUMAN`;
- DENY and REQUIRE_HUMAN precedence;
- typed Policy constraints that only tighten;
- deterministic `risk-model/1.0`;
- RiskAssessment as risk fact only, never authorization;
- verified mitigation handling;
- Policy/Risk immutability, current pointers, permissions and idempotency.

Key files:

- `hermes-runtime/migrations/0011_policy_risk_engines.sql`
- `hermes-runtime/src/hermes_runtime/domain/policy.py`
- `hermes-runtime/src/hermes_runtime/domain/risk.py`
- `hermes-runtime/src/hermes_runtime/application/policies.py`
- `hermes-runtime/src/hermes_runtime/application/risks.py`
- `hermes-runtime/src/hermes_runtime/infrastructure/postgres_policy.py`
- `hermes-runtime/src/hermes_runtime/infrastructure/postgres_risk.py`

### 5.6 Action Selection and Reservation

Implemented:

- explicit `action_selection` actor and `SelectActions` command;
- command shape that excludes caller-provided score, selected refs, Policy/Risk
  decisions and `budget_ok`;
- fixed filter order: Policy -> Risk constraints -> Budget -> Score -> Conflict
  -> Select;
- authoritative ResourceAccount locking and budget feasibility;
- deterministic integer ActionScore with eight dimensions;
- conservative `DEFAULT_NO_HISTORY` until a real historical-success authority
  exists;
- deterministic conflict rules and max parallel selection;
- immutable DecisionRecord, candidate dispositions, ActionScores and selected
  refs;
- atomic Selection/Reservation bridge;
- `budget.reserved` and `decision.recorded` events in the same transaction;
- CT-004 closure: Policy DENY cannot be overridden by high score.

Key files:

- `hermes-runtime/migrations/0012_action_selection.sql`
- `hermes-runtime/src/hermes_runtime/domain/selection.py`
- `hermes-runtime/src/hermes_runtime/application/selections.py`
- `hermes-runtime/src/hermes_runtime/infrastructure/postgres_selection.py`

## 6. Documentation completed

The repository now includes:

- `ARCHITECTURE_DECISIONS.md` with ADR-0001 through ADR-0041 indexed;
- ADR-0032 through ADR-0041 for P1 authority decisions;
- P1 acceptance matrices:
  - `docs/P1_RESOURCE_ACCOUNTING_ACCEPTANCE_MATRIX.md`
  - `docs/P1_SITUATION_ANALYZER_ACCEPTANCE_MATRIX.md`
  - `docs/P1_DIAGNOSIS_ENGINE_ACCEPTANCE_MATRIX.md`
  - `docs/P1_CANDIDATE_ACTION_PLANNER_ACCEPTANCE_MATRIX.md`
  - `docs/P1_POLICY_RISK_ACCEPTANCE_MATRIX.md`
  - `docs/P1_ACTION_SELECTION_ACCEPTANCE_MATRIX.md`
- updated `hermes-runtime/README.md` describing the complete P0–P1 authority
  chain and explicit non-goals.

## 7. Test and validation evidence

Before the P0–P1 implementation commit, the following validation passed:

```text
No-DB unittest discovery:
Ran 275 tests
OK (skipped=182)
```

> Note: the per-slice acceptance matrices (Situation 175, Diagnosis 200, Planner
> 226, Policy/Risk 256, Selection 275) record point-in-time regressions as each
> slice landed; the final P0–P1 suite count is 275. Later phases grow the same
> suite: P3-1 369, P4 463, P5 497 (see the respective completion summaries).

```text
PostgreSQL 14 full suite:
Ran 275 tests
OK

PostgreSQL 16 full suite:
Ran 275 tests
OK

compileall:
passed

git diff --check:
passed
```

The PostgreSQL suites use real database connections and cover authority
transactions, concurrency, permissions, immutable records, idempotency and fault
injection across P0 and P1.

## 8. Current authority chain

The runtime now has a complete pre-execution authority chain:

```text
Worker output
-> CompletionClaim
-> VerificationResult
-> Control Plane PASS/FAIL
-> Event/Outbox/Receipt
-> ResourceAccount Budget Fact
-> AnalysisContext
-> Situation
-> Diagnosis
-> PlanningRun / CandidateAction
-> PolicyDecision
-> RiskAssessment
-> Budget Feasibility
-> ActionScore
-> DecisionRecord
-> ResourceReservation
```

This is the correct stopping point before P2/P3 execution infrastructure.

## 9. Explicit boundaries still preserved

The following separations are preserved:

- Worker report is not Verification verdict.
- VerificationResult is not Task state mutation.
- PolicyDecision is not RiskAssessment.
- RiskAssessment is not Authorization.
- Policy `ALLOW` is not Selection.
- ActionScore is not Authorization.
- Budget feasible is not Reserved.
- SelectedAction is not ExecutionRequest.
- DecisionRecord is not mutable workflow state.
- ResourceEstimate is not Reservation.

## 10. Not implemented by design

The following are deliberately outside completed P0–P1 scope:

- Human Gate lifecycle and Gate Answer application;
- ExecutionRequest;
- Queue and Scheduler;
- Lease, fencing token and heartbeat;
- Worker selection and dynamic Worker lifecycle;
- SandboxProfile Compiler;
- dynamic Capability Registry;
- real AgentRun execution coupling;
- Usage/Settlement coupled to actual run completion;
- FastAPI or public Web API;
- Kafka, Redis, Kubernetes or Raft;
- LLM-based Planner, Policy, Risk or Selection;
- complete Event Sourcing.

These are future P2/P3 concerns, not hidden gaps in P0–P1 completion.

## 11. Version branch purpose

The version branch `codex/hermes-p0-p1-complete` is intended to preserve the
project at the point where P0 and P1 are complete. It should point at the commit
that includes this summary document and the already committed P0–P1 runtime
implementation.

This branch is a local project snapshot unless it is explicitly pushed later.

## 12. Recommended next phase

The next natural phase is P2 planning, but P2 should begin from a clean decision
record rather than by extending Selection ad hoc. Before implementation, P2
should lock:

- ExecutionRequest schema and lifecycle;
- Scheduler and queue authority;
- PostgreSQL lease/fencing token behavior;
- Worker capability registration;
- SandboxProfile compilation;
- selected-action-to-execution coupling;
- settlement coupling to actual AgentRun completion;
- late result quarantine.

The current P0–P1 codebase is ready to serve as the baseline for those decisions.
