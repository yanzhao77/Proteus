# ADR-0003: Initial Six-Test Architecture Gate

Status: SUPERSEDED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: Hermes Conformance Test Specification V1.0  
Related specifications: [Conformance Test Spec](../specs/Hermes_Conformance_Test_Spec_V1.0.md)

## Context

The former root ADR-003 defined six initial architecture tests but did not cover all V1.2 §30.2 scenarios or the required fault injections.

## Decision

The six tests remain useful but are superseded as the complete gate by CT-001 through CT-010 and FI-01 through FI-20.

## Alternatives Considered

Keep six tests as the whole conformance baseline; rejected as incomplete.

## Consequences

Phase claims follow the Conformance Test Specification. Empty or skipped blocking tests are not passes.

## Validation

Automated documentation checks count all 10 CT and 20 FI identifiers.

## Open Questions

CI fault-injection provisioning remains open.
