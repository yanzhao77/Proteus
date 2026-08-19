# ENTRY_RECON — Proteus Production Entry / Factory Workspace

**审计分支：** `codex/p6-autonomous-production-trial`
**审计提交：** `bd55a9f`
**审计方式：** 只读检查当前源码、迁移、P6 Trial、Product API、最小 HTML UI、部署和测试；不把此前 UX 文档的建议误写成已经实现的能力。

## 1. Existing Frontend

当前仓库**没有** React、Vue、Next.js、Svelte、Vite、Tailwind 或已有的 SPA 前端。目录中没有 `package.json`、前端组件文件或前端样式工程。现有产品表面是 FastAPI 及最小服务端渲染的 Human Gate HTML：`hermes-runtime/src/hermes_runtime/application/human_gate_ui.py::HumanGateUiRenderer` 与 `infrastructure/fastapi_app.py` 的 `/ui/human-gates`、`/ui/human-gates/{gate_request_id}`。

结论：当前技术栈不允许“复用现有 SPA”；后续 Factory Workspace 应先采用与 FastAPI 兼容的最小 Web Workspace 架构，或在另行批准的前端项目中建立应用。不得在这次工作中擅自引入 React/Vue/Next/Tailwind/Three.js。

## 2. Existing APIs

`application/product_api.py::ProductApiFacade`、`ProductReadModel`、`ProductCommandGateway` 与 `infrastructure/fastapi_app.py::create_app` 已定义严格的 Product API boundary。当前可见路由为：

| 路径 | 现状 | 说明 |
| --- | --- | --- |
| `GET /projects/{project_id}/status` | Contract exists. | Project status read。 |
| `GET /decisions/{decision_id}/explain` | Contract exists. | Decision explain read。 |
| `GET /human-gates/{gate_request_id}` | Contract exists. | 单个 Gate read。 |
| `POST /human-gates/{gate_request_id}/decisions` | Contract exists. | 现有 Gate authority 的语义 decision 入口。 |
| `GET /projects/{project_id}/reconcile-findings` | Contract exists. | Replay/reconcile findings read。 |
| `GET /docker-processes/{process_id}/observations` | Contract exists. | Docker observation read。 |
| `/ui/human-gates*` | Minimal HTML. | Gate inbox/detail rendering；不是 Factory Workspace。 |

关键现实：`api_main.py::build_app` 当前组装 `EmptyReadModel` 与 `RejectingGateway`。因此路由/协议骨架存在，但真实 PostgreSQL read model 与真实产品 command gateway 尚未在默认 API app 中装配。Production Entry 不存在 Draft、Plan、Portfolio、Production list 或 Live Production API。

## 3. Existing Authority

Project/Task/Graph/Execution/Scheduler/Worker/Verification/Evidence/Human Gate/Recovery/Event authority 已存在且为唯一可信来源。命令在 `application/commands.py`，控制入口在 `application/handlers.py` 与 `application/ports.py`，数据库 authority 由 Postgres stores 和 migrations 管理。

- Project: `CreateProject`、`RequestProjectTransition`、`PauseProject`、`ResumeProject`、`CancelProject`；`0003_project_state_authority.sql` 的 `hermes_create_project_authority` 要求 `control_plane` actor 和 processing receipt。
- Graph: `ApplyWorkGraphPatch`、`RecomputeTaskReadiness`；Task/DAG 是现有 authority。
- Verification: `CreateVerificationPlan`、`RecordVerificationResult`、`ApplyVerifiedTaskTransition`。
- Human Gate: `domain/human_gate.py`、`postgres_human_gate.py`、`0018_human_gate_waiting_resume.sql`；是运行期审批/暂停/恢复 authority。
- Event: `event_log` 与 `outbox_messages` 是已有 transaction/event delivery 模式；不得新增 Entry Event Store。

## 4. Existing Project / Task Model

