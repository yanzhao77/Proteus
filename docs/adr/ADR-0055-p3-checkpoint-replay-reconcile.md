# ADR-0055: P3 Checkpoint, Replay and Reconcile Boundary

## Status

ACCEPTED

## Phase

P3-0

## Context

ADR-0006 and ADR-0007 define Hermes as authoritative state plus Event Log and
Outbox, not a full Event Sourcing system. P3 needs operational recovery without
letting replay overwrite current authority.

## Decision

Replay may rebuild consumer state, read models, audit/explain projections,
checkpoint candidates and recovery views. Replay must not blindly fold Events
over Project, Task, Accounting, Lease, ExecutionRequest or Verification
authority.

Consumer checkpoints are stream, partition, consumer group, code version and
schema version scoped. They advance only over contiguous sequences. Event gaps,
checkpoint corruption, unsupported critical schemas and unavailable retention
windows fail closed with stable P3 rejection codes.

Reconcile compares authoritative tables, Event Log, Outbox, Inbox, Checkpoint
and external facts. It first creates a dry-run plan and explanation. Applying a
plan submits guarded Commands to the owning authorities; Reconcilers never patch
authority tables directly.

## Consequences

FI-12 becomes a family of restart/replay/reconcile scenarios instead of one
ambiguous test. Operators get explainable repair plans, and authority protection
remains consistent with the no-full-event-sourcing decision.

## Evidence

- [P3 Operational Governance Spec §6](../specs/Hermes_P3_Operational_Governance_Normative_Spec_V1.0.md#6-checkpoint-replay-and-reconcile)
- [P3 Operational Governance Spec §7.3](../specs/Hermes_P3_Operational_Governance_Normative_Spec_V1.0.md#73-fi-12-control-plane-restart-with-checkpointreplayreconcile)
- [P3 Acceptance Matrix](../P3_OPERATIONAL_GOVERNANCE_ACCEPTANCE_MATRIX.md)
