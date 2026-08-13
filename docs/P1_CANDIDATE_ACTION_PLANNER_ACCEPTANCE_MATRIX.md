# P1 Slice 4 Candidate Action Planner Acceptance Matrix

Scope: deterministic Candidate Action Planner and versioned Action Registry only.
Policy, Risk, Budget feasibility filtering, Action Selection, ExecutionRequest,
Scheduler, Lease/Fencing, Worker lifecycle, Human Gate, dynamic Capability
Registry, SandboxProfile and LLM Planner are intentionally out of scope.

| Requirement | Evidence | Result |
| --- | --- | --- |
| Versioned Action Registry | `action-registry/1.0`, `planner-rules/1.0`, `resource-estimator/1.0` in `domain/planner.py` and `action_registry_versions` | PASS |
| Disabled and unknown Action types fail closed | `registry_entry()` rejects disabled `human_gate` and unknown types | PASS |
| Candidate only, no authorization/selection/lease state | Domain tests scan registry; schema has no allowed/selected/queued/leased fields | PASS |
| Exact OPEN Situation binding | `PlanCandidates.expected_situation_version`; `hermes_apply_planning_run` locks `situations` and rejects stale/non-OPEN rows | PASS |
| Frozen AnalysisContext binding | command carries Context ID/hash; DB validates `analysis_contexts.context_hash` | PASS |
| Current Diagnosis binding when required | `verification_failed` requires current Diagnosis ID/input hash and matching Situation version/Context hash | PASS |
| Diagnosis forbidden when not required | `work_available` with forged Diagnosis is rejected with `PLANNER_DIAGNOSIS_NOT_ALLOWED` | PASS |
| UNKNOWN Diagnosis rules | PostgreSQL and domain tests produce `run_deeper_test`/`diagnose` and no `repair` | PASS |
| PROBABLE Diagnosis rules | Domain tests keep evidence alternative and allow conservative mapped `repair` only | PASS |
| CONFIRMED Diagnosis rules | Domain and PostgreSQL tests produce mapped `repair`, `retry`, `switch_strategy` and evidence alternative | PASS |
| READY Task rule | `work_available` creates one `schedule_ready_task` candidate with `creates_execution_request=false` | PASS |
| Stale Task target fails closed | non-READY Task rejects with `PLANNER_TARGET_STALE` | PASS |
| Budget HARD_STOP rule | PostgreSQL test produces only `request_resource` and `pause`, with ResourceAccount unchanged | PASS |
| ResourceEstimate vs Reservation boundary | candidates store integer `estimated_resources`; Planner tests verify no reservation/balance mutation | PASS |
| Candidate quality | each candidate has reason, target, capability, precondition, expected output and positive progress or evidence gain | PASS |
| Candidate count and single-candidate reason | 1-5 enforced in DB; `schedule_ready_task` records `ONLY_ONE_REGISTRY_CANDIDATE_VALID` | PASS |
| Stable input hash, PlanningRun ID and Action IDs | domain determinism tests reorder Hypotheses/Evidence Requests and assert identical IDs/hashes | PASS |
| Stable ordering and dedupe | canonical content hash and deterministic priority/evidence/progress/content sort | PASS |
| Immutable PlanningRun/CandidateAction history | immutable triggers reject UPDATE/DELETE on planning history tables | PASS |
| Idempotent retry | same idempotency key/payload returns same PlanningRun | PASS |
| Idempotency conflict | same key/different payload rejects with `PLANNER_IDEMPOTENCY_CONFLICT` | PASS |
| Concurrent equivalent planning | two connections converge on one equivalent PlanningRun | PASS |
| Fault injection rollback | six pre-commit Planner crash points roll back PlanningRun, CandidateAction, Event, Outbox and Receipt effects | PASS |
| Commit-ack retry | retry after successful commit returns original PlanningRun | PASS |
| Event/Outbox/Receipt transaction | successful `action.candidates_planned` commits with Outbox and applied CommandReceipt | PASS |
| PostgreSQL authority role | dedicated `hermes_planner_owner` NOLOGIN owns planning tables/functions | PASS |
| Runtime permissions | worker/verifier/situation/diagnosis/accounting/control roles cannot directly write planning tables | PASS |
| Planner cannot mutate upstream/downstream authority | planner runtime cannot update Situation/Diagnosis/Project/Task/Artifact/Evidence/ResourceAccount or create ResourceReservation/object shadow | PASS |
| PUBLIC and search path hardening | PUBLIC execute revoked; SECURITY DEFINER uses `search_path = pg_catalog`; shadowing fails | PASS |
| PostgreSQL 14 full regression | `Ran 226 tests ... OK` | PASS |
| PostgreSQL 16 full regression | `Ran 226 tests ... OK` | PASS |

Enabled Action types in `action-registry/1.0`:

- `diagnose`
- `run_deeper_test`
- `repair`
- `retry`
- `switch_strategy`
- `schedule_ready_task`
- `request_resource`
- `pause`

Disabled Action types in this slice:

- `switch_agent`: awaits formal Worker lifecycle and capability routing.
- `expert_review`: awaits Human/Expert authority and Policy boundary.
- `replan`: awaits broader Planning authority beyond local CandidateAction generation.
- `rollback`: awaits authoritative rollback-plan production and validation.
- `human_gate`: awaits formal Human Gate/Policy authority.

Known GAP, explicitly deferred:

- PolicyDecision and RiskAssessment;
- Budget feasibility filtering and ResourceReservation;
- Action scoring, Selection and DecisionRecord;
- ExecutionRequest, Scheduler, Lease/Fencing and Worker assignment;
- dynamic Capability Registry and SandboxProfile Compiler;
- LLM-based planning or free-text command generation;
- rollback and Human Gate workflows.