| 对象 | 真实实现 | 结论 |
| --- | --- | --- |
| Project | `domain/models.py`、`domain/project_state_machine.py`、`0003_project_state_authority.sql::projects`。 | 后端唯一的 Project authority。 |
| Task / Graph | `domain/graph.py`、`domain/state_machine.py`、`0001` tasks、`0002` DAG/work graph。 | Task 只应由 approved plan + existing control plane materialize。 |
| Runtime Plan | `domain/planner.py`、`0010::planning_runs,candidate_actions`。 | P6 runtime candidate actions，不是用户 Master Plan。 |
| Verification plan | `0006_verification_plan_agent_run_authority.sql`。 | 可在 Approval Bridge 后通过 existing command materialize。 |
| Project creation | P6 driver calls `ControlPlane.create_project(CreateProject)` then `ApplyWorkGraphPatch` then `CreateVerificationPlan`。 | 是 Approval Bridge 应复用的真实语义顺序。 |

## 5. Existing P6 Entry

P6 Trial 的输入是 `trial/driver.py::AutonomousRunDriver.run_happy_path(request, run_id)` 接收的受限 request mapping。它立即调用已有 `CreateProject`、`ApplyWorkGraphPatch`，并让 Task readiness 事件产生 Situation，随后进入 Planner/Policy/Risk/Selection/Capability/Execution/Worker/Verification/Recovery/Human Gate/Delivery。

这不是 Production Entry API 或正式 `software_requests` aggregate。当前没有 `software_requests` 表、`production_drafts` 表、Entry Draft command/API 或用户-facing request persistence。`trial/**` 是测试/证据 harness，不能被前端或 API 当作生产 authority 服务复用。

## 6. Existing Live Production

当前没有名为 Live Production Workspace 的实现。现有能力是底层 Project/Task/Gate/Verification/Evidence/Recovery authority、P5 Product API contract、P6 evidence bundles和最小 Gate HTML。`docs/PROTEUS_LIVE_PRODUCTION_UX_V1.md` 是设计资产，不是运行中的 UI。任何 Factory Home 只能导航到将来基于这些投影构建的 Live Production surface；不得复制 P6 driver 或新建 Workflow authority。

## 7. Existing Read Models

`ProductReadModel` 是 protocol，当前 API composition 使用 `EmptyReadModel`。当前不存在 Production Portfolio、Gate inbox list、Draft resume、Factory status 或 live workflow read model。现有 Project/Gate/decision/reconcile/Docker observation query contract 是可复用基础，但需要 concrete adapter、可验证 source fields、`as_of`/freshness 和授权作用域。

## 8. Existing Event Model

`0001_p0_completion_verification.sql` 的 `event_log`、`outbox_messages`，以及 `0005_event_delivery_recovery.sql`、`infrastructure/postgres_event_delivery.py`、`relay_once.py` 构成当前事件与可靠投递基础。P6 `0024` 延续该模式：执行准备、feedback 和 situation effect 在 authority transaction 中写 event/outbox。客户端实时状态必须采用 Snapshot first → subscribe → sequence/version validation → gap rehydrate；不能构建 Event-only UI 或私有 Entry outbox。

## 9. Existing Human Gate

Human Gate 已是成熟的运行期 authority：`domain/human_gate.py`、`infrastructure/postgres_human_gate.py`、`0018_human_gate_waiting_resume.sql`、Product API Gate route 和最小 HTML UI。它处理高风险命令、等待、授权断言与恢复上下文。

**Clarification is not Human Gate.** Production Entry 的产品意图澄清需要 Draft revision/question-answer 记录，不能把 `WAITING_FOR_HUMAN` 或 Gate request 用于收集普通需求。

## 10. Reusable Components

