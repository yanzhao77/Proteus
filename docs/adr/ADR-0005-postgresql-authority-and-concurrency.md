# ADR-0005: PostgreSQL as MVP Authority and Concurrency Point

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: ADR-0001 (storage portion)  
Superseded by: None  
Related specifications: [Runtime Spec §17](../specs/Hermes_Runtime_Normative_Spec_V1.0.md#17-consistency-and-transaction-boundaries)

## Context

MVP needs transactional authority, optimistic concurrency, Lease competition and atomic resource reservation without distributed consensus.

## Decision

PostgreSQL is the MVP authoritative state and concurrency serialization point. Its specific version and ORM/driver are OPEN. SQLite may support local pure/single-process tests but is not cluster-safety evidence.

## Alternatives Considered

SQLite for deployment, Redis locks, custom consensus; rejected for required semantics or unnecessary complexity.

## Consequences

Cluster tests require real PostgreSQL and independent connections.

## Validation

CT-002, CT-005 and FI-01/02/08 run against PostgreSQL.

## Open Questions

Minimum PostgreSQL version and migration tooling.
