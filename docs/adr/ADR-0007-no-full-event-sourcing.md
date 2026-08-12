# ADR-0007: Do Not Adopt Full Event Sourcing for MVP

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: ADR-0002  
Superseded by: None  
Related specifications: [Command/Event Protocol §15](../specs/Hermes_Command_Event_Protocol_V1.0.md#15-checkpoint-and-replay)

## Context

Pure reducers and replay are useful, but requiring all authority to be reconstructed by folding Events is not a V1.2 requirement.

## Decision

Hermes MUST NOT require full Event Sourcing for MVP. Replay rebuilds projections, supports audit, and assists recovery/reconcile; it is not the sole normal state write entry.

## Alternatives Considered

Full Event Sourcing; rejected due semantic conflict and migration/operational burden.

## Consequences

State schema migrations remain explicit; Event schema still requires compatibility.

## Validation

Review persistence interfaces for direct guarded state mutation plus Outbox, and reject disposable-authority designs.

## Open Questions

Whether a bounded future subsystem benefits from Event Sourcing.
