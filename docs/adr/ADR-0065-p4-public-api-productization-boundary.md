# ADR-0065: P4 Public API Productization Boundary

## Status

ACCEPTED

## Phase

P4-0/P4-1

## Context

P0-P3 completed Hermes authority runtime slices, but they are application and
database authority services rather than a product API. P4 needs a callable
boundary while preserving the invariant that API code cannot write Project/Task
authority directly.

## Decision

Use a stdlib in-process product API facade with explicit request/response DTO
validation for P4. The facade supports semantic command wrappers and read/query
models only. It rejects generic PATCH/status update, arbitrary SQL, arbitrary
Event append and arbitrary command passthrough.

FastAPI and Pydantic are deferred. P4 does not require a network server to prove
the authority contract, and adding framework dependencies would not strengthen
the core invariant. Future Web/API work may wrap the same facade after a new ADR.

Authority-changing product requests must carry `command_id`,
`idempotency_key`, `expected_version`, `actor` and `reason`; the facade maps
HTTP-style `Idempotency-Key` into existing semantic command objects without
synthesizing authority facts.

## Consequences

The P4 API is testable without network dependencies and cannot accidentally
become a second Control Plane. A later FastAPI or public HTTP deployment remains
possible as a thin adapter over the same application boundary.
