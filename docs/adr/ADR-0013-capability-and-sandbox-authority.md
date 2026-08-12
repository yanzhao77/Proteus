# ADR-0013: Capability-Based Workers and Fail-Closed Sandbox Compilation

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: ADR-0001 (registry/sandbox portion)  
Superseded by: None  
Related specifications: [Runtime Spec §19](../specs/Hermes_Runtime_Normative_Spec_V1.0.md#19-security-and-isolation)

## Context

Dynamic execution must not recreate permanent Agent departments or weaken Policy at runtime.

## Decision

Registry matches declared capabilities. SandboxProfile Compiler combines Policy, Risk mitigations, Action needs and system minimums; it may only tighten constraints and MUST fail closed if a mandatory constraint cannot be represented.

## Alternatives Considered

Fixed role departments and best-effort policy translation; rejected.

## Consequences

Constraint vocabulary and compiler conformance tests are needed before P2 execution.

## Validation

Registry schema review, forbidden-role tests and compiler property tests.

## Open Questions

Constraint vocabulary; Docker versus Process Adapter priority.
