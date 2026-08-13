# ADR-0041: Selection/Reservation Atomic Bridge and Permission Boundary

- Status: ACCEPTED
- Phase: P1
- Related specifications: Core Runtime Design V1.2 §§13, 14, 18, 26, 30; Command/Event Protocol §§4-6; ADR-0014; ADR-0039; ADR-0040

## Context

V1.2 requires non-zero selected actions to have authoritative ResourceReservation
before they can be treated as selected execution intent. Budget feasibility alone
is not a reservation, and a partial multi-action reservation would corrupt
cluster safety. At the same time, Selection runtime must not receive broad
Accounting write permissions or impersonate Control Plane.

## Decision

P1 Slice 6 uses a narrow PostgreSQL `SECURITY DEFINER` bridge,
`public.hermes_apply_selection_decision(...)`, owned by
`hermes_selection_owner` and callable by `hermes_selection_runtime`.

The bridge validates the already-computed deterministic Selection payload against
current authoritative database state, locks ResourceAccounts in stable account ID
order, and commits the following in one PostgreSQL transaction:

```text
CommandReceipt PROCESSING
-> Selection scope/version validation
-> Situation/PlanningRun/Candidate freshness validation
-> Policy/Risk freshness validation
-> ResourceAccount version/balance lock
-> ResourceReservation rows and amounts
-> budget.reserved Event and Outbox rows
-> immutable DecisionRecord/Score/Disposition/Selected refs
-> decision.recorded Event and Outbox rows
-> CommandReceipt APPLIED
```

The bridge is intentionally narrow because the existing Accounting reservation
authority in `0007_resource_accounting.sql` is `control_plane` scoped and because
`resource_reservations.command_id` is unique. A single parent
`selection.select_actions` command can select multiple actions, so the bridge
creates deterministic child `resource.reserve` command receipts per selected
non-zero action while preserving the parent Selection receipt.

Runtime code does not receive direct permissions to mutate ResourceAccount
balances, ResourceReservations, DecisionRecords, PolicyDecision, RiskAssessment,
CandidateAction, Situation, Project, Task, or execution state.

## Consequences

- Any pre-commit failure leaves no reserved balance, Reservation, Score,
  DecisionRecord, Event, Outbox or successful receipt.
- A successful commit always contains DecisionRecord, selected refs, exact
  Reservation mappings for non-zero selected actions, `budget.reserved`,
  `decision.recorded`, Outbox rows and an applied receipt together.
- Same key/same payload retries return the original result; same key/different
  payload conflicts; a new key over the same active canonical snapshot converges
  instead of reserving again.
- No `execution.queued`, `execution.requested`, Scheduler, Lease, Worker or
  Sandbox state is created by this slice.
