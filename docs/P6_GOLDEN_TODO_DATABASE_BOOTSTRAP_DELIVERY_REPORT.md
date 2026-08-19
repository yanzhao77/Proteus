# P6 Golden Todo Disposable Database Bootstrap Delivery Report

> **Final verdict:** **P6 Bootstrap Cleanup Authenticity Closure: PASS.** A disposable Todo database can now be removed only by the factory-issued instance that recorded its validated name, PostgreSQL OID, and owner. The public evidence dictionary is audit output only and cannot authorize a destructive action. [`PROTEUS_E2X_P6_BASELINE_MANIFEST.md`](./PROTEUS_E2X_P6_BASELINE_MANIFEST.md) is the sole Current Verification Authority.

## 1. Delivered Closure

The previous bootstrap contract already enforced a unique role-owned target, Todo `public CREATE`, strict target names, and fail-closed wrong-owner handling. This closure removes the remaining identity gap: matching public `name` and `evidence["database_name"]` no longer suffice for cleanup authorization.

| Concern | Closed implementation |
| --- | --- |
| Factory authenticity | A module-private capability is present only in objects issued by `create_disposable_todo_database(...)`. |
| Immutable creation record | Private authorization stores validated database name, PostgreSQL OID, and owner. |
| Public evidence | Contains audit-safe fields only; changing it cannot redirect cleanup authorization. |
| Pre-connection protection | Name, factory capability, OID/owner record completeness, and instance integrity are checked before an admin connection. |
| Pre-DROP verification | Catalog query verifies current name/OID/owner before termination or quoted `DROP DATABASE`. |
| Same-name replacement | OID mismatch fails closed; the new target remains present. |
| Owner change | Owner mismatch fails closed; target remains present. |
| Repeated cleanup | A legitimate factory-issued instance treats an absent original database as completed cleanup. |

## 2. Cleanup Authorization Model

The factory reads catalog `oid` and `datdba` immediately after `CREATE DATABASE <name> OWNER <todo-role>`. It then creates a `DisposableTodoDatabase` with a private immutable authorization record. Normal callers retain the same compatible surface—`create_disposable_todo_database(...)`, `runtime_todo_dsn`, and `cleanup()`—but public construction produces no private capability and cannot pass cleanup preconditions.

`cleanup()` first validates the public name but uses the private record as its authority. It then performs a parameterized catalog lookup. Only exact match of catalog name, OID, and owner permits parameterized session termination and `psycopg.sql.Identifier`-quoted `DROP DATABASE`. There is no wildcard, prefix batch delete, shared-database cleanup, or evidence-driven authorization.

## 3. Evidence Matrix

| Scenario | Result | Destructive effect |
| --- | --- | --- |
| Manual object with matching public evidence | Rejected before admin connection | None |
| Public evidence modified to another instance | Original private target only is removed | Other instance remains |
| Public `name` changed | Rejected before admin connection | None |
| Original database deleted | Second cleanup completes | None |
| Original name recreated | OID mismatch rejected | Replacement remains |
| Original owner changed | Owner mismatch rejected | Target remains |
| Wrong owner with explicit Todo `CREATE` | Helper and Golden fixture reject | Owner/ACL/membership unchanged |
| Cross-instance cleanup | First cleanup leaves second database available | Only first target removed |

## 4. Verification Record

| Command class | Exact result |
| --- | --- |
| Cleanup-authenticity/bootstrap PostgreSQL/Golden Todo suite | **13/13 PASS** in `2.830 s`; includes manual forged instance, public evidence/name mutation, OID replacement, owner mismatch, wrong-owner-with-`CREATE`, direct Golden Todo **9/9**, cross-instance isolation, and idempotent cleanup. |
| P6 Recovery permission/runtime-role suite | **6/6 PASS** in `3.777 s`. |
| P6 standalone / fresh `0001 → 0028` | **1/1 PASS** in `105.839 s`; no `todo_p6_ci_*` residue. |
| Focused E1/E2/E2.x/FH-1/FastAPI/OIDC/Product API suite | **86/86 PASS** in `4.309 s`. |
| P0–P5 no-DB discovery | **575 run, 333 skipped, 0 failures** in `1.280 s`. |
| Full Runtime regression | **575 run, 12 skipped, 0 failures** in `293.539 s`. |
| Frontend Vitest/build/lint | **33/33 PASS** in `1.33 s` / PASS in `342 ms` / `0` warnings and `0` errors. |

The two existing P6 harness `ResourceWarning` messages remain visible, non-failing warnings. They were not hidden, skipped, or reclassified.

## 5. Protected-Path and Security Audit

Only the test-only bootstrap helper, its narrow integration tests, and approved documentation were changed by this closure. No migration, P6 Recovery authority surface, role, grant, `SECURITY DEFINER` function, authority test, Worker/Verifier/Scheduler/Execution semantic, Golden Todo application/API assertion, E1/E2/E2.x production semantic, frontend, provider configuration, or Docker production topology changed.

The final reseal performs SHA-256 verification for every manifest entry, `git diff --check`, scoped secret scan, current-versus-historical document scan, and an explicit no-residue query. No external provider/network call, dependency install, commit, or push occurred.

## 6. Final Status

| Dimension | Status |
| --- | --- |
| P6 Bootstrap Cleanup Authenticity Closure | **PASS** |
| Final Baseline Statistic Authority Closure | **PASS** |
| P6 Recovery Least-Privilege Repair | **PASS** |
| P6 Authority Gate | **CLOSED** |
| P6 Functional Revalidation | **PASS** |
| P6 Phase | **COMPLETE / REVALIDATED** |
| E2.x Repository/Internal Delivery | **PASS** |
| E2.x Live Provider Verification | **BLOCKED / NOT RUN** |
| E2.x Phase | **NOT COMPLETE** |

## References

[1]: ./P6_GOLDEN_TODO_DATABASE_BOOTSTRAP_DESIGN.md "Cleanup authenticity design"
[2]: ./PROTEUS_E2X_P6_BASELINE_MANIFEST.md "Current Verification Authority"
[3]: ../hermes-runtime/tests/test_p6_todo_database_bootstrap.py "Cleanup authenticity tests"
