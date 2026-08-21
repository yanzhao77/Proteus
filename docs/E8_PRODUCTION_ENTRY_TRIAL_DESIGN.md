# E8 Production Entry Trial：同一项目纵向闭环设计

**状态：** 已实现并通过本地真实 PostgreSQL 验证；待独立 E8 completion PR、CI 与合并核验。
**生成时间（UTC）：** 2026-08-21T11:00:18Z
**前置基线：** `master` 的 `c5dd19e6c6f7c86cae6ed5ec0910e631d9ec72c5`，已包含 Stage A2 的 0032 convergence。

## 1. 目标

E8 证明用户的第一次 Production Creation 不是聊天演示，而是一条具有可验证 authority 边界的真实纵向路径。试验从一个由 creator 认证的生产想法开始，经过 E1 Draft、E2 Understanding、E3 Proposal/Master Plan、E4 durable approval bridge、P6 autonomous recovery，再由 E7 read model 和 bounded live feed 展示同一个 project 的实时状态。

> E8 不是新 authority 的实现阶段。它只把已经接受的 E1–E7 ports 连接成一条**同一项目、同一 durable identity**的可测试路径。

| 阶段 | E8 使用的既有 authority | E8 证明 |
|---|---|---|
| E1–E3 | Product API draft/understanding/proposal/master-plan ports | creator-scoped entry、idempotent draft、typed deterministic Understanding 与 frozen plan |
| E4 | approval preview 与 durable bridge saga | approval materializes exactly one project、tasks 与 verification plan |
| P6 | existing execution admission、worker、verification、recovery ports | 首次真实 defect、diagnosis/recovery、repair、verification PASS 与 delivery ACCEPTED |
| E7 | snapshot 与 bounded cursor live feed | 同一 project 的 `CURRENT` snapshot、阶段观察、cursor-ahead fail-closed 与非 owner concealment |

## 2. 最小恢复适配

E8 仅恢复并提交四项必要差异。它们均来自合并 Stage A2 后的独立 forensic 审计。

| 文件 | 最小职责 | 不做什么 |
|---|---|---|
| `entry_approval_bridge_saga.py` | 将 E4 graph child command 的 type 对齐为 `work_graph.apply_patch`，与现有 control-plane command handler 一致 | 不改变 GraphPatch payload、version 或 E4 bridge state machine |
| `product_api.py` | 将 `ApprovalPreview` dataclass 转换为 creator 可见的 safe DTO | 不返回 frozen compiled blueprint 或 child identities |
| `trial/driver.py` | 增加 existing-entry handoff 与 stage observer，使 P6 从已 materialized 的 E4 project/task/plan 继续 | 不创建第二个 project，不旁路 P6 command ports，不直写 authority tables |
| `test_e8_production_entry_trial.py` | 以 fresh control DB、disposable Todo DB、local RS256 verifier 和 FastAPI dispatch 验证同一 project | 不调用外部 provider、不使用真实 credential、不进入 E9 |

P6 adapter 在 `run_happy_path_from_entry(...)` 中接收 project、task、verification plan、verification check 和 readiness event 的既有 identity。它在原有 `run_happy_path(...)` 内使用 optional handoff，而不是复制或替换 P6 lifecycle。stage observer 只读取 E7 snapshot，并在 `RUNNING`、`VERIFICATION_FAILED_RECOVERING`、`VERIFICATION_PASSED` 与 `DELIVERED_ACCEPTED` 记录投影状态。

## 3. 安全与边界

E8 移除了 forensic 版本中会在执行前遍历 request snapshot 的旧 secret preflight。secret policy 的唯一 authority 是已合并的 0031 structured JSONB helper 与 0032 execution-prepare live callsite。E8 test 不重复实现或 monkey-patch secret detection；它通过真实 `execution.prepare` 端口运行，并在日志中验证不存在 `SECRET_VALUE_FORBIDDEN` 或 action-route false rejection。

Approval preview 对外只返回构建 approval command 所需的字段：availability、bridge identity、compiled blueprint hash、required acknowledgements、compiler version 与 policy version。冻结蓝图及 child identity 不通过 preview API 泄露。Product snapshot 与 live feed 继续由 creator actor scope 控制，非 owner 得到 `NOT_AVAILABLE` 而非 probing oracle。

| 禁止项 | E8 结果 |
|---|---|
| 修改 migrations `0001–0032` | 未修改 |
| 修改 E4 `stable_id()` / durable identity format | 未修改 |
| 修改 P6 authority state machine | 未修改 |
| 新建业务 schema、角色或 grant | 未新增 |
| 身份 path allowlist 或 E8 自定义 secret detector | 未引入 |
| 外部 provider、生产 credential、E9 | 未调用 / 未进入 |

## 4. 真实试验契约

试验通过 FastAPI 和本地 RS256 OIDC verifier 创建 draft；同一 idempotency key replay 必须返回同一 draft。typed deterministic producer 只生成测试限定的 Understanding，不进行网络或 provider 调用。creator 提交 proposal 和 master plan，读取 safe preview 后执行 approval；bridge materializes one project，且 E8 断言仅有一条 project row。

P6 从该 project 的 E4 task、verification plan 与 readiness event 继续运行。Worker 的首次 defect 真实失败，现有 recovery authority 产生 diagnosis、recovery plan、repair 与 independent verification；终态为 task `PASSED`、project `ACCEPTED`。E7 snapshot 和 feed 证明 project identity 从 `MATERIALIZED_NOT_STARTED` 连续到 `DELIVERED_ACCEPTED`，而 stale cursor 必须返回 `LIVE_PRODUCTION_CURSOR_AHEAD` 并不泄露事件。

## 5. Acceptance 条件

E8 completion 仅在下列结果同时满足时成立：真实 E8 discovered trial 通过；同一 project 从 E4 materialization 到 P6 recovery 与 E7 projection 全部可读；0032 未误拒 E4 identity；临时控制/Todo 数据库清理完成；no-DB discovery、Full Runtime 和前端保护性回归通过；manifest 的所有非自指条目为零 missing、零 mismatch；并且独立 E8 PR 不混入 Stage A2 之外的无关文件。
