# Proteus Production Entry Implementation Plan V1.0

**文档性质：** Repository Architecture Discovery + 后续工程实施计划
**审计基线：** `codex/p6-autonomous-production-trial`，HEAD `bd55a9f`
**审计纪律：** 本文基于当前分支的代码、迁移、P6 证据和测试；本文不修改 P0–P6、迁移、测试、运行时或已有设计文档。
**结论状态：** **ARCHITECTURE DISCOVERY COMPLETE**

> **最终原则：** Production Entry 只能捕获批准前意图、管理可审计的 Draft/Plan Revision、发起语义化审批并读取既有事实。它不得建立第二套 Scheduler、Task/Project/DAG/Verification authority、Worker manager、Event Store、状态机或执行引擎。只有被明确批准的 Plan 才可经窄的 Approval Bridge 调用既有 Project Authority；其后完整复用已通过 P6 验收的运行时。

## 1. Executive Summary

当前分支已经拥有一条真实、受保护且经 P6 验收的 Control Plane：`Project/Task Graph → Situation → Diagnosis → Planning → Policy/Risk → Selection → Capability freeze → Execution admission → Scheduler/Worker → Verification/Evidence → Recovery/Replan → Human Gate → Delivery`。`docs/P6_REPORT.md` 将其标记为 **PASS**，并记录 Happy Path、Worker SIGKILL/lease requeue、重复命令幂等、artifact 篡改 fail-closed、Human Gate pause/resume、recovery/replan、独立验证和 ACCEPTED delivery；`tests/test_p6_autonomous_trial.py` 是对应验收入口。[1] [2]

Production Entry、Factory Home、Production Portfolio 和 Live Production 的最终用户概念尚未作为独立实现存在。当前 Product API 已具备严格请求边界和少数 query/Gate route，但 `api_main.py::build_app` 仍装配 `EmptyReadModel` 与 `RejectingGateway`，因此它不能被误称为已完成的可用 Entry API。[3] 代码证据表明，最小安全演进是：新增一个**严格限定于批准前**的 `EntryDraft` aggregate；把 `Production` 保持为现有 `Project` 的用户别名/投影；新增 Approval Bridge，把已批准的 Master Plan 编译为既有 `CreateProject`、`ApplyWorkGraphPatch` 和 `CreateVerificationPlan` 语义命令；再构建只读的 Factory Home/Portfolio 投影。该方案不改变 P6 authority chain。

| 关键决策 | 推荐 | 理由 |
| --- | --- | --- |
| Production Draft | 最小、版本化的独立 `EntryDraft` aggregate。 | 当前仓库没有能承载未批准 Idea、澄清、假设、Proposal、Plan Revision 与恢复的现有权威对象。 |
| Production | `Project` 的 user-facing alias/projection。 | 避免双状态机、双生命周期、同步事件和双 authority。 |
| Master Plan | EntryDraft 内的 versioned plan revision；不复用 P6 `planning_runs`。 | P6 Planner 的候选 action 是运行期决策，不是用户批准的产品计划。 |
| Approval | `ApproveEntryPlan` → narrow Approval Bridge → existing Project/Graph/Verification commands。 | 唯一可跨越 pre-approval 与 runtime 的边界。 |
| Factory Home | source-derived read model + Web composition。 | 不创建 Factory/Production authority；不在 UI 计算生命周期事实。 |
| API | 扩展现有 `ProductApiFacade`/gateway 的 allowlisted semantic commands。 | 沿用 actor、reason、idempotency、expected version、安全响应和 command receipt 模式。 |

## 2. Repository Architecture Findings

### 2.1 已验收的 P6 运行事实

P6 不是概念性 demo。`hermes_runtime.trial.driver::AutonomousRunDriver` 使用既有 application service/ports 驱动真实 Project 创建、Graph patch、Situation、Planner、Policy/Risk、Selection、Capability freeze、Execution、lease、真实 worker 子进程、独立 pytest verifier、recovery/replan 和 Human Gate。`trial/harness.py::run_trial` 与 `trial/scenarios.py` 分别编排 Happy Path、verification failure、duplicate execution、tampering、worker crash 和 human-gate 场景；`golden_worker.py` 和 `golden_verifier.py` 不是 authority，而是试验使用的真实执行/验证适配物。[2] [4]

`0024_p6_autonomous_trial_runtime.sql` 并没有创建并行运行时表。它替换/扩展 `hermes_prepare_execution_request`、`hermes_emit_execution_feedback`、`hermes_apply_situation_effect` 和 secret guard 函数，复用既有 `projects`、`tasks`、`decision_records`、`candidate_actions`、`policy_decisions`、`risk_assessments`、`capability_match_records`、`execution_requests`、`verification_*`、`situations`、`recovery_*`、`event_log` 和 `outbox_messages`。这证明 P6 的正确演进方式是**扩展已有 authority**，不是复制 authority。[5]

### 2.2 现有 API 和产品表面

`application/product_api.py::ProductApiFacade` 目前支持：Project status、Decision explain、单个 Human Gate read/decision、reconcile findings 和 Docker observations。`infrastructure/fastapi_app.py::create_app` 将它们暴露为 FastAPI 路由，并提供最小 `/ui/human-gates` HTML inbox/detail。该 UI 是 P5 Gate renderer，不是 Factory Home 或 Live Production Workspace。[3]

`api_main.py` 的 `EmptyReadModel` 和 `RejectingGateway` 是关键现实约束：当前 API application composition 尚未把真实 PostgreSQL read model 和真实 command gateway 装配到产品进程。实施 Production Entry 必须首先把这个 wiring gap 明确列入范围；不得根据存在 `ProductApiFacade` 接口就假设可直接执行真实 Entry command。[3]

### 2.3 当前不存在的能力

