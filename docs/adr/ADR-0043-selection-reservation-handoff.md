# ADR-0043: P2 Handoff of Selection-Created ResourceReservation

- Status: ACCEPTED
- Phase: P2-0
- Related specifications: Core Runtime Design V1.2 §§13-15, 26, 30; Execution Lease Protocol §5/§15; P2 Execution Admission Spec §8; ADR-0014; ADR-0041

## Context

ADR-0041 made P1 Selection atomically create ACTIVE ResourceReservations for
non-zero selected actions. The original Execution Lease Protocol described
ExecutionRequest PREPARING as the phase that reserves resources. If both are
implemented literally, P2 can double-reserve the same action or leak reservations
when request preparation fails.

## Decision

P2 does not reserve again for a selected action that already has a P1 ACTIVE
ResourceReservation. P2 binds and hands off the existing Reservation to the new
ExecutionRequest.

The handoff transaction must validate:

- DecisionRecord ID and selection version;
- SelectedAction ID/content hash;
- ResourceReservation ID, owner, action binding and ACTIVE status;
- ResourceAccount ID/version/currency/scope;
- frozen Reservation amounts equal the selected action estimate;
- no existing active ExecutionRequest is already bound to the same
  Decision/SelectedAction/Reservation unless idempotently returning the original.

ExecutionRequest MUST NOT enter `QUEUED` without a valid handoff. Same
Decision/Action/Preparation MUST NOT create a second Reservation.

Preparation failure handling:

- rollback if failure occurs before commit;
- deterministic `PREPARATION_FAILED` plus release when request cannot be retried
  without replan;
- bounded retain only when the same preparation can retry idempotently and
  reconcile has an expiry policy.

Transient retry under the same ExecutionRequest retains the handoff Reservation.
Strategy switch or replan requires a new Decision/SelectedAction and a new P1/P2
chain.

## Consequences

- FI-16 remains a P2 ExecutionRequest-coupling requirement, even though P1
  accounting rollback primitives are implemented.
- FI-17 remains split: P1 covers accounting settlement primitives; P2/P3 must
  bind settlement to real execution completion and reconcile.
- Queue and Lease code can trust `QUEUED` to already have a valid Reservation
  binding.
