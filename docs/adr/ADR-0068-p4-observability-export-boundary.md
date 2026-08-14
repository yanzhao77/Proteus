# ADR-0068: P4 Observability and Export Boundary

## Status

ACCEPTED

## Phase

P4-0/P4-4

## Context

P3 added explain, audit, trace and Docker observations. P4 needs product
observability/export surfaces, but metrics and traces must not become hidden
authorization facts.

## Decision

Introduce an observability port with a local/test exporter and
OpenTelemetry-compatible envelope fields (`trace_id`, `span_id`, `parent_span_id`,
attributes, events, metrics and resource metadata). The runtime does not require
an OpenTelemetry SDK or backend in P4.

Exports apply redaction before publication. Unsafe records are rejected or
redacted; missing source links are represented as explicit `MISSING` records.
Observability cannot authorize Policy, Risk, Budget, Gate, Task or Project
state.

## Consequences

P4 gains auditable product diagnostics while preserving the P0-P3 authority
model. Production telemetry backend selection remains a later deployment ADR.
