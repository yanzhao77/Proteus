# ADR-0009: Optimistic Concurrency with Expected Version

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Command/Event Protocol §5](../specs/Hermes_Command_Event_Protocol_V1.0.md#5-expected-version)

## Context

Concurrent Control Plane commands must not overwrite newer authority.

## Decision

Every mutable authority entity MUST have a version; changing Commands MUST carry `expected_version`; mismatch rejects without domain side effects.

## Alternatives Considered

Last-write-wins and blind retry; rejected for lost updates. Long pessimistic transactions; rejected around external work.

## Consequences

Clients reload and replan after conflict.

## Validation

FI-08 and concurrent command integration tests.

## Open Questions

Version granularity for Work Graph patches.