当前分支未发现 `entry_drafts`、`production_drafts`、`idea_revisions`、`clarifications`、`assumptions`、`proposals`、`productions`、`production_portfolio` 或对应 API/read model/测试。`clarification` 仅出现在 Human Gate 的等待类型词汇中；`proposal` 仅出现在 planner 内部 action 参数。二者均不等价于用户 Entry domain。P6 报告中的 “Software Request” 是 Trial driver 的受限输入和运行描述，不是已存在的持久化 aggregate、公开 API 或表。[1] [2] [5]

## 3. Current Authority Map

| 对象 | 代码与持久化证据 | 当前 authority / semantic command | Event、Read Model、API | 测试证据 |
| --- | --- | --- | --- | --- |
| Project | `domain/models.py::{Project,ProjectState}`；`domain/project_state_machine.py`；`0003_project_state_authority.sql::projects`。 | Project authority；`CreateProject`、`RequestProjectTransition`、`PauseProject`、`ResumeProject`、`CancelProject`。 | Project transition 写 `event_log` + `outbox_messages`；API 有 `/projects/{id}/status` contract。 | `test_project_*`、`test_project_permissions.py`、`test_project_guard_facts_postgres.py`。 |
| Task / DAG | `domain/models.py::{Task,TaskState}`、`domain/graph.py`、`domain/state_machine.py`；`0001` tasks，`0002` graph。 | Graph/Task authority；`ApplyWorkGraphPatch`、`RecomputeTaskReadiness`、verification transition。 | readiness/graph events；无 Entry-facing route。 | `test_graph_*`、verification tests。 |
| Runtime Plan / Action | `domain/planner.py`、`postgres_planner.py`；`0010::planning_runs,candidate_actions`。 | Planner produces candidate runtime actions. | Planning records/trace；不是用户 Master Plan API。 | `test_planner_*`。 |
| Decision / Selection | `domain/selection.py`；`0012::decision_records` 等。 | Selection authority；P6 Execution admission consumes selected action. | Decision/selection facts。 | `test_selection_*`、P6 test。 |
| Policy / Risk | `domain/policy.py`、`domain/risk.py`；`0011::policy_decisions,risk_assessments`。 | Policy/Risk authorities；may require Human Gate。 | P6 policy facts via `0023` producers。 | `test_policy_*`、`test_policy_risk_*`。 |
| Capability | `domain/capability.py`；`0013` capability/template/context/sandbox tables。 | Capability matching/freeze. | Inputs become execution admission references。 | `test_capability_*`、P6 test。 |
| Execution | `domain/execution.py`、`postgres_execution.py`；`0014::execution_requests,execution_queue_items`。 | Execution preparation/admission; `0024::hermes_prepare_execution_request` supports `implement`. | queue/outbox events。 | `test_execution_*`、`test_production_execution_*`、P6 test。 |
| Scheduler / Worker | `domain/scheduler.py`、`postgres_scheduler.py`；`domain/worker_execution.py`、`postgres_worker_execution.py`；`0015/0016`。 | Single lease/fencing and result-admission authorities. | lease/result events. | `test_scheduler_*`、`test_worker_execution_*`、worker-crash scenario。 |
| Verification / Evidence / Artifact | `domain/state_machine.py`、`domain/evidence_invalidation.py`；`0001` artifacts，`0006` verification tables。 | Independent verification/evidence validity authority. | Verification/evidence events; no full live API today。 | verification/evidence/artifact tests; tamper scenario。 |
| Human Gate | `domain/human_gate.py`、`postgres_human_gate.py`；`0018::human_gate_*`。 | Gate decision, wait/resume context and authorization authority。 | existing Gate GET/POST route and minimal UI。 | `test_human_gate_*`、P5 UI tests、P6 Gate scenario。 |
| Recovery / Replan | `domain/recovery.py`、`postgres_recovery.py`；`0017::recovery_*`。 | feedback/recovery attempt authority; P6 re-enters work using official paths。 | feedback/recovery events; Situation is event-driven。 | `test_recovery_*`、`test_replay_reconcile_*`、P6 failure recovery。 |
| Situation / Diagnosis | `domain/situation.py`/`postgres_situation.py`/`0008`; `domain/diagnosis.py`/`0009`。 | Runtime situation/diagnosis authority. | `situation.detected/updated/superseded` etc. | `test_situation_*`、`test_diagnosis_*`。 |
| Event / Outbox | `0001::event_log,outbox_messages`，`0005` delivery/recovery，`postgres_event_delivery.py`，`relay_once.py`。 | Domain transaction owns append; relay owns delivery. | retry, DLQ, checkpoint, reconcile. | `test_event_delivery_postgres.py`。 |
| Product API / Read Model | `ProductApiFacade`、`ProductReadModel`、`ProductCommandGateway`、`fastapi_app.py`、`api_main.py`。 | Query facade; only Gate decision forwarding is a current command path. | route contracts exist; default concrete composition is placeholder. | `test_public_api_*`、`test_fastapi_service_host.py`。 |
| P6 Trial | `trial/driver.py::AutonomousRunDriver`、`harness.py::run_trial`、`scenarios.py`、`0024`。 | Test harness orchestrates existing authorities. | evidence bundles under `docs/evidence/p6`. | `test_p6_autonomous_trial.py` 8/8. |

## 4. P0–P6 Capability Inventory

