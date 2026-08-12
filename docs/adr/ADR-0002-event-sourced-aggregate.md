# ADR-0002: Event-Sourced Aggregate for Project and Task State

Status: SUPERSEDED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: ADR-0006, ADR-0007  
Related specifications: [Runtime Spec §4](../specs/Hermes_Runtime_Normative_Spec_V1.0.md#4-runtime-model)

## Context

The former root ADR-002 declared that Project and Task state was derived only by folding immutable Events and that database state was a disposable Projection.

## Decision

This decision is superseded because it conflicts with V1.2 §4.3 and §28. Hermes uses authoritative relational state plus Event Log and transactional Outbox; it does not use full Event Sourcing.

## Alternatives Considered

Keep Event-Sourced aggregates; rejected because it changes V1.2 authority and normal Command semantics.

## Consequences

Reducers may validate transitions or rebuild projections, but normal writes use guarded Command transactions against authoritative state.

## Validation

Architecture review MUST reject claims that authoritative state is a disposable projection.

## Open Questions

Snapshot and projection optimization details remain open.
