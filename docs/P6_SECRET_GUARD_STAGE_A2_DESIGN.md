# P6 Secret Guard Stage A2：Execution-Prepare Live Callsite Convergence 设计说明

**状态：** 已实现；待作为独立 Stage A2 PR 接受。  
**生成时间（UTC）：** 2026-08-21T09:49:48Z  
**适用范围：** 仅覆盖 migration `0032_p6_execution_prepare_structured_secret_guard.sql`、其最小 PostgreSQL 回归，以及本阶段交付文档与基线清单。

## 1. 目标与问题边界

0031 已将 `public.hermes_execution_has_secret_value(JSONB)` 定义为 P6 的**规范化结构化 secret policy**。它递归检查 JSONB object、array 与 scalar，并保留稳定拒绝码 `SECRET_VALUE_FORBIDDEN`。不过，`public.hermes_prepare_execution_request` 的 sandbox profile 分支仍保留独立的 `sandbox_row.profile::text` 正则检查。该分支绕过了 0031 的规范 helper，因而可能重新引入 JSON 序列化上下文误报，且使同一 execution admission 中的 payload 与 sandbox profile 使用两套策略。

Stage A2 的唯一目标是使这个**已存在的 live sandbox callsite**与 0031 收敛。它不放宽 0031 的策略，不为 task、risk 或任何 identifier 建立路径 allowlist，也不改变 E4 durable identity、P6 authority state machine、表结构、角色或 grant。

| 设计约束 | Stage A2 实现 | 验证方式 |
|---|---|---|
| 使用已生效的最终语义 | 从 fresh `0001→0031` 数据库以 `pg_get_functiondef` 导出最终 `hermes_prepare_execution_request` 再重建 | 0032 中存在全部当前 action route 集合 |
| 只替换单一旧分支 | 将 `sandbox_row.profile::text` regex 分支替换为对 0031 helper 的调用 | 函数定义审计中 legacy text callsite 为 `false` |
| 维持拒绝契约 | 规范 helper 返回真时仍抛出 `SECRET_VALUE_FORBIDDEN` | 真实 PostgreSQL guard/admission 回归 |
| 保持函数安全元数据 | `CREATE OR REPLACE` 保留签名、owner、ACL、`SECURITY DEFINER`、volatility、parallel 属性与 hardened `search_path` | fresh `0001→0032` catalog 审计 |
| 不混入 E8 | 不包含 preview DTO、GraphPatch 对齐、existing-entry adapter、observer 或完整 E8 trial | 文件范围审计 |

## 2. 迁移设计

0032 的来源不是早期 migration 的历史函数文本，而是 fresh `0001→0031` 后数据库中**实际生效**的 `hermes_prepare_execution_request` 定义。这样可确保 0014 之后加入的 admission 逻辑不被 `CREATE OR REPLACE` 意外回退。

在该最终定义内，唯一语义替换如下：

```sql
-- Legacy branch removed by 0032:
-- IF sandbox_row.profile::text ~* ... THEN
--     RAISE EXCEPTION 'SECRET_VALUE_FORBIDDEN';
-- END IF;

IF public.hermes_execution_has_secret_value(sandbox_row.profile) THEN
    RAISE EXCEPTION 'SECRET_VALUE_FORBIDDEN';
END IF;
```

迁移保留 action route 的现行允许集合：`diagnose`、`run_deeper_test`、`deeper_test`、`repair`、`retry` 与 `implement`。这一点很重要：从过早的函数定义重建会遗漏后续 route 扩展，并把合法的 recovery route 错误拒绝为 `EXEC_ADMISSION_ACTION_ROUTE_UNSUPPORTED`。0032 以最终定义为源，因此不产生该回退。

> 0032 的 policy authority 仍是 0031 helper；0032 只消除一个绕过 helper 的 legacy callsite。

## 3. 回归设计

`test_execution_postgres.py` 仅增加为支持 sandbox profile fixture 注入所需的最小参数化，并新增以下两项真实 PostgreSQL 回归。

| 回归 | 运行时输入 | 断言 |
|---|---|---|
| `test_structured_guard_rejects_runtime_canary_inside_sandbox_bindings` | 运行时拼接的 synthetic canary 位于 `bindings.task_id` | canonical helper 返回拒绝；源码不包含完整 canary |
| `test_prepare_callsite_converges_to_canonical_guard_for_e4_task_binding` | E4 `stable_id("task", ...)` 写入 sandbox `bindings.task_id` | helper 接受；prepare 进入 `QUEUED`；同一命令 replay 去重；仅有一条 request 与 queue item |

既有套件继续覆盖真实 secret-shaped 值、嵌套 JSON、敏感 key、opaque reference 语法、E4 task/risk identity，以及拒绝后 receipt、event、outbox、audit 等持久化面无运行时 canary 残留。Stage A2 没有把真实 secret 写入源码或交付文档。

## 4. 非目标与不可变项

本阶段不创建或修改业务表、列、角色、ownership 或任何 grant；不修改 migration `0001` 至 `0031`；不修改 E4 `stable_id()`；不修改 P0–P6 authority state machine；不恢复 E8 forensic 改动。任何需要上述变化的情况均超出本阶段 authority，必须停止并另行授权。

## 5. Acceptance 条件

Stage A2 仅在下列条件同时满足时可进入独立 PR：fresh `0001→0032` 函数元数据与 route 语义均通过；两项新增回归及既有 P6/E4 tests 通过；真实 PostgreSQL P6 bootstrap 和 autonomous trial 通过；全量 Runtime、no-DB discovery 与前端保护性回归通过；以及 baseline manifest 的全部非自指条目校验为零 missing、零 mismatch。