| Phase | Verified capability | Primary evidence | Entry reuse boundary |
| --- | --- | --- | --- |
| P0 | Task completion, artifacts, event/outbox fundamentals. | `0001_p0_completion_verification.sql` and core tests. | Reuse artifacts/events only through authority paths. |
| P1 | Situation, diagnosis, candidate planning, policy/risk, selection, capability. | `0008`–`0013`; domain/postgres tests. | Runtime intelligence begins after approved Project/Graph is materialized. |
| P2 | Execution request queue, scheduler lease/fencing, worker result admission, recovery loop. | `0014`–`0017`; execution/scheduler/worker/recovery tests. | Never copy or invoke from UI directly. |
| P3 | Human Gate, replay/reconcile, quarantine/evidence invalidation, explain trace, Docker adapter. | `0018`–`0022`; corresponding tests. | Gate can be linked/navigated; Entry clarification is not Gate. |
| P4 | Productization/hardening APIs and operations. | `P4` docs/tests, FastAPI boundary. | Reuse facade/security rules rather than another server. |
| P5 | Deployable API, OIDC/Gate UI, health/readiness, single-node compose. | `api_main.py`、`fastapi_app.py`、`deploy/p5/docker-compose.single-node.yml`、P5 tests. | Build Factory Home as new product surface, not by expanding static Gate HTML. |
| P6 | Autonomous software production trial and guard-fact runtime closure. | `0023`、`0024`、`trial/**`、P6 report/evidence/test. | Immutable runtime dependency; Entry only crosses at approved bridge. |

## 5. Production Entry Gap Analysis

| Concept | Classification | Existing counterpart | Gap and recommended implementation | DB/API/Event/Read/UI | P6 relationship |
| --- | --- | --- | --- | --- | --- |
| Production Draft | **D: new domain capability**. | None; Project begins at `CREATED`. | Minimal versioned `EntryDraft` aggregate. | New persistence/API/events/read/UI. | Fully pre-P6. |
| Idea Revision | **D: Draft revision child**, not independent aggregate. | None. | Immutable typed revision under Draft. | Draft revision persistence/API/UI. | No runtime mutation. |
| Understanding | **C: derived Draft projection**. | Situation is not equivalent. | Generated/confirmed revision with provenance; **DO NOT IMPLEMENT AS NEW DOMAIN**. | Draft storage/API/UI. | Do not reuse `situations`. |
| Clarification | **C/D: Draft interaction record**. | Human Gate `clarification` waiting type is runtime authorization. | Draft question/answer revisions; **do not reuse Human Gate**. | Draft child/JSON/API/UI. | Preserve Gate semantics. |
| Assumption | **C: Draft metadata**. | Runtime constraints/policy facts differ. | Explicit accepted assumption entries; **DO NOT IMPLEMENT AS NEW DOMAIN**. | Draft revision/API/UI. | Snapshot into approved plan. |
| Proposal | **C: compiled Draft projection**. | Candidate actions/decisions are runtime objects. | Generated proposal revision; **do not reuse candidate actions**. | Draft revision/API/UI. | Zero execution before approval. |
| Master Plan Review | **B: new Entry surface**. | Verification plan/planning run are related but semantically different. | Versioned Entry Master Plan + review/approval. | Draft plan persistence/API/UI. | Compile into existing graph/verification at bridge. |
| Production Portfolio | **C: projection only**. | Project/Gate/Verification/Evidence facts. | Source-derived read model; **no productions authority/table**. | Query/API/UI; optional projection only. | Read-only. |
| Production Creation | **B: bridge adaptation**. | `CreateProject` + graph + verification commands. | `ApproveEntryPlan` bridge delegates existing commands. | Bridge command/receipt/mapping/read. | The only Entry→P6 crossing. |
| Resume Experience | **C: projection/navigation**. | Draft revisions, Project state, Gate `ResumeContext`. | Compose sources; **DO NOT IMPLEMENT AS NEW DOMAIN**. | Query/UI. | Existing resume command remains authority. |
| Factory Home | **C: application composition**. | Product API facade + minimal Gate UI. | Web read surface and Draft launch point. | Read API/UI only. | No runtime owner. |
| Entry API | **D: new semantic facade**. | Existing Product API shape/metadata. | Extend `ProductApiFacade`, not second server. | Routes/DTOs/contract tests. | Enforces envelope discipline. |
| Portfolio Read Model | **D: new derived projection**. | `ProductReadModel` protocol only. | Concrete source-derived query implementation. | Query source/API/UI. | No new fact source. |
| Approval Bridge | **D: new application orchestration**. | P6 driver sequence demonstrates existing command order but is harness-only. | Narrow bridge service with recovery receipts. | bridge persistence/API/events/tests. | Must not import/use trial as product path. |

## 6. Production Draft Architecture Decision

### 6.1 Options Compared

| Dimension | A. Independent `EntryDraft` aggregate | B. Entry projection/revision layer only | C. Upstream Software Request / Plan Authority input |
| --- | --- | --- | --- |
| Authority | Owns only pre-approval intent lifecycle. | Owns nothing; requires existing source. | Would rely on formal Software Request authority. |
| Existing persistence fit | Requires small new schema. | No existing object captures full user intent. | No formal `software_requests` table/API/aggregate exists. |
| Versioning / audit | Straightforward immutable revisions and expected version. | Cannot audit first-class Draft changes. | Would require new formal authority anyway. |
| Recovery / concurrency | Draft-local idempotency and resume before Project exists. | No source for conflict/recovery. | Conflates P6 harness input with product domain. |
| Migration/API cost | Minimum viable: header, revisions, bridge link. | Low apparent cost but does not satisfy requirements. | At least A’s cost plus deeper P6 semantic coupling. |
| P6 compatibility | High: no P6 object before approval. | Low utility. | Medium/low now; expands P6 surface too early. |

### 6.2 Recommended Option

**RECOMMENDED OPTION: A — a constrained, independent `EntryDraft` aggregate.** This is not domain inflation: the repository currently has no authority that can preserve user Idea, progressive clarification, explicit assumptions, Proposal, unapproved Master Plan revision, user-facing resume and safe concurrency. It must stop at the approval boundary. It may not own Scheduler, Project/Task Graph, Execution, Worker, Verification, Evidence, Artifact or P6 delivery state.

