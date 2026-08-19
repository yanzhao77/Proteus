# P6 Golden Todo Disposable Database Bootstrap Design

> **Decision.** Each P6 standalone trial creates one uniquely named disposable PostgreSQL database owned by the Todo application role and requiring Todo `CREATE` in `public`. Its cleanup authority is not derived from public audit evidence: only a **factory-issued instance** that holds a private name/OID/owner creation record may terminate sessions or drop that database. Repository-wide current verification statistics are authoritative only in [`PROTEUS_E2X_P6_BASELINE_MANIFEST.md`](./PROTEUS_E2X_P6_BASELINE_MANIFEST.md).

## 1. Scope and Authority Boundary

The repaired PostgreSQL 16 test environment must not use a shared `todo_test` owner or a shared-schema grant as a substitute for correct ownership. The test-only lifecycle instead creates `todo_p6_ci_<suffix>` with `OWNER <todo-role>`. Existing targets require both exact Todo ownership and Todo `public CREATE`; a wrong owner is invalid even if an explicit `CREATE` grant exists.

This design does not modify migrations, P6 Recovery roles/grants/functions, Worker/Verifier/Scheduler/Execution behavior, Golden Todo `app/**`, Golden Todo API assertions, E1/E2/E2.x production semantics, frontend, provider configuration, or Docker production topology.

| Required boundary | Contract |
| --- | --- |
| Database target | Validated `todo_p6_ci_<ascii lowercase/digit/underscore suffix>` identifier only. |
| New owner | Exact Todo application role, existing and non-superuser. |
| Existing target | Exact Todo owner **and** Todo `public CREATE`; otherwise stable `GOLDEN_TODO_TEST_DATABASE_BOOTSTRAP_INVALID`. |
| Shared repairs | Forbidden: no owner alteration, shared `GRANT`, role membership change, or migration change. |
| Cleanup authority | Private factory record, not public evidence. |

## 2. Single Target-Name Contract

`validate_database_name()` is the single authority for generated targets, URL replacement, lifecycle creation, existing-target validation, and cleanup. It accepts only a non-empty suffix after `todo_p6_ci_`, ASCII lowercase letters/digits/underscores, and a PostgreSQL-safe maximum identifier length of 63. It rejects prefix-only values, reserved database names, path separators, quotes, whitespace, control characters, uppercase characters, Unicode look-alikes, and overlength values.

The value is never normalized into a safe replacement. Target validation occurs before an administrator connection in cleanup; an invalid or public-name-tampered instance therefore cannot terminate a session or issue `DROP DATABASE`.

## 3. Factory-Issued Cleanup Authorization

After `CREATE DATABASE <name> OWNER <todo-role>`, the helper immediately obtains the database catalog OID and owner and issues the sole compatible `DisposableTodoDatabase` object through a module-private factory. The object retains an immutable private `_CleanupAuthorization` record containing the validated name, database OID, owner, and module-private capability object.

> Public `evidence` deliberately remains mutable audit output. It can expose a safe database name, OID, owner, authority booleans, PostgreSQL version, timestamp, and cleanup status, but it is never read as destructive authorization.

Before opening an administrator connection, `cleanup()` checks the strict public name, factory capability identity, private record completeness, private name-to-instance consistency, private owner-to-role consistency, and positive private OID. After connection but before session termination or `DROP`, it queries the current catalog by validated name and requires the returned name, OID, and owner to match the private record exactly.

| Condition | Cleanup result |
| --- | --- |
| Hand-constructed object, even with matching public evidence | Fail closed before administrator connection. |
| Public evidence changed | Still acts only on original private record. |
| Public `name` changed | Fail closed before administrator connection. |
| Original database absent | Legal factory-issued repeated cleanup completes idempotently. |
| Same-name database recreated | OID mismatch: fail closed; replacement is not terminated or dropped. |
| Owner changed | Owner mismatch: fail closed; target remains present. |
| Two factory-issued instances | One cleanup can affect only its own private name/OID/owner record. |

All identifier-bearing DDL continues to use `psycopg.sql.Identifier`; catalog/session lookups are parameterized. There is no wildcard cleanup, prefix sweep, or unquoted SQL identifier.

## 4. Creation Exception Path

A private authorization record is issued immediately after PostgreSQL confirms the just-created database OID and owner. If later runtime/schema validation fails, the exception path invokes cleanup only through that issued record, so the same name/OID/owner checks are applied. If cleanup itself fails, the original creation exception remains raised and receives only a stable bootstrap-code note; administrator DSNs, Todo DSNs, passwords, tokens, or provider data are not exposed.

## 5. P6 and Golden Todo Integration

`test_p6_autonomous_trial.py` continues to register P6 control-database cleanup before Todo bootstrap and Todo cleanup immediately after bootstrap. The generated Todo URL passes through the unchanged `run_trial` boundary. Golden Todo's fixture remains responsible for a missing standalone non-production target and strictly rejects an existing owner/`CREATE` mismatch without repairing it.

## 6. Verification Contract

| Verification | Required evidence |
| --- | --- |
| Factory authenticity | Manual public construction with matching name/evidence cannot connect as admin. |
| Evidence and name tampering | Cannot redirect cleanup. |
| OID replacement | Same-name replacement survives old-instance cleanup attempt. |
| Owner mismatch | Altered owner survives old-instance cleanup attempt. |
| Owner-plus-Create | Wrong owner with explicit `CREATE` remains rejected by helper and Golden fixture. |
| Golden Todo | 9 tests pass against a fresh role-owned database. |
| P6 | Authority suites, standalone trial, fresh `0001 → 0028`, and no-residue check remain green. |

## References

[1]: ../hermes-runtime/src/hermes_runtime/trial/test_database_bootstrap.py "Factory-issued cleanup implementation"
[2]: ../hermes-runtime/tests/test_p6_todo_database_bootstrap.py "Cleanup authenticity and PostgreSQL integration evidence"
[3]: ./P6_GOLDEN_TODO_DATABASE_BOOTSTRAP_DELIVERY_REPORT.md "Bootstrap delivery record"
[4]: ./PROTEUS_E2X_P6_BASELINE_MANIFEST.md "Current Verification Authority"
