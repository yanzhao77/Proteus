# ADR-0008: One Local Transaction for State and Outbox

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: ADR-0001 (outbox portion)  
Superseded by: None  
Related specifications: [Command/Event Protocol §6](../specs/Hermes_Command_Event_Protocol_V1.0.md#6-authoritative-transaction)

## Context

Publishing separately from authority mutation can lose or invent facts.

## Decision

Authority mutation, Event Log record, Outbox Message and CommandResult MUST commit in one PostgreSQL local transaction. External publish is asynchronous and at least once.

## Alternatives Considered

Dual write and distributed transaction; rejected for inconsistency or MVP overdesign.

## Consequences

Relay and consumers must tolerate duplicates.

## Validation

FI-01 through FI-05.

## Open Questions

Relay batch and retention tuning.
