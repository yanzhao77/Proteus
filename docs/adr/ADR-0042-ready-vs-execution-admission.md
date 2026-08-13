# ADR-0042: Separate Task READY from Execution Admission

- Status: ACCEPTED
- Phase: P2-0
- Related specifications: Core Runtime Design V1.2 §§5, 15, 26, 30; Runtime Normative Spec §§8, 20-21; P2 Execution Admission Spec §§4-5; ADR-0021; ADR-0040

## Context

P0 implemented authoritative Task DAG readiness. P1 implemented Selection and
ResourceReservation. Entering P2, `Task READY` could be misread as enough
permission to create a runnable queue item. That would bypass Policy/Risk
freshness, Human Gate blocks, Artifact hashes, Worker capability, Context,
Sandbox and lock constraints.

## Decision

`Task READY` remains a graph fact only: all authoritative `DEPENDS_ON` edges are
satisfied and the Task DAG is acyclic. It is not execution-admissible and does
not imply safe queueing.

P2 introduces fail-closed Execution Admission. Admission is proven by a guarded
Control Plane command or by equivalent ExecutionRequest preparation invariants.
It must verify at least:

- Task dependencies;
- Project and Task state;
- no blocking Human Gate;
- required Artifact availability and exact hashes;
- current ACTIVE VerificationPlan;
- current ALLOW PolicyDecision;
- current RiskAssessment and mandatory mitigations;
- ACTIVE ResourceReservation;
- matching WorkerTemplate revision;
- frozen Context Bundle;
- compiled SandboxProfile;
- normalized execution locks.

No new Task state is required for this separation.

## Consequences

- `READY` remains reusable by Planning and projections without becoming a queue
  contract.
- SelectedAction is not queueable until Execution Admission succeeds.
- Admission failures are explicit, versioned, auditable and fail closed.
- P2 tests must assert both positive admission and each fail-closed rejection.