| 可复用基础 | 可复用方式 | 禁止误用 |
| --- | --- | --- |
| Command envelope/receipt | Draft/approval command 使用 actor、reason、idempotency、expected version、authorization。 | 不用 generic PATCH 或 UI SQL。 |
| Project/Graph/Verification commands | 只在 approved Plan 的 Approval Bridge 中委托。 | 不在 Idea/Proposal 阶段 materialize。 |
| `event_log`/outbox | Entry lifecycle 的重要事实如需要事件时复用既有机制。 | 不建新 Event Store/outbox。 |
| Product API facade | 扩展 allowlisted semantic Entry/Portfolio route。 | 不另建第二 API server。 |
| Gate query/detail | Action Required / Review navigation。 | 不从 Home 直接改 WAITING state。 |
| P6 runtime/evidence | 作为 approved Project 后的既有运行/验证链。 | 不直接 import driver/harness 做产品服务。 |
| Docker compose/API deploy | FastAPI host foundation。 | 不假设现有 API 已有真实 Entry read/command wiring。 |

## 11. Missing Components

1. 受限、版本化、可恢复的 `EntryDraft` authority。
2. Idea/Understanding/Clarification/Assumption/Proposal/Master Plan revision model。
3. Valid Plan approval command and Approval Bridge。
4. Draft-to-Project mapping and materialization recovery record。
5. Concrete Product API read model and command gateway wiring。
6. Production Portfolio projection、Factory status、Gate inbox list、resume query。
7. Factory Home / Draft / Plan review / Production detail Web routes and state boundaries。
8. API/authority/bridge/read-model/UI test coverage for the new path。

## 12. Conflicts / Risks

| Conflict / risk | Evidence | Required response |
| --- | --- | --- |
| Entry becomes second Control Plane. | Current Project/Task/Graph/Execution/Scheduler authority already exists and P6 proves it. | Entry stops at approval; bridge delegates existing commands only. |
| Draft directly reuses Project. | `CreateProject` already creates authoritative `CREATED` Project. | Do not create Project before plan approval. |
| Understanding reuses Situation. | Situation is P6 runtime event/failure analysis in `0008`/`0024`. | Use distinct Draft-derived understanding revision. |
| Clarification reuses Human Gate. | Gate manages runtime authorization/wait/resume. | Use Draft question/answer, not Gate. |
| Master Plan reuses planning run/candidate action. | P6 planning run selects runtime actions after Situation. | Keep user Master Plan revision separate; compile to existing graph/verification only after approval. |
| UI shows fake state. | Current API read model is placeholder; no live projection exists. | UI fixtures must be explicitly mock/non-authoritative; production state requires server snapshot. |
| P6 harness becomes user service. | `trial/**` uses Golden Todo/scenarios/evidence. | Treat only as integration contract/evidence source. |

## Recon Conclusion

Proteus has a verified autonomous factory Control Plane but **does not yet have a real user-facing Idea → Master Plan → Production → Live Production entry**. The next safe layer is EntryDraft + semantic API wiring + Approval Bridge + source-derived projection. The current branch does not justify a new Production aggregate, second Scheduler, second state machine, second Event Store or a SPA framework introduction.

## Primary Source Paths

- `hermes-runtime/src/hermes_runtime/application/product_api.py`
- `hermes-runtime/src/hermes_runtime/infrastructure/fastapi_app.py`
- `hermes-runtime/src/hermes_runtime/api_main.py`
- `hermes-runtime/src/hermes_runtime/application/commands.py`
- `hermes-runtime/src/hermes_runtime/application/handlers.py`
- `hermes-runtime/src/hermes_runtime/domain/project_state_machine.py`
- `hermes-runtime/src/hermes_runtime/domain/human_gate.py`
- `hermes-runtime/src/hermes_runtime/trial/driver.py`
- `hermes-runtime/migrations/0003_project_state_authority.sql`
- `hermes-runtime/migrations/0018_human_gate_waiting_resume.sql`
- `hermes-runtime/migrations/0024_p6_autonomous_trial_runtime.sql`
- `hermes-runtime/tests/test_p6_autonomous_trial.py`
- `docs/P6_REPORT.md`