The aggregate lifecycle should be `DRAFT → UNDERSTOOD → NEEDS_INPUT | PROPOSED → PLAN_READY → APPROVAL_PROCESSING → MATERIALIZED | APPROVAL_FAILED | ARCHIVED`. These are Entry-only states. They must never mirror `ProjectState` or `TaskState`.

## 7. Production vs Project Decision

**RECOMMENDED: `Production = Project alias / projection`.** The user-facing name “Production” should be a view-model vocabulary for a Project that has been created via the approved bridge. A Portfolio card may contain `production_id` equal to a stable display/reference alias, but its lifecycle, state, graph, Gate, evidence and delivery facts resolve from the existing Project aggregate and related authority sources.

| Alternative | Decision | Reason |
| --- | --- | --- |
| `Production → Project` mapping with no lifecycle authority. | Allowed only as Draft-to-Project mapping/projection. | Supports user terminology without introducing a second state machine. |
| `Production = Project` alias/projection. | **Implement now.** | One lifecycle, one event chain, no sync problem. |
| Independent Production aggregate + Project. | **DO NOT IMPLEMENT AS NEW DOMAIN.** | No code evidence justifies it; it creates double lifecycle, event synchronization, migration/API overhead and Plan Mutation complexity. |

A future independent Production aggregate needs a separate ADR and evidence that one user Production must own multiple independent Projects with distinct authorization, audit and lifecycle. That condition is not present in this repository discovery.

## 8. Idea → Software Request → Plan Authority Bridge

The current P6 driver begins its test flow by accepting a request mapping, then calling `ControlPlane.create_project(CreateProject)`, applying `ApplyWorkGraphPatch`, letting the resulting readiness event create a Situation, and continuing through planner/policy/risk/selection/capability/execution.[4] It does not provide a public, persistent Software Request authority.

The recommended bridge is therefore:

```text
Idea
  → EntryDraft revision
  → Understanding / clarification / assumptions / proposal
  → Entry Master Plan revision (hash + approval policy)
  → ApproveEntryPlan semantic command
  → Approval Bridge validates draft/plan version and compiles GraphPatch + VerificationPlan
  → existing CreateProject
  → existing ApplyWorkGraphPatch
  → existing CreateVerificationPlan
  → existing task.readiness event
  → P6 Situation → Planner → Policy/Risk → Selection → Capability → Execution...
```

The bridge must be a **recoverable saga**, not raw cross-table SQL and not a new monolithic transaction. Each child command owns its existing database transaction, event and outbox behavior. The bridge stores child command IDs and queries existing command receipts/source facts during retry. It never deletes partially materialized Project/Task state with SQL; it resumes or surfaces a controlled bridge failure for operator review.

## 9. Factory Home Architecture

Factory Home is a Web composition of four source-derived decks: **Create Production** (EntryDraft command surface), **Action Required** (Human Gate/failure summaries), **Continue Production** (Project alias portfolio), and **Factory Status** (actual product/runtime availability). It reads a concrete `ProductReadModel` implementation; it does not query database tables in the browser, compute Project lifecycle from events, or run a local scheduler.

| Area | Responsibility | Source | Prohibited responsibility |
| --- | --- | --- | --- |
| Factory Home | Portfolio, attention, Draft entry/resume navigation. | Portfolio projection, Gate query, Draft query, health. | Direct Project/Task/Execution mutation. |
| Production Entry | Pre-approval Draft and plan interaction. | EntryDraft authority. | Runtime Scheduling/Worker/Artifact/Evidence. |
| Live Production | One Project’s real state, graph, Gate, evidence, progress basis. | Existing Project/Gate/verification/evidence read sources. | New Project/Task state machine. |
| Control Plane | Commands, guards, state transitions, queues, verification closure. | Existing P0–P5 modules. | UX-specific Draft logic. |
| P6 Runtime | Autonomous execution and tested recovery loop. | `trial/**`, existing runtime authority. | General Web entry or Portfolio ownership. |

## 10. Production Portfolio Read Model

The Portfolio is a read model, not an aggregate. The first implementation may be a bounded query adapter; a materialized projection table should be added only when performance/rebuild requirements justify it.

| Required card field | Existing source | Status | UI must not compute |
| --- | --- | --- | --- |
| `production_id` | Project ID or EntryDraft→Project mapping. | Adapt/New mapping. | Generate separate lifecycle ID. |
| `project_id`, `name`, `status` | `projects` and Project transition authority. | Exists. | Infer terminal state from logs. |
| `phase` | Project state or mapped current phase. | Adapt. | Invent a phase from Task count. |
| `progress` | Only authority-derived projection with named `progress_basis`; otherwise null. | New projection rule. | Compute arbitrary percentage in UI. |
| `current_node`, `blocker` | Task graph/readiness, Gate, recovery facts. | Adapt/new query. | Choose “current” locally from unordered events. |
| `gate_count` | `human_gate_requests` scoped query. | Adapt/new list query. | Count rendered cards only. |
| `owner`, `updated_at` | Project/Entry mapping and transition timestamps. | Adapt. | Use browser timestamp. |
| `health` | Actual Control Plane/worker/event stream health read model. | New query assembly. | Show fake CPU/RAM/network telemetry. |
| `plan_revision` | Entry approved plan revision/hash + bridge mapping. | New bridge projection. | Claim P6 `planning_run` is Master Plan revision. |

Each query response must carry `as_of`, source/projection version and freshness. A disconnected event stream marks cards stale and triggers Snapshot rehydration; it cannot make the browser infer a final Project state.

## 11. Entry API Design

### 11.1 Existing / Adapt / New

