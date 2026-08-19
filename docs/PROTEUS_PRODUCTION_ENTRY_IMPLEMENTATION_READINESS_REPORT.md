# Proteus Production Entry Implementation Readiness Report

**分支：** `codex/p6-autonomous-production-trial`
**基线提交：** `bd55a9f`
**本轮目标：** 在不改变 P0–P6 authority chain 的前提下，完成 Production Entry / Factory Workspace 的 Recon、实现前架构、最小 Web 骨架和验证。
**总体结论：** **PARTIALLY READY — Architecture and non-authoritative UI baseline are complete; the real Idea → Master Plan → Production entry is not yet implemented.**

## 1. Repository Findings

Proteus 当前具备已验证的 Autonomous Software Factory Control Plane。P6 Trial 从受限 request 输入开始，经 Situation、Diagnosis、Planner、Policy/Risk、Selection、Capability、Execution、独立 Verification/Evidence、Recovery/Replan、Human Gate 到 ACCEPTED delivery。P6 runtime 复用既有 Project/Task/Graph/Execution/lease/worker/recovery authority，而不是另起一套运行时。[1] [2]

仓库没有 React、Vue、Next.js、Svelte、Vite、Tailwind 或通用 SPA。现有前端表面是 FastAPI 与最小服务端渲染的 Human Gate HTML。Product API facade 已有严格 allowlist/安全响应边界，但默认 `api_main.py` 组装的是 `EmptyReadModel` 和 `RejectingGateway`；这意味着 API contract 骨架存在，但默认进程没有真实 Entry/Portfolio read model 或生产 command wiring。[3]

## 2. Existing Reusable Infrastructure

| 基础设施 | 已验证可复用方式 | 不可误用的边界 |
| --- | --- | --- |
| Project Authority | 未来仅由 `Approval Bridge` 调用现有 `CreateProject`。 | Idea/Proposal 不能提前创建 Project。 |
| Task Graph / Verification | 已批准 Plan 可经 `ApplyWorkGraphPatch` 与 `CreateVerificationPlan` 物化。 | UI、Draft、Proposal 不能直接写 Task/DAG/verification。 |
| P6 Runtime | 已批准 Project 的唯一自治执行路径。 | 不可把 `trial/**` 当产品 API/Entry 服务。 |
| Human Gate | Action Required 的 read/navigation；既有 Gate decision path。 | Clarification 不是 Gate；Home 不直接改等待状态。 |
| Event / Outbox | 后续 Entry lifecycle 事实可复用现有 transaction/outbox。 | 不新增 Entry Event Store / outbox。 |
| Product API facade | 未来扩展 allowlisted semantic routes。 | 不新增第二 API server 或 generic PATCH。 |
| FastAPI + HTML | 当前唯一可复用 UI 技术。 | 不擅自引入 SPA/前端框架。 |

## 3. Missing Infrastructure

以下能力尚未实现，因此不能将当前基线误报为真实 Production Entry：

1. 持久化、版本化、权限受控的 `EntryDraft` aggregate。
2. Idea、Understanding、Clarification、Assumption、Proposal、Master Plan 的 immutable revision model。
3. Master Plan compiler 和有效 revision/hash validation。
4. `ApproveEntryPlan` semantic command 与可恢复 Approval Bridge。
5. Draft-to-Project materialization mapping/child-command reconciliation。
6. 真实 `ProductReadModel` / `ProductCommandGateway` composition。
7. authoritative Production Portfolio、Gate inbox、Factory status 和 Live Production Snapshot projection。
8. Entry API、权限/并发/幂等、PostgreSQL migration 与 end-to-end Entry trial。

## 4. Architecture Decisions

