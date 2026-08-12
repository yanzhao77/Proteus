# ADR-0001: Mixed MVP Stack and Infrastructure Baseline

Status: SUPERSEDED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: ADR-0005, ADR-0008, ADR-0011, ADR-0013, ADR-0014, ADR-0016  
Related specifications: [Runtime Spec](../specs/Hermes_Runtime_Normative_Spec_V1.0.md)

## Context

The former root ADR-001 combined Python, PostgreSQL, Outbox, Lease, Capability Registry, Sandbox and implementation planning in one accepted decision.

## Decision

This mixed decision is superseded. Its valid protocol constraints are split into single-topic ADRs. Python, FastAPI, SQLAlchemy, versions and dependency management remain OPEN unless separately decided.

## Alternatives Considered

Retain the combined ADR; rejected because unrelated choices could not evolve independently.

## Consequences

No implementation may cite this ADR as authority. Historical rationale remains traceable.

## Validation

ADR index links each extracted decision and marks this record SUPERSEDED.

## Open Questions

Language/framework/version choices remain open.