| Capability | Classification | Current evidence | Minimum path |
| --- | --- | --- | --- |
| Create Draft | NEW | No route/store. | `POST /entry-drafts:begin` → `BeginEntryDraft`. |
| Update Idea | NEW | No route/store. | `POST /entry-drafts/{id}:amend-idea`. |
| Get Draft / Resume | NEW | No Draft read model. | `GET /entry-drafts/{id}` and user-scoped resume query. |
| Understanding | NEW | Situation is incompatible semantic. | Generate/confirm semantic commands. |
| Clarification | NEW | Human Gate clarification is incompatible. | Answer-clarification command. |
| Assumption | NEW | No Entry fact. | Record/accept assumptions commands. |
| Proposal | NEW | Candidate action is runtime-only. | Generate/revise proposal commands. |
| Master Plan | NEW | No Entry plan API. | Generate/revise/read plan revision. |
| Approve Plan | NEW bridge | Current project create command is internal ControlPlane. | `POST /entry-drafts/{id}:approve-plan`. |
| Production List | NEW read | No portfolio route/read model. | `GET /productions`. |
| Production Snapshot | ADAPT | `GET /projects/{id}/status` contract exists but placeholder composition. | Real Project Snapshot query plus user projection. |
| Gate Inbox | ADAPT | Single Gate query/minimal UI exists. | User-scoped Gate list projection. |
| Resume runtime | ADAPT | Human Gate/project resume semantics exist. | Navigation + existing Gate decision flow. |

All mutating endpoints use the existing request envelope discipline: authenticated actor, nonempty reason, `Idempotency-Key`, expected version, authorization reference where required, canonical payload hash, command receipt and safe response. Do not offer generic `PATCH /projects/{id}`, `PATCH /tasks/{id}`, generic state fields, UI SQL or raw event submission.

## 12. Entry Persistence Strategy

The first Entry migration should be deliberately small.

| Proposed persistence | Purpose | Minimum key fields | Explicit exclusions |
| --- | --- | --- | --- |
| `entry_drafts` | Aggregate header/concurrency/lifecycle. | draft ID, owner/requester, state, version, current revision refs, approved plan hash, nullable project ID, timestamps. | Project/Task/Execution/Scheduler state. |
| `entry_draft_revisions` | Immutable Idea/understanding/clarification/assumption/proposal/plan payloads. | draft ID, ordinal, kind, canonical payload/hash, provenance, actor/generated-by, reason, timestamps. | Secret values, Worker config, credentials. |
| `entry_approval_bridges` | Recoverable approval saga/link. | draft/plan revision/hash, approval receipt, correlation ID, project ID, child command IDs/status. | Parallel graph/event log/runtime truth. |

Do **not** add `productions`, `production_states`, `entry_event_log`, `entry_outbox`, `entry_tasks`, `entry_workers` or `entry_execution_requests`. Normalize clarification/assumption/proposal child tables only after an evidence-backed need for independent query, retention, authorization or concurrency emerges; until then they are typed immutable revisions.

## 13. Event / Projection Strategy

New Entry domain events, if added, must use the existing `event_log` and `outbox_messages` transactional mechanism: `entry_draft.begun`, `entry_revision.amended`, `entry_understanding.confirmed`, `entry_plan.generated`, `entry_plan.approval_requested`, `entry_plan.approved`, `entry_bridge.materialized`, `entry_bridge.failed`. They represent Entry lifecycle only.

Typing, form focus, filters, local composer state and unsubmitted text are not domain events. Project state, Task readiness, execution, verification, recovery, Gate and delivery events remain exclusively owned by existing authorities. Portfolio projection is rebuildable from source Project/Gate/verification/evidence/event facts plus the optional Draft-to-Project mapping. No separate Entry event store, outbox or consumer checkpoint system may be introduced.

## 14. Approval Bridge

| Step | Authority | Required semantic action | Result |
| --- | --- | --- | --- |
| 1 | EntryDraft | `ApproveEntryPlan`; validate actor/reason/idempotency/expected revision/plan hash. | Bridge receipt `PROCESSING`; no Project. |
| 2 | Entry compiler | Convert approved Entry plan into existing `GraphPatch` and `VerificationPlan` values. | Deterministic compiled plan reference. |
| 3 | Existing Project authority | `ControlPlane.create_project(CreateProject)`. | Existing Project `CREATED`, receipt/event/outbox. |
| 4 | Existing Graph authority | `ControlPlane.apply_work_graph_patch(ApplyWorkGraphPatch)`. | Existing Task/DAG/readiness event. |
| 5 | Existing Verification authority | `ControlPlane.create_verification_plan(CreateVerificationPlan)`. | Existing verification plan. |
| 6 | EntryDraft | Mark materialized only after child command/source reconciliation. | Draft→Project link for Portfolio. |
| 7 | Existing P6 runtime | Consume legitimate Project/Task readiness and proceed normally. | Situation onward; no Entry scheduler call. |

`hermes_create_project_authority` requires a `control_plane` actor and a processing command receipt. The bridge therefore must call the approved application handler/port with a properly formed control-plane envelope, preserving the user as requester and retaining the approving user’s reason/correlation. It must not call the SQL function from a Web handler.[6]

## 15. Live Production Boundary

Live Production is the read/control experience for an existing Project after materialization. It may show the Graph, state, Gate, Evidence, Verification, Recovery and Delivery facts; it may request existing guarded actions through semantic commands and preview/Gate procedures. It must not duplicate the Entry plan revision store, P6 driver, Scheduler loop or Task/Project state machine.

Factory Home is cross-production navigation/read composition. Production Entry is pre-approval intent authority. Live Production is one-Project projection/controlled-command surface. Control Plane is the only runtime authority. P6 Runtime is the validated autonomous execution path. These are distinct layers, not alternate implementations of the same lifecycle.

## 16. Web / TUI / API Boundary

The repository has a FastAPI Product API and a minimal server-rendered Human Gate UI. It does **not** currently contain a general TUI; `relay_once.py` is an argparse operational CLI, not an end-user control console. The recommended target is therefore:

