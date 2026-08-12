# ADR-0023: PostgreSQL Project Runtime Roles and Event Invariant

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Runtime Invariants 1 and 4](../Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.2.md#26-runtime-invariants)

## Context

Application-layer Command handlers alone do not prevent a compromised Worker credential or an accidental SQL path from updating authoritative Project state. P0 also needs to prevent a committed Project state/version change without its Event and Outbox transaction.

## Decision

Separate the migration owner from three `NOLOGIN` capability roles:

- `hermes_control_plane_runtime`: reads authority tables and executes guarded `SECURITY DEFINER` Project mutation functions; it has no direct Project table write grant.
- `hermes_worker_runtime`: read-only Project visibility and no Event write grant.
- `hermes_read_only_runtime`: read-only Project visibility.

Deployment-specific LOGIN roles inherit exactly one capability role. Project creation and transition functions require a `control_plane` actor and use explicit parameters and conditional authority updates.

A deferred constraint trigger checks at transaction commit that each inserted or changed Project version has a matching immutable Project Event and Outbox message for the same Project, Command, version and target state. The trigger prevents state-only or Event-only commits but is not a complete recovery system.

## Consequences

The migration requires a PostgreSQL role with schema and role-management privileges. Production login credentials, password rotation, cloud IAM integration and schema placement remain deployment concerns. The schema owner remains privileged, but a state-only owner update is rejected by the deferred invariant unless the trigger is deliberately disabled by an administrator.

## Validation

Tests log in through real non-superuser roles on PostgreSQL 14 and 16. Worker/read-only roles cannot write Projects, Worker cannot insert authoritative Events, Control Plane cannot update Projects directly but can complete the guarded state/Event/Outbox transaction, and an owner state-only update fails at commit.

## Open Questions

Production Secret delivery, role rotation, managed-database role limitations and operational alerting for deliberately disabled triggers remain open.
