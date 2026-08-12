# ADR-0022: Minimal P0 Project State Machine

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Core Runtime Design V1.2 §5](../Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.2.md#5-project-state-machine)

## Context

V1.2 defines the Project state set and ordered mainline but does not provide a complete edge matrix for every waiting and recovery state. P0 needs deterministic transitions without inventing the later Decision, Human Gate or Recovery protocols.

## Decision

For P0, normal advancement follows only adjacent edges in the V1.2 mainline:

```text
CREATED -> INTAKE -> DISCOVERY -> PLANNING -> DESIGNING
-> IMPLEMENTING -> VERIFYING -> HARDENING -> PACKAGING
-> DELIVERING -> ACCEPTED
```

`PAUSE`, `RESUME` and `CANCEL` are separate semantic commands. Any non-terminal mainline state may pause; resume restores only the persisted pre-pause state; cancellation requires a User or System Operator authorization reference. `ACCEPTED`, `FAILED` and `CANCELLED` are terminal.

P0 does not expose general transitions into or out of `WAITING_FOR_HUMAN`, `WAITING_FOR_RESOURCE`, `BLOCKED`, `RECOVERING` or `FAILED`. Those states remain in the schema for V1.2 compatibility but require later protocol-specific Commands.

V1.2 does not yet define a durable critical-Task selector. Therefore `VERIFYING -> HARDENING` uses the strict provable rule: the Project must have at least one Task, and every Task in that Project must be `PASSED` with a current-hash PASS VerificationResult. Tasks belonging to other Projects are ignored.

## Consequences

Callers cannot skip mainline phases or choose a resume target. The strict all-Task rule may block Projects that later classify optional Tasks; that requires a separately specified criticality model rather than an implicit default.

## Validation

Table-driven domain tests cover every mainline edge, terminal exits, invalid skips, pause/resume/cancel and the VERIFYING Task guard. PostgreSQL tests validate authority facts and concurrent Task revalidation.

## Open Questions

Critical Task selection, recovery edges, Human Gate edges and policy/evidence requirements for each early mainline phase remain open.
