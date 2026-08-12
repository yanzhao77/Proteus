# ADR-0016: No Premature Distributed Infrastructure in MVP

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: ADR-0001 (implementation scope portion)  
Superseded by: None  
Related specifications: [Runtime Spec §2](../specs/Hermes_Runtime_Normative_Spec_V1.0.md#2-authority-and-scope)

## Context

V1.2 needs protocol correctness, not infrastructure breadth.

## Decision

MVP MUST NOT require Kafka, Kubernetes, Raft/custom consensus, cross-region active-active, cross-database distributed transactions, graph database or many microservices. New middleware requires evidence and a separate ADR.

## Alternatives Considered

Adopt a distributed stack upfront; rejected as unproven complexity.

## Consequences

PostgreSQL and a modular Control Plane can implement MVP; transport/framework remain replaceable.

## Validation

Dependency and deployment review; any listed middleware requires an accepted superseding ADR.

## Open Questions

Measured thresholds that would justify a broker or orchestration platform.
