# ADR-0028: VerificationPlan Version Authority and Computed Verdict

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Core Runtime V1.2 §19.2](../Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.2.md#192-verification-plan)

## Context

The first P0 slice stored free-text `criteria` on `VerificationResult`. It could not prove that criteria existed before execution, that the Result used the current revision, or that every required Check ran.

## Decision

Control Plane creates and revises immutable `VerificationPlan` versions through explicit idempotent Commands. Task authority points to current `(verification_plan_id, version)`. Revision supersedes, but does not rewrite, the prior version and competes on Task expected version.

P0 supports only `all_required_pass` and `worker_context_excluded`; unknown values fail closed. Every required Plan Check has exactly one structured result. Runtime computes aggregate verdict from required Check statuses and rejects a producer-declared mismatch. Optional Checks are retained but do not overturn `all_required_pass`.

A deferred database invariant prevents `Task.state=PASSED` unless current Artifact and active Plan are referenced by an `AUTHORITATIVE` PASS Result with every required CheckResult PASS.

## Consequences

Changing Artifact or Plan makes earlier Results inapplicable without deleting audit history. Plan create/revise atomically commits Plan, Checks, Task pointer, Event, Outbox and CommandReceipt.

## Validation

Tests cover required/optional Checks, unsupported policies, duplicate/unknown/missing Checks, aggregation mismatch, concurrent revision, old Plan rejection and direct Task PASS enforcement.

## Open Questions

Additional aggregation rules, conditional Checks, risk-tier policy and executable pass-condition language remain future decisions.
