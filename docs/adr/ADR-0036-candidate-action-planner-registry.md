# ADR-0036: Candidate Action Planner and Versioned Action Registry

- Status: ACCEPTED
- Phase: P1
- Related specifications: Core Runtime Design V1.2 §§10-14, 19-21, 25-28, 30; Command/Event Protocol §§4-6; ADR-0014; ADR-0033; ADR-0034; ADR-0035

## Context

Action Planner is the first component after Situation and Diagnosis that can
enumerate possible next work. If it chooses, authorizes, reserves resources,
creates an ExecutionRequest, or treats free text as executable intent, it collapses
the V1.2 boundary between planning, Policy, Risk, Budget and Selection.

P1 Slice 4 therefore needs a deterministic CandidateAction generator that binds
to exact upstream authority versions while remaining intentionally non-executing.

## Decision

`action-registry/1.0`, `planner-rules/1.0` and `resource-estimator/1.0` define the
first deterministic Action Planner rule set. The enabled Action types are:

- `diagnose`
- `run_deeper_test`
- `repair`
- `retry`
- `switch_strategy`
- `schedule_ready_task`
- `request_resource`
- `pause`

The following V1.2 Action types remain disabled in this slice: `switch_agent`,
`expert_review`, `replan`, `rollback` and `human_gate`. They require later Policy,
Human Gate, rollback-plan, Worker lifecycle, or broader planning authorities that
do not exist yet.

Each registry entry declares supported Situation types, Diagnosis requirement
(`REQUIRED`, `OPTIONAL` or `FORBIDDEN`), allowed root-cause statuses, capability
requirements, parameter schema version, preconditions, expected outputs, default
reversibility, estimator identity, evidence-gain rule, target-derivation rule and
enabled state. Unknown or disabled Action types fail closed.

The Planner produces immutable `PlanningRun` and `CandidateAction` records. Every
PlanningRun binds to project, Situation ID/version, frozen AnalysisContext ID/hash,
optional current Diagnosis ID/input hash, registry version, planner rule version,
resource estimator version and canonical `input_hash`. Every CandidateAction binds
back to the same scope and stores stable target refs, required capabilities,
parameters, expected outputs, preconditions, deterministic ResourceEstimate,
confidence/progress/evidence-gain/reversibility basis points, ordinal and
canonical content hash.

CandidateAction is not a PolicyDecision, RiskAssessment, SelectedAction,
ResourceReservation, ExecutionRequest, queue item, lease, Worker assignment or
Human Gate request. `ResourceEstimate` is only an estimate and never mutates
ResourceAccount state.

The PostgreSQL authority uses `hermes_apply_planning_run` to lock/load the current
OPEN Situation, validate frozen Context, validate exact current Diagnosis when
required, persist PlanningRun/CandidateActions/child records, update the controlled
`current_planning_runs` pointer, append `action.candidates_planned`, insert Outbox
and finalize CommandReceipt in one local transaction.

## Consequences

- `verification_failed` requires the exact current Diagnosis for the Situation
  version and Context hash.
- `work_available` forbids Diagnosis and can only produce
  `schedule_ready_task` when the Task remains authoritative `READY`.
- `budget_pressure` can produce `request_resource`, `pause` and, for `WARN`,
  lower-cost `switch_strategy` candidates without changing budget state.
- `UNKNOWN` Diagnosis produces evidence-gathering candidates and no concrete
  repair.
- `PROBABLE` Diagnosis may include conservative repair only for mapped structured
  root causes and keeps an evidence alternative.
- `CONFIRMED` Diagnosis may include mapped repair, retry, switch strategy and
  evidence alternatives.
- Duplicate and concurrent equivalent Planning commands converge on one immutable
  PlanningRun.
- Historical PlanningRuns remain immutable; a current pointer is only a controlled
  view for downstream stale detection.
- LLM Planner, Policy, Risk, Budget feasibility filtering, Selection,
  ExecutionRequest, Scheduler, Lease/Fencing, dynamic Capability Registry,
  SandboxProfile, Human Gate and full P2/P3 execution coupling remain future work.