- **Production is a Project alias/projection.** 用户面对 Production；后端唯一 Project authority 不变。**DO NOT IMPLEMENT Production AS NEW DOMAIN.**
- **EntryDraft is the smallest new pre-approval authority.** 它只管理意图/版本/计划/桥接状态，绝不管理 Scheduler、Task、Worker、Execution、Evidence 或 P6 状态。
- **Clarification ≠ Human Gate; Understanding ≠ Situation; Master Plan ≠ P6 planning run.** 三组概念语义不同，不能复用同一 authority。
- **Approval Bridge is the sole crossing.** 仅在用户批准 plan revision/hash 后，以现有语义命令委托 `CreateProject → ApplyWorkGraphPatch → CreateVerificationPlan`；桥接为 receipt-reconciled saga，不能 raw SQL 或 raw rollback。
- **Factory Home is a source-derived read composition.** 它不计算权威 lifecycle/progress、不以 localStorage 作为事实源，也不再造 Live Production workflow。

完整边界、状态机、Draft/Revision、Proposal/Plan、API、事件、错误、安全、版本、幂等、权限、迁移、P6 compatibility 与 P7+ roadmap 已写入 `docs/PROTEUS_PRODUCTION_ENTRY_ARCHITECTURE_V1.md`。[4]

## 5. Files Created

| 文件 | 作用 |
| --- | --- |
| `docs/ENTRY_RECON.md` | 当前真实 frontend/API/authority/P6/read model/Gate/reusable/missing/risk Recon。 |
| `docs/PROTEUS_PRODUCTION_ENTRY_ARCHITECTURE_V1.md` | Production Entry authority、Draft、Approval Bridge、Portfolio、API、测试与迁移架构。 |
| `hermes-runtime/src/hermes_runtime/application/factory_workspace_ui.py` | 无框架、服务端渲染、**显式非权威** Factory Workspace renderer。 |
| `hermes-runtime/tests/test_factory_workspace_ui.py` | 骨架 routes、非权威 notice、GET-only 与 runtime import boundary 测试。 |
| `docs/PROTEUS_PRODUCTION_ENTRY_IMPLEMENTATION_READINESS_REPORT.md` | 本报告。 |

## 6. Files Modified

| 文件 | 最小改动 | Authority impact |
| --- | --- | --- |
| `hermes-runtime/src/hermes_runtime/infrastructure/fastapi_app.py` | 注入 `FactoryWorkspaceRenderer`；仅新增六条 HTML **GET** routes：`/home`、`/new`、`/drafts/{id}`、`/productions`、`/productions/{id}`、`/gates`。 | 无命令、无数据库、无状态变更、无 P6 import。 |

现有 P0–P5 authority、P6 Trial、migration、P6 evidence 和验收测试文件没有被修改。

## 7. Authority Boundary Verification

新增 renderer 仅包含 HTML/CSS、静态信息架构和导航。每页均明确显示：

> **DEMO / NON-AUTHORITATIVE UI FIXTURE — not connected to Project, Task, Execution, Worker, Gate, or P6 runtime authority.**

`/home` 的 “Start Planning” 是一个 **GET navigation** 到 `/drafts/demo-draft`，不是 Project 创建。六个新路由全部为 GET；没有 Draft POST、Project/Task/Execution/Gate mutation、Worker/scheduler control、raw SQL、P6 driver import 或 event insert。新增测试确认此路线和 import boundary。

## 8. P6 Compatibility Verification

`git diff --check` 通过。`git diff --name-only` 仅显示现有 `fastapi_app.py` 的 26 行 additive route injection；受保护的 migration、`trial/**`、P6 acceptance test、P6 report 和 evidence 都没有 tracked diff。新 renderer/test 是 untracked 新文件，不修改现有 authority source。

P6 standalone acceptance 在本地专用 PostgreSQL 16 容器上重新执行并通过：`Ran 1 test in 115.515s — OK`。该 test 是真实 Worker/Verifier/PostgreSQL 的 `tests.test_p6_autonomous_trial`，没有 mock。[2]

## 9. Tests

