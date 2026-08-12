# ADR-0024: Project Transition Guard Facts Fail Closed

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Core Runtime Design V1.2 §5.1](../Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.2.md#51-状态转移约束), [Runtime Normative Spec §8](../specs/Hermes_Runtime_Normative_Spec_V1.0.md#8-project-state-authority)

## Context

V1.2 §5.1 requires each Project transition to have sufficient Evidence, an applicable PolicyDecision, no Budget hard stop, and an applied Human Gate when Policy requires one. P0 does not implement the Policy Engine, Budget Engine, Evidence collector or full Human Gate lifecycle, but missing P1/P3 engines cannot be treated as implicit ALLOW.

## Decision

P0 introduces a minimal authoritative Guard Fact admission/read model for Project transitions. It records only facts already produced or admitted by the proper authority:

- `project_evidence_facts` from `verification_engine`.
- `project_policy_decision_facts` from `policy_engine`.
- `project_budget_facts` from `budget_engine`.
- `project_gate_decision_facts` from `human_gate`.

Each fact is bound to `project_id`, `project_version`, `from_state` and `to_state`; has a stable ID, result/status, authority, created time and validity metadata; and supports invalidation, supersede and expiry. Application handlers reload and lock these facts inside the Project transition transaction. Domain Guard receives only normalized fact summaries through `ProjectGuardContext`.

Callers may pass `supporting_refs`, but those refs are lookup hints only. A Command boolean, caller assertion or Worker self-report is never a Guard fact.

All currently opened non-cancel Project transitions require Evidence, Policy and Budget facts. A `REQUIRE_HUMAN` PolicyDecision additionally requires an `ANSWERED_APPLIED` Gate fact. `VERIFYING -> HARDENING` also requires all current Project Tasks to be `PASSED` with current-hash PASS Verification. `CANCELLED` remains a separate authorized User/System Operator command and is allowed under Budget hard stop because V1.2 §13.3 allows cancellation at hard stop.

## Consequences

Project advancement, pause and resume fail closed until the corresponding authority facts exist. This may feel strict during P0, but it prevents later P1/P3 gaps from becoming invisible default permission. Test fixtures seed formal facts directly as test-only admission data; production code does not expose a Worker-writable admission path.

## Validation

Domain tests cover missing, invalid, stale, wrong-project, denied, hard-stop and Human Gate fact cases with stable reason codes. PostgreSQL tests prove missing facts, forged refs, old versions, invalidated/superseded facts and Task PASS gaps do not advance Project state or emit applied Project events/outbox records.

## Open Questions

The complete Policy, Budget, Human Gate and Evidence producer APIs remain future P1/P3 work. V1.2 does not yet define critical Task selection; P0 still treats every Project Task as required.
