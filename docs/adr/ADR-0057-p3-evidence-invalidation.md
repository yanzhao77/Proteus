# ADR-0057: P3 Evidence Invalidation and Re-verification Authority

## Status

ACCEPTED

## Phase

P3-0

## Context

V1.2 requires Artifact hash changes and invalid Evidence to fail closed. P0/P1
prove exact-hash Verification paths, but P3 still needs an operational
invalidation and propagation protocol.

## Decision

Evidence invalidation is append-only. It records producer, reason, affected
Evidence refs, affected VerificationResults/Decisions/Gates/Tasks/Projects,
scope, expected versions, idempotency key and payload hash.

Invalidation does not delete Evidence and does not rewrite historical
VerificationResults. Historical Decisions preserve the Evidence hashes they used.
New Decisions cannot use invalidated Evidence. A previously `PASSED` Task is not
directly flipped to `FAILED`; instead, current dependency facts become stale and
Control Plane must decide through explicit guarded Commands whether to require
re-verification, enter waiting or enter recovery.

Gate Decisions depending on invalidated Evidence are no longer current and
cannot authorize resume or execution. Unknown impact fails closed with
`REVERIFICATION_REQUIRED`.

## Consequences

Evidence changes become auditable and safe under concurrency. The formal
Verification authority remains independent, while current state can no longer
advance using invalidated facts.

## Evidence

- [P3 Operational Governance Spec §9](../specs/Hermes_P3_Operational_Governance_Normative_Spec_V1.0.md#9-evidence-invalidation)
- [P3 Acceptance Matrix](../P3_OPERATIONAL_GOVERNANCE_ACCEPTANCE_MATRIX.md)
