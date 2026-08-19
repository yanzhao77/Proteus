# P6 Recovery Runtime Least-Privilege Repair Delivery Report

> **Historical phase-local snapshot; not the current repository baseline.** **P6 Recovery Runtime Least-Privilege Repair: PASS.** This document retains the contemporaneous repair evidence and statistics. The sole current repository-wide verification authority is [`PROTEUS_E2X_P6_BASELINE_MANIFEST.md`](./PROTEUS_E2X_P6_BASELINE_MANIFEST.md).

## 1. Architecture Decision Applied

The applied invariant is that `hermes_recovery_runtime` cannot directly write authority tables, including `public.tasks`. Recovery task re-entry is authorized only through the pre-existing public Recovery commands, which run under `SECURITY DEFINER` as `hermes_recovery_owner`. The repair is forward-only: historical migration `0024` remains immutable, while `0028` revokes only the runtime role's direct `UPDATE` right.

| Principal | Before repair | After repair | Authority consequence |
| --- | --- | --- | --- |
| `hermes_recovery_runtime` | Table-wide `UPDATE public.tasks` plus command `EXECUTE` | Existing command `EXECUTE`; no table/column `UPDATE` | Cannot bypass Recovery command guards with direct DML. |
| `hermes_recovery_owner` | `SELECT, UPDATE public.tasks`; Recovery function owner | Unchanged | Retains only the function-owner authority necessary for controlled re-entry. |
| `PUBLIC` | No Recovery command execute | Unchanged | Has no Recovery authority surface. |

## 2. Files Changed

Only the approved repair paths were created or minimally updated. No commit or push was made.

| Path | Change |
| --- | --- |
| `hermes-runtime/migrations/0028_p6_recovery_runtime_least_privilege.sql` | New, single forward migration. It wraps `REVOKE UPDATE ON TABLE public.tasks FROM hermes_recovery_runtime` in a transaction. |
| `hermes-runtime/tests/test_p6_recovery_runtime_least_privilege.py` | New two-test runtime-role integration suite covering direct-DML rejection, controlled re-entry, idempotency replay and fault rollback. |
| `docs/P6_RECOVERY_PERMISSION_REPAIR_DESIGN.md` | New approved-boundary design and acceptance plan. |
| `docs/P6_RECOVERY_PERMISSION_REPAIR_DELIVERY_REPORT.md` | This delivery record. |
| `docs/P6_RECOVERY_PERMISSION_DISCREPANCY_RECON.md` | Minimal appended resolution section only; historical investigation remains intact. |

## 3. Migration Summary and Fresh Result

`0028` does not modify table ownership, role membership, function owner, function body, function signature, execute grants, task-state transitions, receipt/idempotency rules or Recovery command semantics. It creates no role, scheduler, event store or replacement authority path.

A random isolated database applied the existing migration chain continuously from `0001` through `0028`. The final post-migration verification reported `runtime_update=False`, `runtime_update_columns=0`, `owner_update=True`, and literal runtime direct-DML rejection `SQLSTATE 42501`. The isolated database was removed after verification.

## 4. Authority Evidence

| Check | Result |
| --- | --- |
| Runtime effective table `UPDATE public.tasks` | **False** after `0028`. |
| Runtime effective column `UPDATE` | **0 permitted columns**. |
| Runtime membership route | **None**; no direct membership relation involving the Recovery runtime role. |
| Literal direct-DML probe | **Rejected with `42501`** under `SET LOCAL ROLE hermes_recovery_runtime`. |
| Probe form | `UPDATE public.tasks SET state = 'PASSED' WHERE FALSE`, followed by rollback; it intentionally does not read a target column. |
| Owner `UPDATE public.tasks` | **True** for `hermes_recovery_owner`. |
| Runtime public command surface | **Exactly three** existing commands: emit feedback, plan attempt and complete attempt. |
| `PUBLIC` command surface | **None**. |
| Command owner | `hermes_recovery_owner`. |
| Command security mode | `SECURITY DEFINER = true`; hardened `search_path=pg_catalog`. |
| Function body/signature/owner/execute surface | **Unchanged**. |

## 5. Controlled Runtime Recovery Evidence

The new integration test does not use an administrator as a runtime substitute. It establishes a legal failed-execution state with the existing fixture, enters `SET LOCAL ROLE hermes_recovery_runtime`, and calls the existing `public.hermes_emit_execution_feedback(...)` command. The command successfully returns `RECOVERY_FEEDBACK_EMITTED` and re-enters the task to `READY` under owner authority.

