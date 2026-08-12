# ADR-0017: Human Gate Remains Independent from Main Hermes

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Runtime Spec §12](../specs/Hermes_Runtime_Normative_Spec_V1.0.md#12-human-gate-authority)

## Context

Main Hermes presents user interaction, but allowing it to manufacture authorization or directly advance state would collapse the human-control boundary.

## Decision

Human Gate maintains versioned Gate state, authenticated user answers and resumable context independently from Main Hermes. Main Hermes may present and submit an answer but cannot impersonate the user. A Gate Answer is a fact/input; Control Plane must apply a separate guarded Command before any Project, Task or execution state changes.

## Alternatives Considered

Treat Human Gate as a Main Hermes tool or map answers directly to state transitions; rejected because user identity, authorization scope and recovery context would be bypassed.

## Consequences

Gate API/storage, user identity and Control Plane application are distinct concerns. Every OPEN Gate requires a valid `resume_context_ref`.

## Validation

CT-009, CT-010 and Gate identity/impersonation contract tests.

## Open Questions

Human identity provider and signature/assurance levels remain open.
