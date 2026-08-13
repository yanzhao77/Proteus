# ADR-0045: Action Routing and Lock Scope Boundary

- Status: ACCEPTED
- Phase: P2-0
- Related specifications: Core Runtime Design V1.2 §§10, 14-17, 26; P2 Execution Admission Spec §§9, 13; ADR-0036; ADR-0040

## Context

Planner can propose actions and Selection can choose execution intent, but not
every SelectedAction is a Worker job. Some actions belong to Control Plane,
Human Gate, or Recovery/Reconcile authorities. P2 also needs a stable lock-scope
vocabulary before queued execution can safely run concurrently.

## Decision

P2 admission classifies each SelectedAction into one route:

| Route | Meaning |
| --- | --- |
| Worker-executable | May produce ExecutionRequest only after admission checks pass. |
| Control Plane internal | Must run through a Control Plane semantic command. |
| Human Gate | Must route to Human Gate authority, not Worker queue. |
| Recovery/Reconcile | Must route to recovery service command. |
| Unsupported | Must fail closed. |

Unknown, disabled or unimplemented action types reject with
`EXEC_ADMISSION_ACTION_ROUTE_UNSUPPORTED`.

P2 lock scopes use this minimum vocabulary:

- `repository`
- `workspace`
- `branch_ref`
- `artifact_namespace`
- `external_environment`
- `deployment_target`

Canonical form is `<kind>:<normalized stable identifier>`. Unknown critical lock
kind fails closed. Lock acquisition order is canonical and deterministic by
configured kind order and stable ID. Scheduler Lease does not replace domain
locks.

## Consequences

- Planner and Selection remain proposal/decision authorities; they do not imply
  executor availability.
- Worker Queue receives only Worker-executable admitted requests.
- Lock conflict tests can be written before Scheduler implementation.
- P2 may add route metadata without changing P1 CandidateAction semantics.