| Surface | Role | Current status | Rule |
| --- | --- | --- | --- |
| Web | User-facing Production Factory: Draft, review, Portfolio, Live projection, Gate navigation. | New except minimal Gate HTML. | Uses semantic API and read models only. |
| TUI / CLI | Operator/developer diagnostics, relay/supervisor commands and low-level support. | Limited operational CLI exists. | No primary end-user Entry workflow; never bypass authority. |
| API | Machine and Web interface to queries/semantic commands. | Facade contract exists; real composition wiring incomplete. | Canonical external command/read boundary. |

## 17. Security / Authorization

The existing command boundary checks actor, requester, reason, command type, expected version and authorization reference. Product API has actor header/body parsing, request IDs, `Idempotency-Key` enforcement for Gate command and safe response filtering, but API production wiring and full OIDC enforcement must be verified/strengthened before Entry release.[3]

Entry controls must include: authenticated owner/reader/approver roles; strict Draft ownership and collaborator scopes; no raw actor spoofing from client body; plan approval authorization; authorization reference when required; secret rejection/redaction in Idea/revision/event/telemetry; allowlisted attachment references; safe error responses; and audit correlation from Draft command to Project child commands. An approver may approve a plan but cannot obtain direct Scheduler/Worker control through Entry.

## 18. Versioning / Idempotency / Concurrency

`EntryDraft.version` and each Master Plan revision are optimistic concurrency boundaries. Every mutation requires expected draft version; plan approval additionally requires reviewed plan revision and content hash. Each command has an idempotency key; bridge child commands use deterministically derived, auditable child keys. On timeout, the client re-queries the same receipt/bridge state instead of resubmitting a new approval.

A bridge in `PROCESSING` reconciles existing Project/Graph/Verification command receipts and source facts. It can resume the next missing child command but never creates an additional Project. `409` shows current revision/diff/reapply instructions; it never uses last-write-wins. Browser-local storage can retain unsent non-secret Idea text only and must label it unsaved; accepted Draft data is server authority.

## 19. Failure / Recovery UX

| Failure | Entry behavior | Runtime behavior |
| --- | --- | --- |
| Draft command rejection | Preserve input/revision, show safe reason and correction action. | None; P6 untouched. |
| LLM/generated understanding/proposal failure | Mark generated revision failed/retryable; retain prior user facts. | None. |
| Plan hash/version conflict | Stop approval; reload/review newest revision. | No Project/Task created. |
| Approval bridge partial completion | Show `MATERIALIZATION IN PROGRESS`; query child receipts/source; operator review when unresolved. | Existing child command invariants preserved. |
| Project/Graph/verification child reject | Mark bridge failed with correlation; do not raw rollback. | Existing authority decides source state. |
| Running Production failure | Navigate to Live Production/recovery/Gate projection. | Existing P6 recovery/replan/Human Gate handles it. |
| Stream/read model stale | Mark Snapshot stale and rehydrate. | Do not infer execution outcome. |

## 20. Implementation Phases

| Phase | Goal | Scope / files | DB/API/events/read models | Tests / acceptance | Dependencies and risk |
| --- | --- | --- | --- | --- | --- |
| E0 — Contract Foundation | Freeze Entry boundary before code. | ADR + ports/fixture contracts; inspect API composition. | No migration; define envelope/receipt/draft DTO. | Contract tests reject Project/Task/Execution fields. | Must not change P6. |
| E1 — EntryDraft Core | Persist safe pre-approval lifecycle. | New Entry domain/application/Postgres modules; `0025` migration. | Draft/revision/receipt operations; existing event/outbox. | version/idempotency/authorization/Postgres tests. | No Project before approval. |
| E2 — Understanding / Clarification / Assumption | Add typed revisions. | New Entry command handlers/views. | Revision kinds and read view; no Human Gate reuse. | unresolved clarification/assumption and retry tests. | Terminology collision with Situation/Gate. |
| E3 — Proposal / Master Plan | Compile user intent into plan revision. | Entry compiler/validator. | Plan revision/hash/read route. | deterministic compile, hash, plan validation tests. | Must not reuse P6 runtime planning run. |
| E4 — Approval Bridge | Materialize approved plan via existing authority. | New bridge service/adapter; modify only approved application boundary files. | Bridge mapping/receipts/events; existing child commands. | duplicate approval, partial bridge recovery, no raw SQL, P6 chain E2E. | Highest-risk phase. |
| E5 — Product API / Read Model | Wire real query/gateway and Portfolio. | `product_api.py`, `fastapi_app.py`, `api_main.py`, concrete read adapter. | Entry semantic routes; Portfolio/Gate/Project Snapshot queries. | API contract/permission/wiring tests. | Current placeholder wiring must be replaced safely. |
| E6 — Factory Home / Resume | Build Web read surface. | New Web project/component code outside runtime authority. | Draft/Portfolio/Gate query usage. | keyboard/loading/stale/read-only boundary tests. | UI cannot mutate runtime state. |
| E7 — Live Production Integration | Read/project/Gate/evidence integration. | New projection adapters/UI routes. | source-derived snapshot/event hydration. | live state, gate navigation, stale/reconnect tests. | No second state machine. |
| E8 — Production Entry Trial | Prove Idea → approval → existing P6 delivery. | E2E harness/fixture/evidence only, with separately approved test additions. | Correlation through Draft/bridge/Project/P6. | Existing P6 8/8 plus new entry acceptance all pass. | Requires P6 regression gate. |

## 21. File-Level Change Plan

The following is a **future implementation plan**, not a change made by this discovery task.

