# P6 Secret Guard Stage A2：交付报告

**状态：** Stage A2 实现与本地门禁通过；待独立 PR、远端 CI 与合并后 master 核验。  
**生成时间（UTC）：** 2026-08-21T09:49:48Z  
**权威基线：** remote `master` 的 `84ba4b0d094f2139a47b575f859907cc0f360612`（已含 0031）。

## 1. 交付范围

本阶段交付一条 forward-only migration `0032_p6_execution_prepare_structured_secret_guard.sql`，使 `hermes_prepare_execution_request` 的 sandbox profile 检查调用 0031 的 canonical structured JSONB guard。配套测试仅包含 sandbox profile fixture 注入与两项最小 execution admission 回归。本报告、设计文档及 baseline manifest 构成唯一允许的文档交付。

下表列出明确未发生的变更。它们是 Stage A2 的 authority 边界，而非待办事项。

| 不可变对象 | 结果 |
|---|---|
| 历史 migrations `0001–0031` | 未修改 |
| E4 `stable_id()` / durable identity format | 未修改 |
| P0–P6 authority state machine | 未修改 |
| 业务表、业务列、角色、grant | 未新增或扩大 |
| E8 preview DTO、GraphPatch 对齐、existing-entry adapter、observer、完整 E8 trial | 未包含 |

## 2. Fresh Migration 与函数元数据证据

在新的 disposable PostgreSQL 16 容器中依次应用 `0001→0031`，通过 `pg_get_functiondef` 获取生效的 `hermes_prepare_execution_request`；0032 仅替换旧 sandbox profile 文本 regex 分支。随后在同一 fresh 容器应用 0032 并审计系统目录与最终函数定义。

| 验证项 | 结果 |
|---|---|
| 函数 owner | `hermes_execution_owner` |
| `SECURITY DEFINER` | `true` |
| volatility / parallel | `volatile` / `unsafe`（原有值保留） |
| hardened search path | `pg_catalog` |
| ACL | `hermes_execution_owner=X/hermes_execution_owner`；`hermes_execution_runtime=X/hermes_execution_owner` |
| `sandbox_row.profile::text` | 不存在 |
| `hermes_execution_has_secret_value(sandbox_row.profile)` | 存在 |
| action route 允许集合 | 存在 `diagnose`、`run_deeper_test`、`deeper_test`、`repair`、`retry`、`implement` |

这项审计同时排除了先前重建方式的风险：若从早期 migration 提取函数文本，会缺少后续的 action route 语义，并导致合法 repair/retry 路径以 `EXEC_ADMISSION_ACTION_ROUTE_UNSUPPORTED` 被拒绝。当前 0032 从 fresh 0031 的最终定义重建，且真实 P6 trial 已通过该路径。

## 3. 真实 PostgreSQL 与回归结果

| 门禁 | 结果 | 证据 |
|---|---:|---|
| 0032 function convergence audit | PASS | fresh `0001→0032` catalog/function-definition audit |
| 新增 execution guard tests | PASS | 包含 runtime-constructed sandbox canary 拒绝与 E4 task binding admission/replay 回归 |
| P6 bootstrap + autonomous trial | PASS | `14` tests，`105.804s`，`OK` |
| no-DB CI discovery | PASS | `704` tests，`437` skipped，`OK` |
| Full Runtime | PASS | `704` tests，`12` skipped，`430.060s`，`OK` |
| Frontend Vitest | PASS | `6` files、`40` tests 通过 |
| Frontend production build | PASS | TypeScript build + Vite build 通过 |
| Frontend static lint | PASS | `0` warnings、`0` errors |

P6 trial 的正式运行使用真实 disposable PostgreSQL 与受控 Golden Todo 数据库。其 acceptance matrix 中 autonomous happy path、verification-failure recovery、worker-crash recovery、duplicate execution deduplication、artifact-tampering fail-close、human-gate resume、recovery plan 与 final delivery 均通过。

## 4. 测试环境排障记录

第一次独立 P6 尝试并非 0032 authority failure：Golden Todo 运行时 DSN 被错误写成 plain `postgresql://`。在 SQLAlchemy 下，该方言选择 psycopg2，而 Golden Todo 的锁定依赖使用 psycopg v3；结果为 `ModuleNotFoundError: No module named 'psycopg2'`。这是一次性 disposable test-environment DSN 方言错误，不是仓库迁移、P6 state machine 或 0032 secret policy 的变更。

为排除歧义，后续将 DSN 恢复为 CI 定义的 `postgresql+psycopg://` 形式，并运行最小真实 Golden Worker 探针。探针在其新建 workspace virtual environment 中执行 `9 passed in 1.01s`。随后正式 P6 bootstrap/autonomous trial 在同一 fresh 0032 容器中 `14/14` 通过。该过程未更改仓库的 Golden Todo 依赖、P6 harness、authority 或测试语义。

> 该排障结论限定于 disposable test environment；本阶段没有把测试环境修正伪装成生产行为或代码修复。

## 5. Secret 安全证据

新增测试通过运行时拼接 synthetic canary，避免在源码、输出或交付文档中写入真实 secret。测试验证 canonical guard 能识别 sandbox binding 中的 secret-shaped scalar；E4 task identity 则因为不具备 token boundary 而自然通过。现有回归继续验证拒绝后 execution request、reservation binding、queue、receipt、event、outbox 与 audit 无 canary 持久化。

0032 的稳定拒绝行为没有变化：canonical helper 返回真时，prepare 函数仍抛出 `SECRET_VALUE_FORBIDDEN`。由于所有 inspection 都经 0031 structured helper，Stage A2 没有引入 identity-path allowlist 或对 `task_id`、`ref_id`、`*_id` 的特殊放行。

## 6. PR 前状态

本地实现和门禁满足 Stage A2 acceptance。下一步只能是对允许的五个文件执行 manifest reseal、精确暂存、secret scan、cached diff 审计、独立 Stage A2 PR 与 CI。该 PR 合并及新 `master` 核验前，E8 worktree 的 forensic 改动仍保持隔离，不可混入或恢复到本阶段分支。
