# ADR-0033: AnalysisContext Uses an Observed-Sequence Authority Boundary

- Status: ACCEPTED
- Phase: P1
- Related specifications: Core Runtime Design V1.2 §§7-9, 26, 28; Command/Event Protocol §§10-12

## Context

Situation analysis is replayable only when its inputs are fixed. Reading the latest
Project, Task, Verification or ResourceAccount row while processing an older Event
would silently introduce facts newer than that Event's partition sequence.

## Decision

Every accepted Trigger Event creates one immutable `analysis_contexts` row. Its
`observed_at_sequence` is the Trigger Event's partition-local sequence. Inputs are
limited to the immutable Event envelope/payload and authority records whose stable
IDs and versions are carried by that Event. Current mutable rows may validate
identity or that a historical version existed, but their current values are not
copied into the historical context.

The context records stable Artifact, Evidence, Verification, ResourceAccount-version,
Policy and Work Graph references. Missing authority, Project/Task mismatch, future
Evidence and unsupported historical reconstruction fail closed with stable reason
codes. The context hash is canonical SHA-256 over semantic inputs and rule version;
it excludes timestamps, random IDs, physical row order and Situation identity.

## Consequences

- Replaying the same Trigger Event returns its original Inbox result and Context.
- Later mutable state cannot rewrite an existing AnalysisContext.
- Historical data that cannot be proven at or before the observed boundary requires
  reconcile; the analyzer does not substitute the latest state.
- Full historical Project/Task snapshots remain an open future migration concern.
