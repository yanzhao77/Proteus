# P1 Slice 5 Policy and Risk Acceptance Matrix

Scope: deterministic Policy Engine and Risk Engine only. Budget feasibility,
ActionScore, Action Selection and DecisionRecord were implemented later by P1
Slice 6 and are tracked in `docs/P1_ACTION_SELECTION_ACCEPTANCE_MATRIX.md`.
Human Gate lifecycle, ExecutionRequest, Scheduler, Lease/Fencing, Worker
lifecycle, SandboxProfile, Capability Registry and LLM Policy/Risk are
intentionally out of scope for this matrix.

| Requirement | Evidence | Result |
| --- | --- | --- |
| Policy Bundle versioned | `policy-bundle/1.0`, `policy-rules/1.0`, `policy_bundle_versions`, `policy_rules` | PASS |
| Risk Model versioned | `risk-model/1.0`, `risk-rules/1.0`, `risk_model_versions` | PASS |
| Policy/Risk independent authorities | separate domain modules, commands, stores, owner/runtime roles and DB functions | PASS |
| Policy outputs only ALLOW/DENY/REQUIRE_HUMAN | domain enum and DB CHECK constraint | PASS |
| Risk outputs no authorization result | RiskAssessment schema and tests scan representation for ALLOW/DENY | PASS |
| No applicable Policy rule fails closed | `test_no_rule_fails_closed` | PASS |
| Emergency DENY cannot be overridden | `test_emergency_deny_cannot_be_overridden_by_allow` | PASS |
| DENY beats Planner quality | `test_dangerous_repair_denied_despite_max_planner_quality`; CT-004 integration | PASS |
| REQUIRE_HUMAN does not create Human Gate | production repair/request_resource tests assert no gate table/record | PASS |
| Constraints only tighten | `intersect_constraints` tests for risk level, API calls, mitigations, filesystem write | PASS |
| Unknown constraint fails closed | `POLICY_CONSTRAINT_UNSUPPORTED` domain test | PASS |
| Exact current Candidate binding | PostgreSQL tests load current PlanningRun/Candidate and reject hash/version mismatch | PASS |
| Stale Planning/Situation/Candidate rejected | `POLICY_CONTEXT_STALE`, `RISK_CONTEXT_STALE`, hash mismatch tests | PASS |
| PolicyDecision immutable | immutable trigger and integration UPDATE rejection | PASS |
| RiskAssessment immutable | immutable trigger and integration UPDATE rejection | PASS |
| Idempotent retry | same key/payload returns original PolicyDecision | PASS |
| Idempotency conflict | same key/different payload returns `POLICY_IDEMPOTENCY_CONFLICT` | PASS |
| Concurrent equivalent evaluation | two Policy connections converge on one immutable result | PASS |
| Fault injection rollback | six Policy and six Risk pre-commit crash points roll back all effects | PASS |
| Event/Outbox/Receipt transaction | successful Policy/Risk tests persist Event, Outbox and applied CommandReceipt | PASS |
| Read-only diagnosis scenario | `run_deeper_test(read_only=true)` -> Policy ALLOW + LOW/MEDIUM Risk + no Reservation | PASS |
| Production repair scenario | `repair` production -> REQUIRE_HUMAN + HIGH/CRITICAL Risk + no Gate | PASS |
| Request resource scenario | `request_resource` -> REQUIRE_HUMAN, no Gate | PASS |
| Risk level boundaries | 2499/2500, 5499/5500, 7999/8000 domain tests | PASS |
| Missing risk input conservative | unknown environment raises factor and reason | PASS |
| Unverified mitigation no residual reduction | domain residual risk test | PASS |
| Verified mitigation reduces residual risk | verified mitigation test | PASS |
| Runtime permissions | non-authority roles cannot write Policy/Risk tables; Policy/Risk cannot mutate upstream/downstream or reserve | PASS |
| PUBLIC/search-path/owner hardening | PUBLIC execute revoked, owners NOLOGIN, no CREATE for runtimes | PASS |
| CT-004 authority portion | Policy DENY persists; Risk cannot change it; no Reservation/ExecutionRequest/SelectedAction | PASS |
| CT-004 Selection portion | Slice 6 `test_ct004_policy_deny_high_score_filtered_no_reservation_or_execution`; see `docs/P1_ACTION_SELECTION_ACCEPTANCE_MATRIX.md` | PASS |
| PostgreSQL 14 full regression | `Ran 256 tests ... OK` | PASS |
| PostgreSQL 16 full regression | `Ran 256 tests ... OK` | PASS |

Known GAP, explicitly deferred:

- Human Gate lifecycle and approval application;
- SandboxProfile Compiler and ExecutionRequest;
- Scheduler, Lease/Fencing and Worker lifecycle;
- dynamic Capability Registry;
- LLM Policy/Risk and free-form policy DSL.
