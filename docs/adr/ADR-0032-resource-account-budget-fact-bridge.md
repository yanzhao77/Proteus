# ADR-0032: Resource Account Budget Fact Bridge

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Core Runtime V1.2 §13](../Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.2.md#13-budget-resource-accounting)

## Context

P0 Project Guard consumes `project_budget_facts`, but P0 intentionally had no formal Resource Accounting producer. Accepting a caller-provided `budget_ok` boolean or leaving production facts directly writable would let stale or forged budget state advance a Project.

## Decision

Only the Accounting authority function may issue a production Budget Fact. It reads an authoritative ResourceAccount, binds `resource_account_id` and exact Account version, evaluates hard stop deterministically, and emits `OK` only when the Account is not in hard stop. It also binds Project/version/from/to transition context.

Every later Account version change invalidates current facts for that Account. Project Guard continues to query the referenced Fact inside its transition transaction and accepts only a current `budget_engine` `OK` fact. Worker, ordinary Control Plane, read-only and Accounting runtime roles cannot insert or update facts directly.

## Consequences

P0 fixtures may still seed Guard facts as test-only admission data. New P1 integration tests use the formal Accounting producer. Policy, Risk or scoring cannot override a hard stop because none of those inputs can create an `OK` Accounting fact.

## Validation

PostgreSQL tests prove Account version binding, invalidation after Reservation, hard-stop output, role isolation, fixed function search path and Project Guard regression behavior on PostgreSQL 14 and 16.

## Open Questions

Portfolio aggregation and multi-account transition policy remain future decisions.
