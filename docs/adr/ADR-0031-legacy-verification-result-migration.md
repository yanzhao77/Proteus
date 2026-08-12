# ADR-0031: Legacy VerificationResult and Run Reference Migration

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Runtime Normative Spec §15](../specs/Hermes_Runtime_Normative_Spec_V1.0.md#15-verificationresult-to-task-transition)

## Context

Pre-0006 Results contain free-text criteria and no Plan or VerifierRun. Existing CompletionClaim `run_id` values have no proven authority. Manufacturing Plans or Runs would turn unproven history into authorization.

## Decision

Migration 0006 marks existing Results `LEGACY`. Only guarded writes with Plan/version, VERIFIER Run and structured CheckResults are `AUTHORITATIVE`; Task PASS/FAIL rejects legacy rows.

CompletionClaim-to-AgentRun foreign key is installed `NOT VALID`: PostgreSQL enforces it for every new row without pretending historical strings are valid. Operators must audit history before separately validating it. Existing Event IDs, Result IDs and audit records remain unchanged.

## Consequences

Historical records remain readable and immutable but cannot authorize new state. Production migration needs an explicit inventory/remediation window.

## Validation

Tests insert a legacy free-text PASS Result and prove it cannot transition Task state. Migration replay runs on PostgreSQL 14 and 16.

## Open Questions

Production inventory tooling, retention and whether any historical Result can be externally attested remain deployment decisions.
