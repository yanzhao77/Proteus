# P6 Recovery Permission Discrepancy Recon

**性质：只读 authority 调查。** 本报告不修改 `0024_p6_autonomous_trial_runtime.sql`、Recovery functions、permission test、P6 runtime 或 P6 evidence。其结论是一个待裁决的 P6 authority gate，而不是已实施修复。

## 1. Executive Conclusion

当前证据支持以下判断：**`hermes_recovery_runtime` 不应拥有对 `public.tasks` 的直接 `UPDATE` 权限。** `0017_feedback_recovery_loop.sql` 已建立 Recovery 的窄 execute surface、dedicated non-login `hermes_recovery_owner` 与 `SECURITY DEFINER` command functions。`tests/test_recovery_permissions.py` 将 runtime direct authority write 明确列为被禁止的语句，其中包括 `UPDATE public.tasks SET state='PASSED'`。

`0024_p6_autonomous_trial_runtime.sql` 第 506 行新增 `GRANT UPDATE ON public.tasks TO hermes_recovery_runtime`，这与上述 invariant 直接冲突。注释把 function owner 所需的 task re-entry 权限外溢给 runtime role；但 `SECURITY DEFINER` function 以 owner 权限执行，满足 task update 的应是 `hermes_recovery_owner`，而不是调用 runtime。

## 2. Evidence Matrix

| Evidence | Observation | Authority implication |
| --- | --- | --- |
| `0017_feedback_recovery_loop.sql` | `hermes_plan_recovery_attempt` 与 `hermes_complete_recovery_attempt` 均为 `SECURITY DEFINER`，并要求 `p_actor_type='recovery_controller'`。 | Recovery runtime 的设计入口是 constrained function execute，而非 direct DML。 |
| `0017_feedback_recovery_loop.sql` | Recovery owner 是 dedicated non-login owner，内部 append/reject helpers 不公开 execute。 | Owner 权限应容纳受控 SQL；runtime 权限应保持最小。 |
| `0019_checkpoint_replay_reconcile.sql` | Recovery/reconcile authority extension 继续使用 `SECURITY DEFINER`、hardened search path 和 function surface。 | 后续设计没有建立 runtime direct `tasks UPDATE` 的常规模式。 |
| `0024_p6_autonomous_trial_runtime.sql:502-506` | 注释称 modified `hermes_emit_execution_feedback` performs task re-entry，随后 grant owner 与 runtime 两者 `UPDATE public.tasks`。 | owner grant 与 function design 一致；runtime grant 是额外、直接的 authority path。 |
| `tests/test_recovery_permissions.py:33-47` | 对 `hermes_recovery_runtime` 逐个验证 direct INSERT/UPDATE，包括 `UPDATE public.tasks` 必须被拒绝。 | 测试是明示 permission invariant，而非模糊运行时行为检查。 |
| `tests/test_recovery_permissions.py:49-78` | runtime public execute surface 被断言为精确三个 public recovery commands。 | direct table DML 与 narrow command surface 的最小权限意图不一致。 |

## 3. Why P6 Trial Passes While Full Regression Fails

P6 standalone trial 通过不能证明 runtime role privilege 正确。`trial/driver.py` 以单一 `database_url` 构造 `PostgresProjectStore`、`PostgresRecoveryStore`、`ControlPlane` 与其余 authority stores；测试路径没有对 `hermes_recovery_runtime` 执行 `SET ROLE` 或检查其 table privilege。它证明 Recovery Controller 的 functional sequence、including re-entry, 可在 test database authority connection 上完成。

相反，`test_recovery_permissions.py` 明确以 `hermes_recovery_runtime` 角色执行直接 SQL。因此两个测试测量不同性质：P6 trial 测量功能闭环，permission test 测量 least privilege。当前 `0024` grant 使前者继续 PASS、后者 FAIL；这不是“无关失败”，而是 functional acceptance 未覆盖 permission invariant 的证据。

## 4. Is the Permission Test Stale?

现有证据不足以把 permission test 视为 stale。其写法与 P0–P5 recovery design、three-command public execute surface、dedicated owner、`SECURITY DEFINER` authority pattern 一致。`0024` 的 inline comment 提供了 runtime grant 的动机，但没有对应的 architecture decision、测试更新或新的 runtime direct-DML command boundary。

因此本 Recon 的默认判断是：**`0024` migration 违反了既有 recovery permission invariant，直到一项明确的 architecture decision 以同等强度改变该 invariant。** 该判断不是修复命令；P6 owner 必须裁决到底撤销 runtime grant，还是正式引入并审计一个不同的 authority model。

## 5. Minimal Repair Direction (Do Not Implement in This Task)

最小且与现有模式一致的候选方向是：在一项新的、经过 P6 authority review 的 migration 中撤销 `hermes_recovery_runtime` 对 `public.tasks` 的 direct `UPDATE`；保留 `hermes_recovery_owner` 对 `public.tasks` 的权限，使 `hermes_emit_execution_feedback` 的 `SECURITY DEFINER` path 继续完成 task re-entry。然后重跑 permission、Recovery functional 和 P6 evidence acceptance。

该方向必须先获批准，因为它触及 P6 role grant/migration，属于本任务明确的 stop condition。不得直接编辑 `0024`，不得删、skip、xfail 或放宽 permission test。

## 6. Required Revalidation After a Future P6 Decision

| Revalidation | Why it is required |
| --- | --- |
| `test_recovery_permissions.py` | 验证 direct DML 禁令与 exact execute surface。 |
| Recovery Postgres tests | 验证 feedback、attempt planning/completion、fault rollback。 |
| P6 standalone acceptance | 验证 Autonomous Trial 的 recovery/re-entry evidence chain。 |
| P6 report/evidence regeneration | 任何 role grant 变化都会影响 current acceptance evidence 的 authority interpretation。 |
| Full Runtime regression | 防止 role privilege 调整破坏 replay, worker, verifier 或 Project authority boundaries。 |

## 7. Gate Status

> **P6 Authority Gate: OPEN.** E2.x Gap Closure 没有也不会裁决或修复此冲突。任何 Phase Complete 结论都必须把该 gate 显式保留为 open。

## 8. Resolution Status — 0028 Forward Repair

The subsequent fresh `0001 → 0027` permission reproduction confirmed that `0024` directly introduced the table-wide `UPDATE public.tasks` grant for `hermes_recovery_runtime`; it was not inherited and remained effective after `0027`. The earlier `state = state` probe was misleading because it also required `SELECT`; the read-free literal probe confirmed the direct write path.

The approved forward migration `0028_p6_recovery_runtime_least_privilege.sql` revokes only `UPDATE ON public.tasks` from `hermes_recovery_runtime`. It preserves `hermes_recovery_owner` authority and the existing Recovery function bodies, signatures, ownership, `SECURITY DEFINER` configuration and exact execute surface. Fresh `0001 → 0028`, original Recovery permission, runtime-role command/replay/rollback, Recovery functional, P6 standalone and full Runtime regression evidence all passed.

> **P6 Authority Gate: CLOSED.** See [P6 Recovery Runtime Least-Privilege Repair Delivery Report](./P6_RECOVERY_PERMISSION_REPAIR_DELIVERY_REPORT.md) for the final revalidation record. Historical sections above remain the original investigation and stop-state record.
