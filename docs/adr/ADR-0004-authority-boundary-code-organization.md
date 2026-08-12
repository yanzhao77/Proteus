# ADR-0004: Organize Code by Authority Boundary

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Runtime Spec §§5-7](../specs/Hermes_Runtime_Normative_Spec_V1.0.md#5-component-responsibilities)

## Context

MVC/CRUD layering encourages generic state mutation and mixes domain authority with transport/database concerns.

## Decision

Runtime code MUST separate pure core rules, application Command/use-case orchestration, infrastructure adapters, and semantic API/read models. Core MUST NOT depend on Web, ORM, database, Docker or LLM clients. This decision does not require Event Sourcing.

## Alternatives Considered

MVC and table-oriented repositories; rejected because they obscure authority boundaries.

## Consequences

Explicit ports and mapping code are required; generic status PATCH services are forbidden.

## Validation

Dependency tests and API surface scans enforce direction and forbidden imports.

## Open Questions

Exact package names may change without changing dependency direction.
