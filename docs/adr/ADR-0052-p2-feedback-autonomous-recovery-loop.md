# ADR-0052: P2 Feedback and Bounded Autonomous Recovery Loop

## Status

ACCEPTED

## Phase

P2-5

## Context

P2-4 closes fenced Worker execution through terminal `ExecutionResult`,
CompletionClaim bridging and ResourceReservation settlement/release. A failed
execution is still only an execution fact: it must not silently retry inside the
Scheduler and must not let Worker, Recovery or Control Plane mark the Task
`PASSED` or `FAILED` without independent Verification authority.

P2-5 must turn execution failure into structured Feedback and a bounded recovery
ledger while preserving the P1 autonomy chain:

```text
failed ExecutionResult
-> structured feedback.created
-> Situation
-> Diagnosis
-> CandidateAction planning
-> bounded RecoveryAttempt
-> new execution/verification path
```

P3 Human Gate UX, full checkpoint replay/reconcile, quarantine adoption/redrive
and production external-side-effect reconciliation remain out of scope.

## Decision

P2-5 introduces a dedicated Recovery Controller authority backed by migration
`0017_feedback_recovery_loop.sql`.

Recovery authority owns only:

- immutable `execution_feedback_records`;
- `recovery_cycles`;
- `recovery_attempts`;
- minimal `recovery_collaboration_requests` records.

It exposes exactly three guarded PostgreSQL commands:

- `hermes_emit_execution_feedback`;
- `hermes_plan_recovery_attempt`;
- `hermes_complete_recovery_attempt`.

`hermes_emit_execution_feedback` accepts only failed P2-4 `execution_results`.
It classifies failure into a deterministic taxonomy, writes a structured
`feedback.created` Event/Outbox and a `recovery.cycle_started` Event/Outbox in
the same transaction, and mirrors a compatibility `feedback_records` row so the
existing P1 Situation/Diagnosis/Planner chain can consume execution-originated
feedback.

The deterministic taxonomy maps at least:

- test assertion and build failures to `L1_REPAIR`;
- transient adapter/timeout failures to bounded retry/switch-worker hints;
- policy and budget failures to switch-strategy / Human Gate hints;
- sandbox violations directly to Human Gate;
- unknown execution failures to replan / Human Gate.

Recovery attempts are bounded by `max_attempts`. Once the autonomous budget is
exhausted, a final blocked `human_gate` attempt is recorded and the cycle becomes
`EXHAUSTED`; P2-5 records the request but does not implement P3 Human Gate
lifecycle.

Recovery may link an attempt to later ExecutionRequest, ExecutionResult and
VerificationResult IDs, but this ledger link is not state authority. Task
`PASSED` or `FAILED` still requires independent VerificationResult plus Control
Plane `task.apply_verified_transition`.

Recovery runtime has no direct write privilege on Task, Verification, Worker
execution, Event Log, Outbox or Accounting authority tables. It also does not
take write locks on Worker-owned result rows; failed results are read-only input
facts.

`switch_worker` is the recovery-protocol name for choosing a different Worker
capability/template/context in a later execution attempt. It is distinct from
the current P1 Planner registry's `switch_agent` naming and is intentionally
stored only in the Recovery ledger in this slice.

## Consequences

- Business/test failure leaves the Scheduler retry path and enters the
  Feedback/Situation/Diagnosis/Planner loop.
- Recovery becomes auditable and bounded without creating a parallel Planner or
  bypassing Policy/Risk/Budget/ExecutionRequest admission.
- Execution success still does not imply Task PASS.
- Recovery completion records attempt outcome and links, but does not mutate
  Task verdict state.
- P2 is complete for execution authority through bounded feedback/recovery loop
  entry; P3 remains responsible for Human Gate lifecycle and operational
  recovery/reconcile.

## Evidence

- `hermes-runtime/migrations/0017_feedback_recovery_loop.sql`
- `hermes-runtime/src/hermes_runtime/domain/recovery.py`
- `hermes-runtime/src/hermes_runtime/application/recovery.py`
- `hermes-runtime/src/hermes_runtime/infrastructure/postgres_recovery.py`
- `hermes-runtime/src/hermes_runtime/infrastructure/postgres_diagnosis.py`
- `hermes-runtime/tests/test_recovery_domain.py`
- `hermes-runtime/tests/test_recovery_postgres.py`
- `hermes-runtime/tests/test_recovery_permissions.py`
