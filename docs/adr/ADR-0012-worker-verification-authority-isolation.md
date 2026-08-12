# ADR-0012: Separate Worker, Verification and State Authority

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Runtime Spec §§11,15](../specs/Hermes_Runtime_Normative_Spec_V1.0.md#11-verification-verdict-authority)

## Context

Worker self-report cannot prove correctness, while Verification must not become state authority.

## Decision

Worker produces CompletionClaim/Candidates. Verification alone produces formal verdict using independent identity/context. Control Plane alone validates verdict/hash/Evidence/version/Guard and persists Task transition.

## Alternatives Considered

Worker self-approval and Verification direct state writes; rejected for authority collapse.

## Consequences

Three interfaces and service identities are required.

## Validation

CT-006/007 and FI-13-15.

## Open Questions

Verifier trust policy by risk tier.