| 验证 | 结果 | 说明 |
| --- | --- | --- |
| `tests.test_factory_workspace_ui` | **PASS** — 4 tests. | routes、non-authoritative notice、GET-only、无 runtime authority imports。 |
| `test_fastapi_service_host` + `test_oidc_and_human_gate_ui` + Product API boundary/domain | **PASS** — 18 tests. | FastAPI、OIDC/Gate UI、API allowlist/metadata/safe response 回归。 |
| `compileall -q src` | **PASS**. | 新/改 Python source compile。 |
| P6 standalone acceptance | **PASS** — 1 test, 115.515 s. | Dedicated PostgreSQL + Golden Todo，真实 P6 autonomous trial。 |
| Full PostgreSQL suite | **NOT GREEN** — 510 run, 1 failure, 12 skipped. | `test_recovery_permissions.RecoveryPermissionTests.test_recovery_runtime_cannot_directly_write_authority_tables` 发现 `hermes_recovery_runtime` 可执行 `UPDATE public.tasks`。 |

最后一项失败不是本次 Workspace skeleton 所致：本轮 diff 没有触及 migration、recovery、Task authority 或 P6；当前 `0024_p6_autonomous_trial_runtime.sql` 第 506 行已有 `GRANT UPDATE ON public.tasks TO hermes_recovery_runtime`，而权限测试要求该角色被拒绝。这是当前分支已有的 P6/recovery permission contract conflict，必须作为单独、authority-reviewed 修复处理。本任务不会为使测试变绿而私自修改 P6 或权限模型。

## 10. Remaining Work

当前还不能提供真实用户入口。下一步必须按顺序实现：

1. `EntryDraft` persistence/authority 与 immutable revisions。
2. Entry semantic API and real product adapter wiring。
3. Understanding/Clarification/Assumption/Proposal/Master Plan compiler。
4. Approval Bridge，并用 existing Project/Graph/Verification commands materialize exactly once。
5. Portfolio/Gate/Live source-derived read models、snapshot/event freshness。
6. 把 renderer fixtures 替换为真实 query/semantic client，仍保持 Web 不直接写 authority。
7. Idea → approved plan → existing P6 run → delivery E2E trial。
8. 在 Entry work 之外解决 recovery-role grant 与 permission test 的现有冲突，并使完整 PostgreSQL suite 全绿。

## 11. Recommended Next Codex Task

**Title:** `Implement EntryDraft Core (E1) with PostgreSQL authority, immutable revisions, semantic receipts, and no Project materialization`.

该任务应只新增 `entry_drafts`、`entry_draft_revisions`（以及必要的 command receipts/roles/indexes），实现 Draft state/version/idempotency/authorization tests，并证明任何未批准 Draft 都不能创建 Project、Task、ExecutionRequest、Worker、Artifact 或 Evidence。它不得触碰 `trial/**`、`0023/0024`、P6 evidence、Scheduler、Worker、Recovery、Human Gate、Task/Project state machine。

## Direct Answer

**Proteus 现在是否已经具备从 Idea → Master Plan → Production → Live Production 的真实用户入口？**

**没有。** 当前已具备完整的架构基线、Recon、明确 authority boundary 和可导航的、显式标注为非权威的 Factory Workspace UI skeleton。真正缺少的是 server-authoritative EntryDraft/revisions、Master Plan compiler、ApproveEntryPlan/Approval Bridge、真实 API read/command wiring、Portfolio/Live projections 与 Idea-to-P6 E2E acceptance。当前 UI 不会也不能创建 Project；这正是本轮为保护 P6 authority chain 而刻意保持的边界。

## References

[1]: [`docs/P6_REPORT.md`](P6_REPORT.md)
[2]: [`hermes-runtime/tests/test_p6_autonomous_trial.py`](../hermes-runtime/tests/test_p6_autonomous_trial.py) and [`hermes-runtime/src/hermes_runtime/trial/`](../hermes-runtime/src/hermes_runtime/trial/)
[3]: [`hermes-runtime/src/hermes_runtime/application/product_api.py`](../hermes-runtime/src/hermes_runtime/application/product_api.py), [`infrastructure/fastapi_app.py`](../hermes-runtime/src/hermes_runtime/infrastructure/fastapi_app.py), and [`api_main.py`](../hermes-runtime/src/hermes_runtime/api_main.py)
[4]: [`docs/PROTEUS_PRODUCTION_ENTRY_ARCHITECTURE_V1.md`](PROTEUS_PRODUCTION_ENTRY_ARCHITECTURE_V1.md)
