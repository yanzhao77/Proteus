# ADR-0053: P3 Human Gate Request and Decision Authority

## Status

ACCEPTED

## Phase

P3-0

## Context

ADR-0017 established that Human Gate is independent from Main Hermes, but P3
needs the exact operational contract before implementation. V1.2 requires Human
Gate decisions to be resumable, explainable and unable to bypass Policy,
Verification or Control Plane guards.

## Decision

Human Gate has two separate immutable concepts:

- Gate Request: created by Main Hermes, Recovery Controller or Control Plane
  when Policy or recovery requires human input.
- Gate Decision: submitted by an authorized User or Operator and validated by
  Human Gate authority.

Main Hermes may display, explain and submit a user-provided answer, but it may
not approve its own request. Worker, Scheduler, Planner and Verifier identities
cannot approve, reject or apply Gate Decisions.

Gate lifecycle for P3 is:

```text
REQUESTED -> APPROVED / REJECTED / EXPIRED / CANCELLED / SUPERSEDED
```

An approved Gate Decision is a Guard fact, not a direct Project/Task mutation.
Control Plane must later consume it through a guarded Command with current
version, Evidence, Policy, Budget and scope checks. Expired or superseded
decisions fail closed.

Every Gate command carries actor, authorization reference, reason, idempotency
key, payload hash, expected version and immutable resume context reference.
Identity-provider and signature validation are interface boundaries; P3-0 does
not choose an SDK.

## Consequences

Human approvals cannot become arbitrary database patches or command strings.
High-risk multi-approval remains deferred, but the contract reserves approver
identity and authorization references for later dual-control policy.

## Evidence

- [P3 Operational Governance Spec §4](../specs/Hermes_P3_Operational_Governance_Normative_Spec_V1.0.md#4-human-gate-authority)
- [P3 Acceptance Matrix](../P3_OPERATIONAL_GOVERNANCE_ACCEPTANCE_MATRIX.md)
