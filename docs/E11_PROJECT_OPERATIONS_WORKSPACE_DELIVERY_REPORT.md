# E11 Project Operations Workspace：交付报告

**状态：** PASS / COMPLETE。
**数据来源：** E7 source-derived Live Production snapshot 与 bounded feed；无新增 read-model schema。

## 实现

`/productions/:id/operations` 是 Project Operations Workspace。它读取同一 actor-scoped live snapshot 并呈现项目标题/状态/watermark、DAG nodes 与 edges、execution requests、verification plans、evidence counts/items、waiting records、recovery findings 与权威事件日志。所显示字段均从既有 E7 projection 映射，未从 React 推断 Project、Task、Execution、Gate、Recovery 或 Verification authority。

| 子工作区 | 数据 | 写入边界 |
|---|---|---|
| Workflow DAG | task nodes / dependency edges | 只读 |
| Execution | execution request state/version | 只读 |
| Verification | plan / result authority status | 只读 |
| Evidence | valid、invalidated、missing及媒体类型 | 只读 |
| Waiting / Recovery | waiting record、finding、gate context | 只读 |
| Controlled recovery entry | 含 project context 的既有 Gate Inbox route | 不发送 pause/resume/retry/reassign/direct recovery command |

`CURRENT`、`STALE`、`DEGRADED`、`NOT_AVAILABLE` 与空集合在 UI 中显式显示。受控恢复 CTA 只是导航入口；实际 recovery authority 仍属于既有 P0–P6 / human-gate workflow。本波次不进入 E12 Gate decision center。

## E11 验收

| 门禁 | 本轮结果 |
|---|---|
| E11 adapter：DAG/execution/verification/evidence/waiting/recovery field mapping | `1/1 PASS` |
| 前端完整 Vitest（截至E11） | `31` tests / `8` files PASS |
| Full Runtime（真实 PostgreSQL 16） | `707 run / 12 skipped / 0 failures`，`471.213s` |
| 新增 migration | 无；head 仍为 `0032` |

> E11 不改变 E7 read model、E4 durable identity、P0–P6 authority state machine、schema、role 或 grant；不进入 E12–E16。
