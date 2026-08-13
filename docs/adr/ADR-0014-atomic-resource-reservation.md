# ADR-0014: Atomic Resource Reservation and Settlement

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: ADR-0001 (accounting portion)  
Superseded by: None  
Related specifications: [Execution Lease Protocol §15](../specs/Hermes_Execution_Lease_Protocol_V1.0.md#15-resource-accounting-lifecycle)

## Context

Concurrent Actions can overspend a shared Budget and crashes can leak Reservation.

## Decision

Resource Accounting owns versioned `ResourceAccount` and per-dimension `limit / consumed / reserved` balances. The twelve V1.2 dimensions use non-negative integers; `llm_cost_minor` requires a three-letter currency and currencies are never merged.

Every multi-dimensional Reservation locks its Account and balances in PostgreSQL, compares `expected_version`, validates all dimensions, and then changes every balance or none. A Reservation binds a stable `decision`, `action`, or `preparation` owner. It does not imply an ExecutionRequest.

Usage samples are immutable and idempotent by sample identity. Settlement locks the Reservation and Account, consumes every unprocessed sample exactly once, records the full actual amount even above the Reservation, releases the full reserved amount, and enters hard stop when actual use exceeds the limit. `warn`, `gate`, and `hard_stop` use integer basis points. Hard stop rejects new ordinary Reservations but Release, Usage, Settlement and Reconcile remain legal.

Accounting mutations execute through narrowly scoped `SECURITY DEFINER` functions owned by a dedicated `NOLOGIN` role with fixed `pg_catalog` search path. The runtime role has no direct balance write privilege. Resource state, Event, Outbox and CommandReceipt commit in one local transaction.

## Alternatives Considered

In-memory counters and post-execution accounting only; rejected.

## Consequences

Resource Accounting is P1 and required before distributed Worker scheduling conformance, not before all P0 work. FI-16 and FI-17 are closed here only for preparation/reservation and usage/settlement accounting. ExecutionRequest, Lease, fencing and real Run completion coupling remain P2/P3 work.

## Validation

Domain threshold/settlement tests and PostgreSQL 14/16 integration tests cover CT-005, multi-dimensional all-or-nothing, FI-16 accounting rollback, FI-17 crash recovery, two concurrent reconcilers, orphan release, over-limit settlement, idempotency and runtime permissions.

## Open Questions

Currency conversion and emergency accounting policy. Parent/portfolio allocation and real ExecutionRequest/Run coupling remain deliberately unimplemented.
