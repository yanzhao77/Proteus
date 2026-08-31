# E11 User Command Transport 实现交付报告

**Generated UTC：** Updated by the current manifest reseal.
**实现基线：** `e3cf282ed21ad461cfd5532c4a684486bbcd71fb`（PR #29 合并后的 `master`）
**交付状态：** **IMPLEMENTED / VERIFIED / DELIVERY CANDIDATE — PR #30 OPEN；NOT MERGED；NOT ACCEPTED AS FINAL**

> 本报告记录已获授权的 E11 实现分支结果。它不授权合并，也不将 E11 写为最终完成。最终状态仍须等待实现 PR 审查、标准合并，以及合并后核验。

## 1. 实现范围与不变量

本实现将经过验证的 OIDC 用户请求限定为既有 Project 语义命令的**可信 Control Plane 代理**。公开写入面只包含 `POST /factory-home/productions/{project_id}/commands/{pause|resume|cancel}`；receipt 查询面为 `GET /factory-home/productions/{project_id}/commands/{command_id}`。实现严格遵循已合并设计的 allow-list、server-derived scope、Control Plane 执行者与 E7 协调原则。[1] [2] [3]

| 领域 | 已实施行为 | 明确未实施/未放宽的边界 |
|---|---|---|
| 身份与范围 | 从既有不透明 HttpOnly OIDC session 派生已验证 subject；服务端要求 `Actor(USER, subject)` 一致，并以既有 creator-scope 解析可操作项目。 | 客户端不能提交或选择 executor、requested_by、scope 或项目所有权。 |
| 语义命令 | 仅代理既有 `pause`、`resume`、`cancel`；服务端构造 `Actor(CONTROL_PLANE, "e11-user-command-proxy")` 作为 executor，并保留验证用户为 requester。 | 无通用 transition、状态写入、任意 command、retry、reconcile、reverify 或 E12 命令。 |
| 幂等与审计 | 继续委托既有 `ControlPlane` 与 `PostgresProjectStore`；复用 command receipt、expected version、transition record、event log 与 outbox。 | 无第二 authority、无直接 DML、无伪造 receipt 或事件。 |
| 响应与投影 | 写响应和查询响应仅返回 receipt metadata：command id、receipt status、result code、target version、event ids，以及 `AWAITING_E7_RECONCILIATION`。 | receipt 不声明 E7 projection 已完成，不返回底层 receipt response 中可能被误解为当前状态的数据。 |
| 前端 | Operations workspace 仅提供 reason 输入和 pause/resume；使用 cookie credentialed POST，显示 pending 或 receipt/E7 协调提示。 | 不提供 cancel UI，不发送 actor、requested_by、scope、state、executor 或任意 authority 形状字段。 |

前端通用 `CommandMetadata` 也移除了客户端 `actor` 字段。该调整消除了浏览器可表达的 authority 主体；服务端仍是身份与授权的唯一来源。

## 2. 数据库与兼容性结论

在 disposable PostgreSQL 16 上，从现有 migration `0001` 至 `0032` 建立基础并完成实现验证。该实现**没有新增或修改 migration、表/列、角色、grant、ACL、function owner/security mode/search path，也没有修改 E4 durable identity、P0–P6 状态机或 E1–E10 既有语义**。新增的 receipt 读取仅查询既有 `command_receipts`，并限定既有 Project command type。

| 验收点 | 结果 |
|---|---|
| executor/requester 分离持久化 | PASS：transition record 保留 Control Plane executor 与 creator requester。 |
| creator scope 与外部 project probing | PASS：foreign target 返回受控不可用结果，且零 authority write。 |
| 版本与终态保护 | PASS：既有 expected-version 与 Project state-machine 拒绝继续生效。 |
| 同 key、同请求 replay | PASS：返回同一 authoritative receipt，不新增 event/outbox。 |
| 同 key、不同请求 | PASS：返回既有 `IDEMPOTENCY_CONFLICT`，不新增 event/outbox。 |
| 并发同 key | PASS：两个请求收敛至一个 receipt、一条 authority event 和一条 outbox message。 |
| E7 协调 | PASS：receipt 之后以有界、可取消的 creator-scoped E7 snapshot/live-feed 读取协调；仅在 `CURRENT`、兼容schema且数值Project version达到 receipt target version 时更新UI的source-derived snapshot。 |

## 3. 验证结果

所有数据库证据均来自真实 disposable PostgreSQL 16；未使用 mock 数据库来证明 authority 接受条件。Golden Todo 相关完整回归使用仓库既有的非提交测试虚拟环境与非生产测试数据库前置条件；没有将该环境、DSN 或凭据写入仓库。

