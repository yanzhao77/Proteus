# ADR-0059: P3 Production Execution Adapter and External Side-effect Boundary

## Status

ACCEPTED

## Phase

P3-0

## Context

P2 freezes backend-neutral `contract-only/1.0` SandboxProfiles and uses test
adapters only. P3 must define what a production execution adapter must prove
before Hermes can run real Worker processes or external side effects.

## Decision

P3-0 does not choose Docker or restricted Process as the production default. The
P3-5 decision gate requires the selected target to prove:

- SandboxProfile compilation to concrete runtime flags with compiler
  target/version;
- deny-by-default filesystem, network and secret-handle behavior;
- Worker process spawn, heartbeat, timeout, kill and artifact collection;
- bounded/redacted stdout and stderr;
- usage measurement or explicit untrusted usage marking with reconcile;
- fencing token propagation into Worker and side-effect envelopes;
- idempotent external side-effect receipt capture;
- fail-closed handling for irreversible side effects;
- adapter crash, stale Worker termination and side-effect reconcile.

External side effects are receipts, not Hermes authority. They must be tied to
idempotency key, causation, request/run/lease/fencing refs and later reconcile.

## Consequences

P3-5 can implement one production target without changing P2 authority semantics.
If a target cannot prove isolation or reconcile semantics, it remains out of
scope rather than being hidden behind the existing test adapter.

## Evidence

- [P3 Operational Governance Spec §11](../specs/Hermes_P3_Operational_Governance_Normative_Spec_V1.0.md#11-production-execution-boundary)
- [P3 Acceptance Matrix](../P3_OPERATIONAL_GOVERNANCE_ACCEPTANCE_MATRIX.md)