| Category | Existing path / proposed new path | Planned responsibility |
| --- | --- | --- |
| New | `hermes-runtime/src/hermes_runtime/domain/entry_draft.py` | EntryDraft lifecycle, revision kinds, invariants. |
| New | `hermes-runtime/src/hermes_runtime/application/entry_commands.py` | Begin/amend/confirm/generate/approve command DTOs. |
| New | `hermes-runtime/src/hermes_runtime/application/entry_handlers.py` | EntryDraft command handlers and approval bridge orchestration. |
| New | `hermes-runtime/src/hermes_runtime/application/entry_ports.py` | Draft store, plan compiler, bridge/query ports. |
| New | `hermes-runtime/src/hermes_runtime/infrastructure/postgres_entry_draft.py` | Draft/revision/bridge persistence using existing command/event rules. |
| New | `hermes-runtime/src/hermes_runtime/infrastructure/postgres_factory_read_model.py` | Source-derived Draft/Portfolio/Gate/Project query adapter. |
| New | `hermes-runtime/tests/test_entry_draft_domain.py` | Draft invariants. |
| New | `hermes-runtime/tests/test_entry_draft_postgres.py` | versions, receipts, transaction/event behavior. |
| New | `hermes-runtime/tests/test_entry_api_boundary.py` | allowlisted routes, forbidden authority shapes, actor/security. |
| New | `hermes-runtime/tests/test_entry_approval_bridge.py` | child command sequence, duplicate/recovery/P6 compatibility. |
| Modify | `application/product_api.py` | Add allowlisted Entry/Portfolio route mapping and query ports. |
| Modify | `infrastructure/fastapi_app.py` | Bind request parsing/route methods to facade only. |
| Modify | `api_main.py` | Replace selected placeholder components with real configured adapters after test coverage. |
| Modify | `application/ports.py` / `application/handlers.py` | Only if an existing official ControlPlane port is needed by the bridge; no lifecycle rule changes. |
| New | `hermes-runtime/migrations/0025_production_entry_drafts.sql` | Minimal EntryDraft/revision/bridge schema, grants, functions/indexes. |
| Do not modify in Entry work | `trial/**`, P6 test/evidence/0023/0024, runtime authority domain modules. | Protected non-regression zone. |

## 22. Database Migration Plan

A future `0025_production_entry_drafts.sql` should: create `entry_drafts`, `entry_draft_revisions`, `entry_approval_bridges`; add strict foreign keys/unique `draft_id + revision`; enforce owner/state/version; forbid secret-bearing payloads; record command/approval correlation; provide indexes for owner/resume and `project_id`; use role grants consistent with current migration governance; and write Entry events via existing transaction/outbox mechanisms.

It must **not** create `productions`, `production_states`, `entry_tasks`, `entry_scheduler`, `entry_workers`, `entry_execution_requests`, `entry_event_log`, `entry_outbox`, or a parallel verification system. A Portfolio projection table is deferred: first ship a bounded query adapter; add a materialized/rebuildable projection only after measured latency/volume warrants it.

## 23. API Migration Plan

1. Keep `ProductApiFacade` as the one product API boundary and preserve `{data,error,request_id}`/safe response semantics.
2. Add semantic Entry command routes behind authentication and feature gating; prohibit generic CRUD/state PATCH.
3. Implement concrete `ProductReadModel` and `ProductCommandGateway` adapters, replacing `EmptyReadModel`/`RejectingGateway` only for configured, tested capabilities.
4. Add user-scoped Portfolio, Draft and Gate inbox queries with `as_of`, projection/source version and freshness.
5. Add OpenAPI/contract tests for headers, idempotency, expected version, authorization, forbidden field shapes, safe errors and receipt/projection distinction.
6. Do not expose P6 trial driver endpoints as production API merely because it accepts a request mapping.

## 24. Test Strategy

| Test layer | Required proof |
| --- | --- |
| Domain | Draft lifecycle, unresolved questions, plan readiness, plan hash, no Project reference before approval. |
| PostgreSQL | revision concurrency, command receipt idempotency, Entry event/outbox atomicity, secret rejection, bridge records. |
| API boundary | actor/auth, reason/key/version required, prohibited state fields rejected, receipt vs applied projection semantics. |
| Bridge integration | `ApproveEntryPlan` invokes existing `CreateProject` → `ApplyWorkGraphPatch` → `CreateVerificationPlan`; duplicate approval produces one Project; partial bridge resumes through receipts. |
| Read model | Portfolio mapping, Gate counts, stale/as-of, no UI-derived lifecycle/progress. |
| Web | Draft resume, empty/loading/error/stale, keyboard/accessibility, Gate navigation only. |
| E2E | Idea → approved plan → Project/Task readiness → P6 run → verification/recovery/gate/delivery. |
| Regression | Existing P0–P5 tests, existing P6 8/8, PostgreSQL migration continuity, compileall, secret scan, Docker/deployment checks. |

## 25. Acceptance Criteria

| ID | Criterion |
| --- | --- |
| AC-E-01 | No Entry mutation can create Project, Task, ExecutionRequest, Worker, Artifact or Evidence before approved Plan. |
| AC-E-02 | Draft/plan revisions are versioned, idempotent, auditable and recoverable without P6 state. |
| AC-E-03 | Understanding is not stored as Situation; clarification does not create Human Gate; Proposal is not a P6 candidate action. |
| AC-E-04 | `Production` Portfolio resolves authoritative runtime state solely from Project/Gate/verification/evidence sources. |
| AC-E-05 | Approve command validates plan hash/version and creates at most one Project under duplicate/concurrent delivery. |
| AC-E-06 | Bridge uses existing application ports/semantic commands and never direct SQL to projects/tasks/queues/events. |
| AC-E-07 | Bridge partial failure is reconcilable from receipts/source facts and never raw-deletes existing authority data. |
| AC-E-08 | Factory Home uses a concrete read model and marks stale data; browser does not compute final lifecycle/progress. |
| AC-E-09 | Product API real wiring replaces placeholders only with contract/permission coverage. |
| AC-E-10 | Human Gate remains the only runtime pause/resume authority. |
| AC-E-11 | Existing P6 8/8, P0–P5 regression, migration continuity, compileall and secret scan remain green. |
| AC-E-12 | No second Scheduler, Task/Project/DAG/Verification authority, Event Store or Worker manager appears in new code/migration. |

