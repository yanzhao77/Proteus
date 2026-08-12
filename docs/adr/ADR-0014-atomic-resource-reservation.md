# ADR-0014: Atomic Resource Reservation and Settlement

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: ADR-0001 (accounting portion)  
Superseded by: None  
Related specifications: [Execution Lease Protocol §15](../specs/Hermes_Execution_Lease_Protocol_V1.0.md#15-resource-accounting-lifecycle)

## Context

Concurrent Actions can overspend a shared Budget and crashes can leak Reservation.

## Decision

Resource Accounting supports allocation, reservation, consumption, settlement, release and thresholds. Reservations use PostgreSQL atomic conditions; ExecutionRequest/Lease lifecycle and reconcile release or settle them exactly once.

## Alternatives Considered

In-memory counters and post-execution accounting only; rejected.

## Consequences

Resource Accounting is P1 and required before distributed Worker scheduling conformance, not before all P0 work.

## Validation

CT-005 and FI-16/17.

## Open Questions

Currency conversion and emergency accounting policy.