The same test proves that feedback, recovery cycle, receipt and all three expected events commit as one authority transaction; a duplicate call returns the idempotent result without additional effects. A fault injected after feedback-record creation rolls back feedback, cycle, receipt, events and the task re-entry, leaving the task `RUNNING`. Direct literal DML is rejected both before and after command execution.

## 6. Tests Run

| Test or check | Exact result | Interpretation |
| --- | --- | --- |
| Fresh migration `0001 → 0028` | **PASS** | Migration continuity and post-revoke authority facts verified in an isolated database. |
| Original `test_recovery_permissions.py` | **4/4 PASS** | Original permission invariant is unchanged and now green. |
| Runtime-role least-privilege integration | **2/2 PASS** | Real runtime-role command execution, replay, re-entry and fault rollback verified. |
| Recovery PostgreSQL functional/fault suite | **3/3 PASS** | Existing feedback, planning, completion and rollback behavior is unchanged. |
| Combined Recovery authority suite | **9/9 PASS in 7.598 s** | Permission, runtime-role and Recovery functional evidence agrees. |
| P6 standalone autonomous acceptance | **1/1 PASS in 110.989 s** | Autonomous Trial remains functionally valid after revoke. Two pre-existing trial-harness `ResourceWarning`s appeared but did not fail the test. |
| P0–P5 no-DB standard discovery | **550 run, 324 skipped, 0 failures in 1.219 s** | Pure/runtime-independent regression baseline passes; PostgreSQL-dependent tests skip by established conditions. |
| Full Runtime regression | **550 run, 12 skipped, 0 failures in 303.482 s** | All available Runtime authority and functional tests are green. |
| Credential/secret scan of repair paths | **PASS** | No credential material or secret-like values found. |
| `git diff --check` | **PASS** | No whitespace errors in tracked changes. |

## 7. Tests Not Run

No live provider verification was run, requested or needed. The repair does not configure or invoke an external model. Frontend tests were not rerun because the repair does not modify frontend files or provider configuration; the frontend remains outside this approved scope. Twelve full-regression tests remain explicitly skipped because their external prerequisites—real OTLP endpoint, real Docker or Vault—were not supplied. These skips are established test conditions and no failure was hidden, skipped or marked expected by this repair.

## 8. Protected-Path Audit

The audit confirms that `0024_p6_autonomous_trial_runtime.sql`, all other historical migrations, `tests/test_recovery_permissions.py`, Recovery production function code, P6 trial driver, E1/E2/E2.x implementation and `frontend/` were not modified by the repair. Only `0028` is the new migration. A pre-existing modified `fastapi_app.py` remains in the wider worktree; it is unrelated to and untouched by this P6 repair, and must not be attributed to it.

## 9. Final Status

| Status dimension | Final status |
| --- | --- |
| P6 Recovery Runtime Least-Privilege Repair | **PASS** |
| P6 Functional Revalidation | **PASS** |
| P6 Authority Gate | **CLOSED** |
| P6 Phase | **COMPLETE / REVALIDATED** |
| E2.x Final Acceptance Correction | **PASS** — unchanged |
| E2.x Live Provider Verification | **BLOCKED / NOT RUN** — unchanged |
| E2.x Phase | **NOT COMPLETE** — unchanged; no live-provider evidence exists |

## 10. Remaining Risks and Stop Conditions

The repair removes the known runtime direct-task-update path but does not replace the need for future external-integration verification where those test prerequisites are intentionally absent. The P6 task did not configure or call a provider, alter the frontend, alter E1/E2/E2.x, add a second migration, change Recovery function behavior, change role membership, weaken a test, or modify a historical migration. No stop condition was encountered after the approved repair path began.

## References

[1]: ./P6_RECOVERY_PERMISSION_REPAIR_DESIGN.md "P6 Recovery Runtime Least-Privilege Repair Design"
[2]: ./P6_RECOVERY_PERMISSION_DISCREPANCY_RECON.md "P6 Recovery permission discrepancy reconciliation"
[3]: ../hermes-runtime/migrations/0028_p6_recovery_runtime_least_privilege.sql "Forward migration 0028"
[4]: ../hermes-runtime/tests/test_p6_recovery_runtime_least_privilege.py "Runtime-role least-privilege integration test"
[5]: ../hermes-runtime/tests/test_recovery_permissions.py "Original Recovery permission regression"
