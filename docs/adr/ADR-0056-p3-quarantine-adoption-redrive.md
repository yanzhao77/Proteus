# ADR-0056: P3 Quarantine Review, Adoption and Redrive Authority

## Status

ACCEPTED

## Phase

P3-0

## Context

P2-4 admits stale Worker payloads into minimal immutable quarantine and prevents
them from mutating current authority. P3 must define operational review without
letting a reviewer convert stale data into Task PASS or bypass current guards.

## Decision

P3 quarantine lifecycle is:

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

The original envelope/hash is immutable. Operational records store redacted
summaries, reviewer identity, reason, Evidence refs, expected version,
idempotency key, retention deadline and causation/correlation refs.

Adoption is not direct insertion into normal authority. It creates a new guarded
Command that re-evaluates current Policy, Lease, Fencing, versions, Evidence and
Guards. Redrive creates a new Command/idempotency identity while preserving the
original causation. Discarded and expired records retain audit summaries.

## Consequences

Quarantine becomes reviewable and recoverable, but never a shortcut around
Verification, Worker fencing or Control Plane authority.

## Evidence

- [P3 Operational Governance Spec §8](../specs/Hermes_P3_Operational_Governance_Normative_Spec_V1.0.md#8-quarantine-operations)
- [P3 Acceptance Matrix](../P3_OPERATIONAL_GOVERNANCE_ACCEPTANCE_MATRIX.md)
