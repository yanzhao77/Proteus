# ADR-0011: PostgreSQL Lease with Monotonic Fencing Token

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: ADR-0001 (lease portion)  
Superseded by: None  
Related specifications: [Execution Lease Protocol](../specs/Hermes_Execution_Lease_Protocol_V1.0.md)

## Context

Multiple Schedulers and partitioned Workers require durable exclusive current ownership.

## Decision

Lease acquisition uses PostgreSQL atomic conditions/locking. Every re-grant increments a monotonic fencing token; all lifecycle and Result Commands carry it. Stale Results are quarantined.

## Alternatives Considered

Process locks, read-then-write and unfenced distributed locks; rejected as unsafe.

## Consequences

Database clock and token validation are correctness dependencies.

## Validation

CT-002/003 and FI-09-11.

## Open Questions

TTL profiles and adapter side-effect idempotency.