## 26. P0–P6 Non-Regression Rules

The following zones are protected during Entry implementation unless a separate approved P6 change specifically authorizes them: `hermes-runtime/src/hermes_runtime/trial/**`; `hermes-runtime/tests/test_p6_autonomous_trial.py`; `hermes-runtime/migrations/0023_project_guard_fact_producers.sql`; `hermes-runtime/migrations/0024_p6_autonomous_trial_runtime.sql`; `docs/P6_REPORT.md`; `docs/P6_AUTONOMOUS_PRODUCTION_TRIAL_PLAN.md`; `docs/evidence/p6/**`; existing `domain/{execution,scheduler,worker_execution,human_gate,recovery,state_machine,evidence_invalidation}.py`; and P0–P5 migration chain `0001`–`0022`.

Entry is permitted to use adapters/ports around existing command handlers, query stores and Product API. It is not permitted to refactor the P6 trial driver into a product service, alter guard-fact semantics, change lease/fencing, weaken verification closure, introduce direct write paths, or adjust P6 evidence to make new behavior appear accepted.

## 27. Architecture Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Treating P6 harness as product service. | Bypasses product authorization/lifecycle and couples UI to test behavior. | Extract contracts only; keep `trial/**` test-only. |
| Draft becomes an implicit Project. | Violates approval boundary and creates orphan runtime objects. | No Project ID/graph/runtime operations until approved bridge. |
| New Production aggregate. | Double state/events/migrations. | Project alias/projection now; ADR required for any future aggregate. |
| Reusing Situation/Human Gate/planning run semantics. | Semantic collision and runtime corruption. | Separate typed Draft revisions; explicit anti-reuse tests. |
| Placeholder API wiring left in production. | UI appears functional but queries/commands are unavailable/rejected. | Concrete adapter wiring + host/E2E tests before release. |
| Bridge partial materialization. | Duplicate Project or opaque failure. | deterministic child keys, bridge receipt/saga, source reconciliation. |
| Portfolio invents facts. | Users make decisions from incorrect live status. | source version/as-of/freshness and authority-derived progress only. |
| Secret leakage through Idea/revision/event. | Security boundary violation. | validation/redaction tests, safe response and existing secret guards. |

## 28. Open Questions

1. Which actor/role grants Plan Approval in the first release, and how is `authorization_ref` issued/validated?
2. What exact Entry Master Plan schema is sufficient to compile a `GraphPatch` and `VerificationPlan` without over-specifying Worker/model/framework/database choices?
3. Is a bridge-level saga status adequate, or does product policy require an explicit human review when child command materialization is partially complete?
4. Should a Draft use normalized child tables from day one for retention/audit, or can typed immutable JSON revisions meet query and compliance needs initially?
5. What is the first concrete PostgreSQL `ProductReadModel` composition and its source-of-truth/query performance budget?
6. Which Project state mapping is user-facing `phase`, and when is `progress` available with an explainable basis rather than `null`?
7. Can P6’s future Software Request API be made the long-term wrapper around EntryDraft, or should the two remain separate until a later ADR proves convergence?
8. Does the first public release require collaborators/multi-user Draft editing? If yes, add explicit ownership/role/conflict policy before implementation; do not assume last-write-wins.

## 29. Final Recommendation

Proceed with Production Entry only as a **separate, minimal pre-approval intent layer**, then connect it to the validated P6 runtime through a single recoverable Approval Bridge. Implement the order E0 → E1 → E2 → E3 → E4 before any Factory Home polish; first prove that an approved plan creates one Project/Graph/Verification setup using existing semantic commands and then lets the untouched P6 runtime complete its authority chain. Afterwards wire real Product API read/command adapters, build Portfolio/Factory Home as projections, and integrate Live Production as a view of existing facts.

Do **not** implement a new Production aggregate, Scheduler, Task authority, Event Store, Worker manager, verification system, runtime state machine, raw state PATCH API or UI-to-SQL path. Do **not** make the Trial driver a public entry service. These prohibitions are not aesthetic preferences; they are the smallest set of constraints that preserves the authority chain P6 has already proven.

## References

[1]: [`docs/P6_REPORT.md`](P6_REPORT.md)
[2]: [`hermes-runtime/tests/test_p6_autonomous_trial.py`](../hermes-runtime/tests/test_p6_autonomous_trial.py) and [`hermes-runtime/src/hermes_runtime/trial/`](../hermes-runtime/src/hermes_runtime/trial/)
[3]: [`hermes-runtime/src/hermes_runtime/application/product_api.py`](../hermes-runtime/src/hermes_runtime/application/product_api.py), [`infrastructure/fastapi_app.py`](../hermes-runtime/src/hermes_runtime/infrastructure/fastapi_app.py), and [`api_main.py`](../hermes-runtime/src/hermes_runtime/api_main.py)
[4]: [`hermes-runtime/src/hermes_runtime/trial/driver.py`](../hermes-runtime/src/hermes_runtime/trial/driver.py)
[5]: [`hermes-runtime/migrations/0024_p6_autonomous_trial_runtime.sql`](../hermes-runtime/migrations/0024_p6_autonomous_trial_runtime.sql)
[6]: [`hermes-runtime/migrations/0003_project_state_authority.sql`](../hermes-runtime/migrations/0003_project_state_authority.sql) and [`application/handlers.py`](../hermes-runtime/src/hermes_runtime/application/handlers.py)
[7]: [`docs/P6_AUTONOMOUS_PRODUCTION_TRIAL_PLAN.md`](P6_AUTONOMOUS_PRODUCTION_TRIAL_PLAN.md)
