# ADR-0010: Scoped Idempotency-Key and Duplicate Command Semantics

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Command/Event Protocol §4](../specs/Hermes_Command_Event_Protocol_V1.0.md#4-idempotency-and-commandresult)

## Context

Clients and internal handlers retry after ambiguous failures.

## Decision

Authority Commands MUST persist a scoped Idempotency-Key, canonical request hash and CommandResult. Same key/same payload returns original result; same key/different payload rejects.

## Alternatives Considered

At-most-once client behavior and command-id-only deduplication; rejected as insufficient.

## Consequences

Canonicalization and retention policy are required.

## Validation

FI-06 and FI-07 plus uniqueness constraints.

## Open Questions

Canonical JSON implementation and exact retention durations.
