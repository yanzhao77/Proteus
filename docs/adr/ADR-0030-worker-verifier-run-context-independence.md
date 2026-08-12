# ADR-0030: Worker and Verifier Run/Context Independence

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Core Runtime V1.2 §19.4](../Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.2.md#194-独立性), [ADR-0012](ADR-0012-worker-verification-authority-isolation.md)

## Context

Comparing only Worker and verifier identity strings does not prevent the same run or isolation context from implementing and judging an Artifact.

## Decision

CompletionClaim stores Worker Run and context identity. Verification requires a different VERIFIER Run, prohibited-agent identity and context identity, scoped to the same Project and Task. Result verifier identity must equal VERIFIER Run identity.

Verification Engine records verdict but cannot write Task state. Control Plane reloads current Plan, Run independence, Artifact hash, Evidence and Task version before PASS/FAIL.

## Consequences

The same AgentRun or context cannot self-verify. This is a strict P0 minimum, not a full high-risk verifier selection policy.

## Validation

Tests cover wrong/same Run, shared context, identity mismatch, missing/cross-scope/invalidated verifier Runs and direct Worker/Verifier database write denial.

## Open Questions

Risk-tier organizational independence, model/provider diversity and trusted deterministic runner policy remain open.
