# ADR-0029: Minimal P0 AgentRun Authority

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Runtime Normative Spec §21](../specs/Hermes_Runtime_Normative_Spec_V1.0.md#21-phase-requirements)

## Context

`CompletionClaim.run_id` was an unverified string. P0 needs stable identity for Artifact provenance and Worker/Judge separation, while ExecutionRequest, Lease, fencing and full Worker lifecycle belong to P2.

## Decision

P0 persists a minimal Control-Plane-admitted `AgentRun`: Project, Task, `WORKER|VERIFIER`, agent identity, context identity, `ADMITTED|COMPLETED|INVALIDATED`, creator Command and version. Admission and invalidation are explicit idempotent Commands with expected-version checks and atomic Event/Outbox/Receipt.

CompletionClaim accepts only a matching non-invalidated WORKER Run and binds Artifact provenance to it. VerificationResult accepts only a matching non-invalidated VERIFIER Run. The model deliberately has no queue, spawn, heartbeat, Lease, fencing, retry or accounting behavior.

## Consequences

P0 closes identity authority without pretending to implement Scheduler safety. Execution Lease Protocol remains mandatory before real P2 execution admission.

## Validation

Tests cover missing, wrong-kind, cross-Task, cross-Project, identity-mismatched and invalidated Runs plus admission idempotency and rollback.

## Open Questions

P2 will define ExecutionRequest linkage, fencing token, lifecycle transitions, reservation/usage coupling and late-result quarantine.
