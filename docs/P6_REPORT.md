# P6 Autonomous Production Trial — Final Report

Overall verdict: **PASS** — Proteus took a real Natural Language Software
Request through a complete autonomous production lifecycle using only its real
authority chain: Request -> Situation -> Diagnosis -> Planning -> Policy/Risk ->
Action Selection -> Execution -> Evidence -> Verification -> Failure Detection ->
Recovery/Replan -> Human Gate (when required) -> Final Verification -> Software
Delivery (ACCEPTED).

Evidence: [acceptance-matrix.md](evidence/p6/acceptance-matrix.md) (all rows
PASS), [run-*/](evidence/p6/) bundles, tests/test_p6_autonomous_trial.py.

## 1. Runs

- **Happy path** (run-happy-path-run1): 1 autonomous run, 2 real worker
  executions, 1 genuine failure, 111 events recorded, project **ACCEPTED**,
  task **PASSED**.
- **Scenario A** verification failure recovered (initial implementation
  genuinely fails and is repaired) — part of the happy path (real pytest FAIL).
- **Scenario B** worker crash: 1 worker SIGKILLed mid-run, lease relinquished,
  request requeued and re-acquired, re-run (attempt 2) succeeded, task PASSED.
- **Scenario C** duplicate execution: same command + idempotency key resubmitted
  -> identical receipt, exactly one authority row.
- **Scenario D** artifact tampering: produced file mutated on disk -> independent
  verifier failed it closed (ARTIFACT_HASH_MISMATCH), task FAILED, no fake PASS.
- **Scenario E** human gate: project paused (WAITING_FOR_HUMAN) and resumed via
  real HumanGateAuthority + real resume-guard facts.

## 2. Failures injected (all real, none mocked)

- Real pytest failure in the golden worker (broken test mutation).
- Real SIGKILL of the worker subprocess mid-run.
- Real on-disk mutation of a produced artifact.
- Real REQUIRE_HUMAN policy gate.

## 3. Recoveries that really ran

- Execution-result failure -> recovery.emit_execution_feedback (task re-entry
  inside the recovery transaction) -> plan_recovery_attempt -> repair
  execution -> complete_recovery_attempt (SUCCEEDED).
- Worker crash -> lease relinquish (request requeued) -> re-acquire -> re-run.

## 4. Replans that really ran

- verification_failed situation -> real DiagnosisEngine (root cause
  test_assertion_failure) -> real ActionPlanner repair candidate -> full freeze
  chain re-executed through the real planner/policy/risk/selection/capability.

## 5. Human interventions

- Exactly one (scenario E), exercised through the real HumanGateAuthority:
  authorized approver submitted an APPROVE decision; the project resumed.

## 6. Final project

- Happy path project reached **ACCEPTED** through 10 real guard-fact-bound
  transitions (evidence/policy/budget facts produced by the P6 authority
  commands; migration 0023).
- Golden Project delivered: examples/golden-todo (FastAPI + SQLAlchemy +
  PostgreSQL + JWT + pytest + Docker Compose), 9/9 pytest tests PASS,
  independently verified by the golden verifier subprocess.

## 7. Evidence paths

- docs/evidence/p6/acceptance-matrix.md + acceptance-matrix.json
- docs/evidence/p6/run-{happypath,worker-crash,duplicate-ex,artifact-tampering,human-gate}-run1/
  each with request/situation/diagnosis/planning/policy/selection/execution/
  verification/recovery/delivery JSON + events.json + artifacts.json +
  run-report.md.

## 8. Test results

- P6 integration test (tests/test_p6_autonomous_trial.py): PASS (all 8
  acceptance rows).
- P0-P5 regression: no-DB 506 tests OK (307 skipped); PostgreSQL 16 full
  regression 187 tests OK; compileall PASS.
- Migration continuity: 0001..0024 applied cleanly on a fresh database.

## 9. Remaining risks

- The lease lifetime is bounded (default profile 5 minutes); very long
  executions would need lease-profile tuning or renewal beyond 60 renewals.
- A verification-only FAIL with no failed execution result still requires the
  recovery re-entry path (documented boundary; the tamper scenario uses the
  fail-closed path).
- The sk- secret-guard tightening is behaviorally identical for real API
  keys but should be re-reviewed before release.
- The situation consumer now quarantines unimplemented-rule events; the
  classifier itself still fails closed (P1 contract preserved).

## 10. Next-phase suggestions

- Expose the trial as an API route (Software Request submission surface) so a
  user can submit a request and observe the run live (P6 recon answer A).
- Add a run/session aggregate for run identity + progress observability.
- Wire the golden worker to real Docker (the runtime has a production Docker
  execution authority, migration 0022) for containerized builds.
- Extend scenario coverage: retry exhaustion -> human gate handoff, budget
  hard-stop replan, scheduler takeover after lease expiry.
- Hook the P6 trial into the hermes-p6.yml CI (already added) with the
  golden-todo role/database bootstrap.

## Runtime gap closures (ADR-0073)

See P6_AUTONOMOUS_PRODUCTION_TRIAL_PLAN.md section 9 for the five minimal,
authority-conforming closures (implement action / registry 1.1, recovery task
re-entry, work_graph readiness classification, consumer liveness on
unimplemented rules, secret-guard tightening). All P0-P5 tests still pass; no
authority invariant or API contract changed.
