# P1 Slice 6 Action Selection Acceptance Matrix

Scope: Budget feasibility, deterministic ActionScore, Action Selection,
immutable DecisionRecord and atomic ResourceReservation. This slice stops at
selected execution intent with required resources reserved. Human Gate lifecycle,
ExecutionRequest, Scheduler, Lease/Fencing, Worker lifecycle, SandboxProfile,
Capability Registry, Agent execution coupling, FastAPI and LLM Selection remain
out of scope.

| Requirement | Implementation evidence | Test evidence | PostgreSQL 14 | PostgreSQL 16 | Status |
| --- | --- | --- | --- | --- | --- |
| Explicit Selection authority | `ActorType.ACTION_SELECTION`, `SelectActions`, `PostgresSelectionStore`, `hermes_selection_owner/runtime` | `test_selection_permissions.py` | PASS | PASS | PASS |
| Command excludes caller score/selected/budget_ok | `SelectActions` fields only include identity, freshness, weight profile and account bindings | domain/application shape tests via full discovery | PASS | PASS | PASS |
| Policy DENY filters before score | `_policy_risk_filter` returns `POLICY_DENY` before score; no `ScoreResult` | `test_policy_deny_filters_before_score_and_no_reservation`, `test_ct004_policy_deny_high_score_filtered_no_reservation_or_execution` | PASS | PASS | PASS |
| REQUIRE_HUMAN filtered without Gate forgery | `POLICY_REQUIRE_HUMAN`; no Gate creation path | `test_require_human_candidate_is_filtered_without_gate` | PASS | PASS | PASS |
| Risk is not authorization | Selection only compares Risk facts against Policy constraints | domain risk constraint tests; Policy/Risk regression suite | PASS | PASS | PASS |
| Policy/Risk freshness and binding | DB function validates current PlanningRun/Candidate/Policy/Risk hashes and versions | stale context tests in `test_selection_postgres.py` and upstream Policy/Risk tests | PASS | PASS | PASS |
| Budget reads locked ResourceAccount | stable account-ID locking and DB-side balance/version validation | budget scope/currency/HARD_STOP/infeasible/version tests | PASS | PASS | PASS |
| Budget feasibility uses `estimate <= limit - consumed - reserved` | `_budget_filter` and SQL bridge validate dimensions and available balance | `test_budget_scope_currency_hard_stop_infeasible_and_version_conflicts` | PASS | PASS | PASS |
| Zero-resource action creates no fake Reservation | explicit zero estimate can be selected without reservation | `test_budget_and_zero_resource`; integration zero-resource case | PASS | PASS | PASS |
| Twelve resource dimensions enforced | shared `RESOURCE_DIMENSIONS` and SQL dimension checks inherited from Accounting | full regression including Accounting tests | PASS | PASS | PASS |
| Deterministic ActionScore | `selection-weight-profile/1.0`, `selection-normalizer/1.0`, canonical score input hash | `test_score_has_eight_integer_dimensions_and_default_history` | PASS | PASS | PASS |
| Conservative historical default | `DEFAULT_NO_HISTORY = 3500`; default source recorded | domain score test | PASS | PASS | PASS |
| Stable snapshot under input reorder | canonical JSON sorted candidates | `test_input_order_does_not_change_snapshot_or_selection` | PASS | PASS | PASS |
| Stable tie-break | final score, lower residual risk, higher reversibility, lower cost, action ID | `test_selection_domain.py` ranking tests | PASS | PASS | PASS |
| Conflict fail-closed | `selection-conflict-rules/1.0`; unknown/mutable/project-global conflicts | `test_conflict_rules_allow_readonly_and_filter_mutable_target` | PASS | PASS | PASS |
| Compatible multi-selection | read-only compatible actions can both be selected up to max parallel 2 | domain and PostgreSQL multi-action tests | PASS | PASS | PASS |
| Aggregate budget cannot partially reserve | DB transaction and fault injection prevent partial multi-reservation commit | multi-action/fault injection tests | PASS | PASS | PASS |
| Immutable DecisionRecord | immutable tables/triggers and current head pointer only | immutable update/delete rejection tests | PASS | PASS | PASS |
| Empty selection still records DecisionRecord | `NO_ELIGIBLE_ACTION` result with dispositions | `test_no_eligible_action_is_explained`; integration empty-selection test | PASS | PASS | PASS |
| Decision/Reservation/Event/Outbox/Receipt same transaction | `hermes_apply_selection_decision` commits all authority records together | happy path counts and fault injection rollback tests | PASS | PASS | PASS |
| `budget.reserved` emitted for reservations | SQL bridge appends budget event/outbox per selected reservation | integration event checks | PASS | PASS | PASS |
| `decision.recorded` emitted | SQL bridge appends decision event/outbox | happy path event/outbox checks | PASS | PASS | PASS |
| Idempotent retry | same key/payload returns original response | `test_idempotency_convergence_and_concurrency` | PASS | PASS | PASS |
| Idempotency conflict | same key/different payload rejects | `test_idempotency_convergence_and_concurrency` | PASS | PASS | PASS |
| Commit-ack retry convergence | new key over active equivalent decision returns original decision without duplicate reservation | convergence branch in `PostgresSelectionStore` and retry tests | PASS | PASS | PASS |
| Concurrent budget competition does not oversell | DB locks and version checks serialize selection/reservation | concurrency test with multiple connections | PASS | PASS | PASS |
| Runtime permissions | runtime can call guarded function but cannot write tables or shadow objects | `test_selection_permissions.py` | PASS | PASS | PASS |
| PUBLIC hardening | sensitive function execute revoked; runtime no schema create | permission tests and migration grants | PASS | PASS | PASS |
| No ExecutionRequest or execution events | no execution table creation; tests assert zero `execution.queued/requested` | CT-004 and scan | PASS | PASS | PASS |
| PostgreSQL 14 full regression | full `unittest discover` with PostgreSQL 14 | `Ran 275 tests ... OK` | PASS | — | PASS |
| PostgreSQL 16 full regression | full `unittest discover` with PostgreSQL 16 | `Ran 275 tests ... OK` | — | PASS | PASS |

## Known GAP, explicitly deferred

- Human Gate lifecycle and authorization application.
- ExecutionRequest, queue, Scheduler, Lease/Fencing, heartbeat and Worker
  assignment.
- SandboxProfile Compiler and dynamic Capability Registry.
- Real AgentRun execution coupling and completion settlement coupling.
- FastAPI, Kafka, Redis, Kubernetes and P2/P3 distributed infrastructure.
- LLM-based Selection or learned historical-success authority.
