# ADR-0006: Authoritative State plus Event Log and Outbox

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: ADR-0002  
Superseded by: None  
Related specifications: [Runtime Spec §4](../specs/Hermes_Runtime_Normative_Spec_V1.0.md#4-runtime-model)

## Context

Runtime needs current authority, audit facts, durable publication and recovery without changing V1.2 into Event Sourcing.

## Decision

Use authoritative relational State + append-only Event Log + transactional Outbox + Checkpoint/Replay/Reconcile. Authority rows are not disposable projections. Normal writes enter through guarded Command handlers.

## Alternatives Considered

State only; lacks audit/recovery. Full Event Sourcing; conflicts with V1.2 and adds complexity.

## Consequences

Implementations maintain both current state and immutable facts atomically.

## Validation

FI-01/02/12 and architecture review.

## Open Questions

Retention and archive media.
