# ADR-0044: ExecutionRequest PREPARING and QUEUED Semantics

- Status: ACCEPTED
- Phase: P2-0
- Related specifications: Core Runtime Design V1.2 §§15, 17, 26, 30; Execution Lease Protocol §§3, 5-9; P2 Execution Admission Spec §§5-7

## Context

P2 needs a durable queue contract. If `QUEUED` means merely “someone intends to
run this,” Scheduler may lease requests whose Policy, Risk, Capability, Context,
Sandbox, Artifact or Reservation prerequisites are missing.

## Decision

ExecutionRequest states are specified as:

```text
PREPARING -> QUEUED -> LEASED -> RUNNING -> RESULT_SUBMITTED
          -> SUCCEEDED | FAILED | CANCELLED | TIMED_OUT

PREPARING -> PREPARATION_FAILED
QUEUED/LEASED/RUNNING -> CANCEL_REQUESTED -> CANCELLED | TIMED_OUT
LEASED/RUNNING -> QUEUED        (expired lease and retry policy allows)
RESULT_SUBMITTED -> QUARANTINED (stale token or invalid identity)
```

`PREPARING` is non-runnable. It may exist only as a durable preparation record or
inside the same local transaction that reaches `QUEUED`.

`QUEUED` means all execution inputs are frozen and admission succeeded. It must
bind Project, Task, DecisionRecord, SelectedAction, PolicyDecision,
RiskAssessment, ResourceReservation, WorkerTemplate revision, Context Bundle
hash/version, SandboxProfile hash/compiler version, VerificationPlan version,
Artifact refs/hashes, lock scopes, command/idempotency and expected versions.

`SUCCEEDED` means execution protocol success, not Task PASS. Verification remains
the sole formal verdict authority.

## Consequences

- Scheduler may only lease `QUEUED` requests.
- Capability, Context and Sandbox failures cannot be deferred to Worker pickup.
- Unknown or unsupported action route is an admission failure, not a queue item.
- Queue tests must assert no runnable row exists before all frozen refs exist.
