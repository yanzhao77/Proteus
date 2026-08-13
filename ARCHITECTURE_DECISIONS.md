# Hermes Runtime Architecture Decision Index

This file is the navigation index for Hermes Core Runtime architecture decisions. Normative protocols live in [`docs/specs/`](docs/specs/); individual decisions and their history live in [`docs/adr/`](docs/adr/). This index does not redefine either.

Authority order:

1. [Core Runtime Design V1.2 Runtime Invariants and explicit protocols](docs/Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.2.md#26-runtime-invariants)
2. Current task requirements and [normative specifications](docs/specs/Hermes_Runtime_Normative_Spec_V1.0.md)
3. Other V1.2 design content
4. [Architecture V1.0](docs/Hermes_Autonomous_Software_Factory_Architecture_V1.0.md)
5. Accepted ADRs below

Allowed ADR statuses: `PROPOSED`, `ACCEPTED`, `SUPERSEDED`, `REJECTED`.

## Normative specifications

| Specification | Scope |
| --- | --- |
| [Hermes Runtime Normative Specification V1.0](docs/specs/Hermes_Runtime_Normative_Spec_V1.0.md) | authority, ownership, invariants, phases and traceability |
| [Hermes Command and Event Protocol V1.0](docs/specs/Hermes_Command_Event_Protocol_V1.0.md) | Command, authoritative transaction, Event, Outbox, delivery and recovery |
| [Hermes Execution Lease Protocol V1.0](docs/specs/Hermes_Execution_Lease_Protocol_V1.0.md) | ExecutionRequest, Lease, fencing, result admission and accounting interaction |
| [Hermes Conformance Test Specification V1.0](docs/specs/Hermes_Conformance_Test_Spec_V1.0.md) | V1.2 §30.2 tests, fault injection and phase gates |

## ADR registry

| ADR | Title | Status | Phase | Related specification | File | Supersedes |
| --- | --- | --- | --- | --- | --- | --- |
| ADR-0001 | Mixed MVP Stack and Infrastructure Baseline | SUPERSEDED | P0-P2 | Runtime §2/§21 | [ADR-0001](docs/adr/ADR-0001-mixed-mvp-stack-baseline.md) | — |
| ADR-0002 | Event-Sourced Aggregate for Project and Task State | SUPERSEDED | P0 | Runtime §4 | [ADR-0002](docs/adr/ADR-0002-event-sourced-aggregate.md) | — |
| ADR-0003 | Initial Six-Test Architecture Gate | SUPERSEDED | P0-P2 | Conformance entire spec | [ADR-0003](docs/adr/ADR-0003-six-test-architecture-gate.md) | — |
| ADR-0004 | Organize Code by Authority Boundary | ACCEPTED | P0-P3 | Runtime §§5-7 | [ADR-0004](docs/adr/ADR-0004-authority-boundary-code-organization.md) | — |
| ADR-0005 | PostgreSQL as MVP Authority and Concurrency Point | ACCEPTED | P0/Cluster | Runtime §17 | [ADR-0005](docs/adr/ADR-0005-postgresql-authority-and-concurrency.md) | ADR-0001 (storage) |
| ADR-0006 | Authoritative State plus Event Log and Outbox | ACCEPTED | P0/P3 | Runtime §§4,18 | [ADR-0006](docs/adr/ADR-0006-authoritative-state-event-log-outbox.md) | ADR-0002 |
| ADR-0007 | Do Not Adopt Full Event Sourcing for MVP | ACCEPTED | P0 | Command/Event §15 | [ADR-0007](docs/adr/ADR-0007-no-full-event-sourcing.md) | ADR-0002 |
| ADR-0008 | One Local Transaction for State and Outbox | ACCEPTED | P0 | Command/Event §6 | [ADR-0008](docs/adr/ADR-0008-local-transaction-state-outbox.md) | ADR-0001 (outbox) |
| ADR-0009 | Optimistic Concurrency with Expected Version | ACCEPTED | P0 | Command/Event §5 | [ADR-0009](docs/adr/ADR-0009-optimistic-concurrency.md) | — |
| ADR-0010 | Scoped Idempotency-Key and Duplicate Command Semantics | ACCEPTED | P0 | Command/Event §4 | [ADR-0010](docs/adr/ADR-0010-idempotency-command-semantics.md) | — |
| ADR-0011 | PostgreSQL Lease with Monotonic Fencing Token | ACCEPTED | P2/Cluster | Lease entire spec | [ADR-0011](docs/adr/ADR-0011-postgresql-lease-fencing.md) | ADR-0001 (lease) |
| ADR-0012 | Separate Worker, Verification and State Authority | ACCEPTED | P0 | Runtime §§11,15 | [ADR-0012](docs/adr/ADR-0012-worker-verification-authority-isolation.md) | — |
| ADR-0013 | Capability-Based Workers and Fail-Closed Sandbox Compilation | ACCEPTED | P2 | Runtime §19 | [ADR-0013](docs/adr/ADR-0013-capability-and-sandbox-authority.md) | ADR-0001 (registry/sandbox) |
| ADR-0014 | Atomic Resource Reservation and Settlement | ACCEPTED | P1/P2 | Lease §15 | [ADR-0014](docs/adr/ADR-0014-atomic-resource-reservation.md) | ADR-0001 (accounting) |
| ADR-0015 | At-Least-Once Delivery with Idempotent Consumers | ACCEPTED | P0/Cluster | Command/Event §§9-13 | [ADR-0015](docs/adr/ADR-0015-at-least-once-idempotent-consumers.md) | — |
| ADR-0016 | No Premature Distributed Infrastructure in MVP | ACCEPTED | P0-P3 | Runtime §2 | [ADR-0016](docs/adr/ADR-0016-no-premature-distributed-infrastructure.md) | ADR-0001 (scope) |
| ADR-0017 | Human Gate Remains Independent from Main Hermes | ACCEPTED | P3 | Runtime §12 | [ADR-0017](docs/adr/ADR-0017-human-gate-independent-authority.md) | — |
| ADR-0018 | Python 3.9+ for the First P0 Vertical Slice | ACCEPTED | P0 | Runtime §23 | [ADR-0018](docs/adr/ADR-0018-python-runtime-toolchain.md) | — |
| ADR-0019 | Psycopg 3 and Versioned Native SQL Migrations | ACCEPTED | P0 | Command/Event §6 | [ADR-0019](docs/adr/ADR-0019-psycopg-native-sql-migrations.md) | — |
| ADR-0020 | PostgreSQL 14+ Integration Test Baseline | ACCEPTED | P0 | Conformance §1 | [ADR-0020](docs/adr/ADR-0020-postgresql-14-integration-baseline.md) | — |
| ADR-0021 | Project-Scoped Work Graph Version | ACCEPTED | P0 | Runtime §6.3 | [ADR-0021](docs/adr/ADR-0021-project-scoped-work-graph-version.md) | — |
| ADR-0022 | Minimal P0 Project State Machine | ACCEPTED | P0 | Runtime §5 | [ADR-0022](docs/adr/ADR-0022-minimal-project-state-machine.md) | — |
| ADR-0023 | PostgreSQL Project Runtime Roles and Event Invariant | ACCEPTED | P0 | Runtime Invariants 1/4 | [ADR-0023](docs/adr/ADR-0023-postgresql-project-runtime-roles.md) | — |
| ADR-0024 | Project Transition Guard Facts Fail Closed | ACCEPTED | P0/P1/P3 | Runtime §5.1 | [ADR-0024](docs/adr/ADR-0024-project-transition-guard-facts-fail-closed.md) | — |
| ADR-0025 | SECURITY DEFINER Search Path and Owner Hardening | ACCEPTED | P0 | Runtime Invariants 1/4 | [ADR-0025](docs/adr/ADR-0025-security-definer-search-path-and-owner-hardening.md) | — |
| ADR-0026 | Partition-Local Event Sequence and Contiguous Consumer Checkpoint | ACCEPTED | P0 | Command/Event §§10-12,15 | [ADR-0026](docs/adr/ADR-0026-partition-local-sequence-contiguous-checkpoint.md) | — |
| ADR-0027 | Outbox Relay Lease, Delivery DLQ and Authorized Redrive | ACCEPTED | P0 Operations | Command/Event §§9-14 | [ADR-0027](docs/adr/ADR-0027-outbox-relay-lease-dlq-redrive.md) | — |
| ADR-0028 | VerificationPlan Version Authority and Computed Verdict | ACCEPTED | P0 | Runtime §15 | [ADR-0028](docs/adr/ADR-0028-verification-plan-version-authority.md) | — |
| ADR-0029 | Minimal P0 AgentRun Authority | ACCEPTED | P0/P2 boundary | Runtime §21 | [ADR-0029](docs/adr/ADR-0029-minimal-p0-agent-run-authority.md) | — |
| ADR-0030 | Worker and Verifier Run/Context Independence | ACCEPTED | P0 | Runtime Invariant 14 | [ADR-0030](docs/adr/ADR-0030-worker-verifier-run-context-independence.md) | ADR-0012 |
| ADR-0031 | Legacy VerificationResult and Run Reference Migration | ACCEPTED | P0 migration | Runtime §15 | [ADR-0031](docs/adr/ADR-0031-legacy-verification-result-migration.md) | — |
| ADR-0032 | Resource Account Budget Fact Bridge | ACCEPTED | P1 | Runtime §§5/13 | [ADR-0032](docs/adr/ADR-0032-resource-account-budget-fact-bridge.md) | — |
| ADR-0033 | AnalysisContext Observed-Sequence Authority | ACCEPTED | P1 | Runtime §§7-9/18 | [ADR-0033](docs/adr/ADR-0033-analysis-context-observed-sequence-authority.md) | — |
| ADR-0034 | Situation Fingerprint and Lifecycle Authority | ACCEPTED | P1 | Runtime §§8/21/28 | [ADR-0034](docs/adr/ADR-0034-situation-fingerprint-and-lifecycle-authority.md) | — |
| ADR-0035 | Deterministic Diagnosis Rule Authority | ACCEPTED | P1 | Runtime §§9/19-21/25-28/30 | [ADR-0035](docs/adr/ADR-0035-diagnosis-rule-authority.md) | — |
| ADR-0036 | Candidate Action Planner and Versioned Action Registry | ACCEPTED | P1 | Runtime §§10-14/19-21/25-28/30 | [ADR-0036](docs/adr/ADR-0036-candidate-action-planner-registry.md) | — |
| ADR-0037 | Policy Bundle Authority and Constraint Merge | ACCEPTED | P1 | Runtime §§11/14/23/26/28/30 | [ADR-0037](docs/adr/ADR-0037-policy-bundle-authority.md) | — |
| ADR-0038 | Deterministic Risk Model Authority | ACCEPTED | P1 | Runtime §§12/14/26/28/30 | [ADR-0038](docs/adr/ADR-0038-deterministic-risk-model-authority.md) | — |
| ADR-0039 | Deterministic ActionScore and Conservative Defaults | ACCEPTED | P1 | Runtime §§13-14/26/30 | [ADR-0039](docs/adr/ADR-0039-deterministic-action-score.md) | — |
| ADR-0040 | Action Selection, Conflict Rules and Immutable DecisionRecord | ACCEPTED | P1 | Runtime §§11-14/26/30 | [ADR-0040](docs/adr/ADR-0040-action-selection-decision-record.md) | — |
| ADR-0041 | Selection/Reservation Atomic Bridge and Permission Boundary | ACCEPTED | P1 | Runtime §§13-14/18/26/30 | [ADR-0041](docs/adr/ADR-0041-selection-reservation-atomic-bridge.md) | ADR-0014 (Selection bridge details) |

## Migrated decisions

- Former ADR-001 was split because it mixed stack choices, protocols and implementation gates. Its valid decisions now live in ADR-0005, ADR-0008, ADR-0011, ADR-0013, ADR-0014 and ADR-0016.
- Former ADR-002, “Event-Sourced Aggregate,” is `SUPERSEDED`. It conflicted with V1.2's authoritative-state transaction. ADR-0006 defines the replacement model and ADR-0007 explicitly rejects full Event Sourcing for MVP.
- Former ADR-003's six tests are retained inside the complete [Conformance Test Specification](docs/specs/Hermes_Conformance_Test_Spec_V1.0.md), which covers all ten V1.2 §30.2 tests plus twenty fault injections.
- Former ADR-004 remains `ACCEPTED` after removing its dependency on Event Sourcing and preserving only Authority Boundary organization.

## Open decision queue

The following remain OPEN and require separate evidence-backed ADRs before being locked:

- runtime-wide implementation language and long-term supported versions beyond the first slice;
- FastAPI or another API framework;
- SQLAlchemy or another persistence mapper beyond the first slice;
- production PostgreSQL version beyond the PostgreSQL 14+ conformance baseline;
- dependency management tool;
- JSON Schema, Pydantic or another payload validator;
- Docker versus restricted Process Adapter priority;
- Kafka, Redis or another broker/cache;
- Artifact object store and Human Gate identity provider.

No runtime code, API initialization, database model or empty test is authorized merely by this index.