| 验证层级 | 命令/范围 | 结果 |
|---|---|---|
| E11 无数据库契约 | public API boundary、transport unit、FastAPI local RS256/opaque session、E10、E7、Project/Recovery domain | **29 / 29 PASS** |
| E11 PostgreSQL | pause/resume、receipt read、scope denial、stale version、replay、冲突与并发收敛 | **6 / 6 PASS** |
| E11→E7 PostgreSQL | receipt target version、creator-scoped current snapshot、bounded live-feed与receipt event id | **1 / 1 PASS** |
| 相关 PostgreSQL 回归 | Project、guard facts、E7 projection、Recovery、Project/Recovery/P6 permissions | **64 / 64 PASS** |
| 前端 | Vitest（含协调helper、Operations interaction、adapter error matrix） | **80 / 80 PASS** |
| 前端产物 | TypeScript `--noEmit` 与 Vite production build | **PASS** |
| 前端静态检查 | oxlint | **0 warnings / 0 errors** |
| 浏览器验证 | sandbox browser 与远程隔离开发机预览网络隔离；未发出命令请求。等效渲染与互动路径由Operations component test覆盖。 | **ENVIRONMENT-BLOCKED** |
| 完整运行时 | `unittest discover -s tests`，fresh PostgreSQL 16 与 Golden Todo 受控前置 | **722 run / 12 skipped / 0 failures**，`666.583 s` |

首次完整运行的失败仅揭示 Golden Todo 测试环境缺少同 cluster 的 `todo` 测试角色/模板数据库及其既有测试虚拟环境；在按仓库 CI 预置条件恢复后，相关 bootstrap 模块 `13 / 13 PASS`，最终完整运行时回归通过。该处理没有修改仓库代码、migration、权限或测试预期。

## 4. 本轮协调修复

本轮修复关闭了PR #30初审发现的“仅提示协调、未执行协调”的缺口。`e11Reconciliation.ts` 是纯前端有界协调helper，最多四次读取；event feed只提供stale/gap诊断，不能取代snapshot确认。`Operations` 以AbortController与epoch避免unmount、后续命令或URL恢复中的陈旧异步结果覆盖新状态；它会将receipt id写入URL，并在新mount时通过既有receipt GET恢复。

`uncertain` 是安全终态而非重试命令：版本未达到、HTTP稳定错误、超时、畸形snapshot、schema不兼容或cursor异常均保留最后source-derived snapshot及redacted receipt correlation，不制造进度、状态或已应用主张。协调细节及完整验证矩阵见[6]。

## 5. 交付文件与安全审计

本候选交付只包含 E11 transport、既有 facade/FastAPI/store 接线、最小前端 adapter/UI、受影响的前端契约更新和 E11 测试。检查结果为 `git diff --check` 通过；受保护的 migration、roles/ACL/grants/schema、E4 identity 与 E12 路径均无变更；新增 proxy 源文件中未发现对 projects、event log 或 outbox 的直接 DML。候选源码也通过基础 credential-like pattern scan，未发现私钥、API key、Bearer token 或 password assignment。

## 6. 当前状态与后续受权边界

| 范围 | 当前状态 |
|---|---|
| E11 User Command Transport 实现分支 | **IMPLEMENTED / VERIFIED / DELIVERY CANDIDATE** |
| E11 最终接受状态 | **PARTIAL / ACCEPTANCE GAP**，直到实现 PR 经标准审查与合并后核验。 |
| E9–E11 Wave A | **NOT COMPLETE**；本候选实现不改写历史 Wave A 的已接受范围。 |
| E12–E16 | **NOT ENTERED**。 |

> **当前状态更新 (2026-08-31):** 本文档为历史交付记录。E11 已 **PASS / COMPLETE**（PR #31 已合并）。E13 Proposal / Master Plan Editor 已 **PASS / COMPLETE**（PR #34 已合并）。当前权威状态见 `docs/PROTEUS_E2X_P6_BASELINE_MANIFEST.md` §11。
| migration / ACL / role 变更 | **NONE**。 |
| 实现 PR 合并 | **NOT AUTHORIZED；不得自动合并**。 |

实现 PR 发布后必须保持 **OPEN**。只有后续获得独立、明确的标准合并授权，才可执行合并；之后仍需要从远端 `master` 进行 post-merge verification，才能改变 E11 的最终接受措辞。

## References

[1]: [E11 User Command Transport Recon Report](E11_USER_COMMAND_TRANSPORT_RECON_REPORT.md)
[2]: [E11 User Command Transport Design](E11_USER_COMMAND_TRANSPORT_DESIGN.md)
[3]: [E11 User Command Transport Acceptance Matrix](E11_USER_COMMAND_TRANSPORT_ACCEPTANCE_MATRIX.md)
[4]: [E11 Authority Decision](E11_USER_COMMAND_TRANSPORT_AUTHORITY_DECISION.md)
[5]: [E11 trusted transport implementation](../hermes-runtime/src/hermes_runtime/application/user_project_command_transport.py)
[6]: [E11 post-command E7 projection reconciliation delivery](E11_USER_COMMAND_TRANSPORT_RECONCILIATION_DELIVERY.md)
