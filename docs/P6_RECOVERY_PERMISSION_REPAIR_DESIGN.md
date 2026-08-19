# P6 Recovery Runtime Least-Privilege Repair Design

> **Design authority.** This document records the approved P6 authority repair. The approved invariant is that `hermes_recovery_runtime` must not directly `INSERT`, `UPDATE` or `DELETE` authority tables, including `public.tasks`. Recovery task re-entry remains exclusively within the existing, constrained `SECURITY DEFINER` command surface owned by `hermes_recovery_owner`.

## 1. Confirmed Baseline

A one-time fresh migration reproduction applied `0001` through `0027` to an isolated database and compared the resulting authority state with `hermes_p6_trial`. The direct `UPDATE` grant is absent after `0023`, introduced by `0024`, and remains present after `0027` and in the existing test database. It is a direct table-wide ACL grant to `hermes_recovery_runtime`, not a role-membership or inheritance path.

| Baseline fact | Confirmed result | Authority implication |
| --- | --- | --- |
| Runtime direct `UPDATE public.tasks` after `0023` | Absent | The historical Recovery command surface did not require runtime DML. |
| Runtime direct `UPDATE public.tasks` after `0024` / `0027` | Present, table-wide | `0024` opens a bypass around the narrow command boundary. |
| `hermes_recovery_owner` direct `UPDATE public.tasks` | Present after `0024` | The function owner retains the privilege required for controlled re-entry. |
| Runtime role membership | None | No inherited or membership-based explanation exists. |
| Public Recovery commands | Exactly three runtime-executable; none executable by `PUBLIC` | The intended public command surface already exists. |
| Command owner and security mode | `hermes_recovery_owner`, `SECURITY DEFINER`, `search_path=pg_catalog` | Owner authority is the correct route for task re-entry. |

The earlier probe `UPDATE public.tasks SET state = state WHERE FALSE` was not an UPDATE-only check because the right-hand side reads `state`, requiring `SELECT`. Runtime lacks `SELECT`, so that probe yielded a misleading `42501`. All verification in this repair uses the read-free literal form `UPDATE public.tasks SET state = 'PASSED' WHERE FALSE` within a transaction and rollbacks.

## 2. Forward-Only Repair

The repair is a single new migration: `0028_p6_recovery_runtime_least_privilege.sql`. It contains one authority operation inside a transaction:

```sql
REVOKE UPDATE ON TABLE public.tasks FROM hermes_recovery_runtime;
```

The migration does not alter `0024` or any earlier migration. It does not alter table ownership, Recovery role membership, function bodies, signatures, ownership, execute grants, task-state semantics, receipts, idempotency rules, events or frontend/E1/E2/E2.x behavior.

| Principal | Before 0028 | After 0028 | Intended boundary |
| --- | --- | --- | --- |
| `hermes_recovery_runtime` | Direct table-wide `UPDATE public.tasks` plus command `EXECUTE` | Command `EXECUTE` only; no direct `UPDATE public.tasks` | May request recovery only through approved command functions. |
| `hermes_recovery_owner` | `SELECT, UPDATE public.tasks` and function ownership | Unchanged | Performs task re-entry inside `SECURITY DEFINER` authority transactions. |
| `PUBLIC` | No Recovery command execute | Unchanged | Cannot invoke Recovery authority. |

## 3. Controlled Command Path

The control path deliberately remains unchanged:

```text
runtime role → public.hermes_emit_execution_feedback(...) → SECURITY DEFINER
             → hermes_recovery_owner authority transaction → task re-entry
```

The narrow integration test exercises the command as `SET LOCAL ROLE hermes_recovery_runtime`, not as an admin substitute. It prepares an existing legal failed-execution state through the existing test fixture, invokes the existing `hermes_emit_execution_feedback` public function, then verifies `READY` re-entry, durable feedback/cycle/receipt/event effects, exact idempotency replay, and an injected fault rollback. It separately proves direct literal DML is rejected before and after the command.

## 4. Required Authority Revalidation

| Check | Required result |
| --- | --- |
| Effective table `UPDATE` for runtime | False |
| Effective runtime column `UPDATE` | No column permitted |
| Literal direct zero-row DML | PostgreSQL `42501` under `SET LOCAL ROLE hermes_recovery_runtime` |
| Runtime command execute surface | The existing exact three public Recovery commands only |
| `PUBLIC` execute surface | No Recovery command authority |
| Function boundary | Existing owner, `SECURITY DEFINER` and hardened `pg_catalog` search path unchanged |
| Owner task privilege | `hermes_recovery_owner` retains `UPDATE public.tasks` |
| Controlled runtime path | Existing command completes re-entry, replay and rollback invariants without direct DML |

## 5. Risks and Acceptance Plan

The only material risk is a hidden dependency on the prohibited direct table grant. This is addressed by running the Recovery permission suite, the runtime-role integration test, Recovery PostgreSQL functional and fault tests, fresh `0001 → 0028` migration continuity, P6 standalone acceptance, P0–P5 regression and the full Runtime regression. A failed check does not permit weakening the permission invariant or modifying a historical migration; it leaves the P6 Authority Gate open.

Rollback is forward-only. If a later governed decision changes the authority model, it must use a new reviewed migration rather than editing `0028` or reintroducing a runtime broad privilege by an indirect route.

## References

[1]: ./P6_RECOVERY_PERMISSION_DISCREPANCY_RECON.md "P6 Recovery permission discrepancy reconciliation"
[2]: ../hermes-runtime/migrations/0024_p6_autonomous_trial_runtime.sql "P6 Autonomous Trial Runtime migration"
[3]: ../hermes-runtime/migrations/0028_p6_recovery_runtime_least_privilege.sql "P6 Recovery runtime least-privilege forward migration"
[4]: ../hermes-runtime/tests/test_p6_recovery_runtime_least_privilege.py "Runtime-role command integration evidence"
