# Proteus Live Production UX & Interaction Design V1.0

**状态：** Design Baseline
**作者：** Manus AI
**日期：** 2026-08-17
**范围：** P6 Autonomous Production Trial 的产品、交互、领域与接口设计；**不包含实现代码**。
**架构基线：** 本文按审查时的 Proteus P0–P5 Control Plane 设计；工作树同时存在在途 P6 试验文件，本文不将其视为已验收能力。

> **核心命题：** Proteus 的 Web UI 不是“和一个 Agent 聊天的窗口”，而是人类查看、控制、修订并审计一条软件生产线的 **Live Production Workspace**。它默认自主，但人类在每一个关键时刻都能看见、暂停、干预、修改和重新规划。

![权威控制与实时投影流程](assets/authority_flow.png)

## 1. Executive Summary

Proteus 已经拥有自主软件工厂所需的 Control Plane 基础：Project/Task 权威状态、任务 DAG、命令幂等、预期版本、Outbox、调度租约与 fencing、Worker/Verifier 隔离、证据与产物、恢复循环、Human Gate、审计解释，以及 FastAPI 与单节点运行时边界。现有 P5 表面只提供少量语义查询和最小 Human Gate HTML 界面；它尚不是面向用户的生产工作台。当前最关键的产品缺口不是“再做一个聊天框”，而是把既有权威能力安全地投影为用户可理解、可操控、可恢复的 Production 体验。

本文将产品主对象定义为 **Production**：从 Idea 到 Delivery 的长寿命软件生产单元，其权威后端聚合仍是现有 `Project`。Production 以版本化的 **Master Plan** 组织工作，以 **Live Workflow Graph** 展示已批准计划与运行事实，以 **Node / Worker / Execution / Verification / Evidence** 的关系解释“现在在哪里、为什么这么做、谁在执行、证明是什么”。界面永远不是事实来源；所有写操作都必须转成带 actor、reason、idempotency key、expected version 与 correlation 的语义命令，并由 Control Plane 事务、Outbox 和权威投影闭环。

P6 的正确目标是一个“窄而真”的纵向切片：用户可提交 Idea、审阅并批准 Master Plan、观察一个真实的工作流、读取 Worker/验证/证据、通过受治理的暂停或局部变更进行干预，并在事件流断开后恢复到权威快照。任意图编辑、多租户协作、通用自然语言自动写状态、复杂图算法和多生产线调度应留给后续阶段。

## 2. Product Philosophy

Proteus 的默认行为是自主推进；它的安全承诺是人类始终保有可理解、可证据化、可撤销的控制权。这个承诺不是“每一步都弹窗”，也不是“用户永远只能旁观”。它要求系统将每个重大行动解释为 **目标—决策—授权—执行—验证—证据—交付** 的连续链路，并在风险、不可逆性、成本或计划不确定性升高时，将控制权清晰地交还给人。

> **Autonomous by default, Human-controllable at any moment.**
> 默认自主生产；人类可在任何时刻看见、暂停、干预、修改和重新规划。

| 原则 | 设计含义 | 禁止的反模式 |
| --- | --- | --- |
| 计划先于生产 | 任何真正执行前必须有已批准的 Plan Revision。 | 将聊天消息或模型草稿视为可执行计划。 |
| 权威先于动画 | 图上每个状态、进度、告警都来自服务端权威投影。 | 浏览器本地先改成“成功”，再异步补写。 |
| 解释先于控制 | 变更、暂停、跳过、重试必须先显示目标、影响、风险和后果。 | 单击“重试/跳过”后立即改变工作图。 |
| 证据先于完成 | Worker 的自述不是完成；完成由独立验证及 Evidence 支撑。 | 把日志文本或 Agent 声称当作 PASSED。 |
| 版本先于覆盖 | Plan、节点、依赖、影响分析和审批均可追溯。 | 原地覆盖计划、删除历史或只保留最新图。 |
| 恢复优于重做 | 先检查 checkpoint、lease、fencing、幂等与有效产物，再决定重试。 | 网络断开或 Worker 崩溃后盲目从头启动。 |

## 3. Product Positioning

Proteus 是一个 **Autonomous Software Factory**，而不是另一个 AI Chatbot。Chat 可以是 Command Bar 的语言入口，但它不是信息架构中心，也不是历史、状态和权限的承载体。用户来到 Proteus 首先回答的问题应当是“**你想生产什么软件？**”，而非“你想和谁聊天？”。

| 模型 | 主对象 | 用户心智 | 成功定义 |
| --- | --- | --- | --- |
| Chat Agent | 对话 / Task | 发出提示、等待结果 | 一次回复或单次任务完成。 |
| Manus Plan Mode | Task + 可审阅计划 | 在构建前对齐方法、确认后继续 | 已确认的任务计划得到执行。 |
| Proteus | Production + Master Plan + Live Workflow + Authority | 管理一条可观测、可变更、可审计的软件生产线 | 已验证的软件产物按计划交付，且全过程可控制、可恢复。 |

Production 不是 Task 的同义词。一个 Production 对应用户业务目标及其交付责任，通常跨越多个阶段、多个 Plan Revision、多个并行 Task、多个 Worker Run 和多次验证。Task 是 Production 在某个获批计划版本下的受控执行单元；它可以重试、被替代、被 supersede 或保留为可复用完成成果，但不会替代 Production 的整体语义。

## 4. Competitive Analysis

### Manus

Manus Plan Mode 的核心价值在于将计划审阅前置：系统做可行性检查，将目标、步骤和约束生成结构化 Markdown；用户可直接编辑或要求修订，确认后计划成为执行依据，确认前不开始构建。它还支持在任务中途开启 Plan Mode，由系统停止并为下一阶段生成待批准计划。[1] Manus 的公开 API 以异步 Task 生命周期和消息事件组织进度，公开状态为 `running`、`stopped`、`waiting`、`error`；`waiting` 事件可带特定确认输入 schema。[2] 其详细消息模式还会发布 plan snapshot 与新增步骤事件。[3]

Proteus 应借鉴这三点：**明确的执行前批准、可编辑的结构化计划、执行中转入重新规划的能力**。但 Proteus 不能复制其 Task/消息中心抽象。公开 Task 消息流适合追踪单一 Agent 任务；软件工厂需要树与 DAG、节点依赖、租约、fencing、独立验证、证据失效、Worker 重新分配、计划版本差异和对账。因此，Proteus 将借鉴交互的可理解性，却以 Control Plane 的 Production/Plan/Workflow/Authority 模型形成差异。

### Hermes

Hermes 是当前仓库中形成 P0–P5 Control Plane 的运行时与架构名称，不应被误定位成面向终端用户的竞争产品。其优势是强权威边界：Worker 不能自行将 Task 标为通过；验证与 Worker 隔离；命令采用幂等与 expected version；执行依赖租约和 fencing；Human Gate 具有等待与恢复上下文；事件、解释、证据和恢复在持久化层可追踪。它的局限恰好定义了 P6 UX 工作：现有产品 API 仅暴露项目状态、决策解释、Human Gate、对账发现和 Docker 观察等有限端点，且没有 Live Workflow、Plan Review 或事件订阅表面。

### Proteus 的差异化

| 维度 | Manus | Hermes Runtime | Proteus Live Production Workspace |
| --- | --- | --- | --- |
| 中心对象 | Task 与消息 | 权威聚合与运行时协议 | Production 与 Master Plan。 |
| 计划 | 可编辑并确认的任务计划 | Planner/decision 事实，但无面向用户的主计划工作台 | 可审阅、可版本化、可 diff、可影响分析的 Master Plan。 |
| 运行可见性 | 任务进度/消息/计划步骤 | 内部事件、租约、验证和审计事实 | 面向人类的 Live Workflow Graph，连接 Node、Worker、Execution、Evidence。 |
| 变更 | 任务中可再次进入 Plan Mode | 恢复/规划等控制能力 | L1/L2/L3 Plan Mutation，带冻结、影响、审批、对账与复用判定。 |
| 人机协作 | 任务确认 | Human Gate 运行时权威 | 统一的 Intervention 与 Gate UX，不绕过 Authority。 |
| 权威来源 | 对外 API 任务事件 | PostgreSQL Control Plane | Control Plane Snapshot + Event Stream；UI 永不成为真相源。 |

## 5. UX Principles

第一，任何页面必须让用户在五秒内回答：**Production 当前在哪里？下一步是什么？谁在做？为什么？如果我现在介入，会影响什么？** 第二，用户可随时看见和请求干预，但真正的执行控制必须遵守已有 lease、checkpoint、fencing、状态持久化和 recovery 协议。第三，已完成且未受影响的结果应优先复用；重新规划是显式、局部、证据驱动的重算，而不是对历史的覆盖。第四，风险必须用清晰语言表达，但颜色、图标和动画不能成为唯一信号。

## 6. Surface Architecture

| Surface | 定位 | 首要用户 | 核心能力 | 明确不做 |
| --- | --- | --- | --- | --- |
| **Web GUI** | Factory Workspace | 产品负责人、开发者、审批者 | Idea Entry、Plan Review、Live Workflow、Inspector、Evidence、Gate、Command Bar | 浏览器端调度、直接数据库写入、无预览的自然语言副作用。 |
| **TUI** | Factory Control Console | Operator、开发者、SSH/CI 值守 | 概览、事件尾随、告警、inspect、受限 pause/resume/stop、脚本化查询 | 复制完整图形画布、富文本计划编辑。 |
| **API** | Automation Interface | CI/CD、外部系统、未来客户端 | 版本化快照、语义命令、审计查询、事件订阅、确认回调 | 通用 PATCH、任意 SQL、任意状态写入。 |

Web、TUI 和 API 共享同一个 Production Contract，但不共享实现职责。Web 对复杂结构和证据做视觉解释；TUI 用高密度、低带宽、可组合输出辅助运维；API 将所有可变操作限定为命名的语义命令，延续 P4/P5 禁止通用状态变更的边界。

## 7. Information Architecture

Web 的全局导航为 **Factory Home / Productions / Gates / Workforce / Evidence & Audit / Settings**。进入某个 Production 后，工作空间使用固定三栏和底部 Command Bar：左栏是 Production Structure；中栏是 Live Workflow Graph；右栏是 Inspector；底部是自然语言命令与结构化操作入口。小屏幕下三栏改为可切换面板，但 Command Bar 始终可访问。

| 区域 | 内容 | 默认问题 |
| --- | --- | --- |
| Factory Home | Idea Entry、Recent、Running、Waiting Gates、Completed、Failed、Factory/Workforce 状态 | “我想生产什么？” |
| Production Structure | Master Plan Revision、阶段树、节点摘要、Gate、Worker 汇总 | “结构是什么？” |
| Live Workflow Graph | 节点、DAG 依赖、实时执行、阻塞、风险与进度 | “生产现在流向哪里？” |
| Inspector | 节点/Production/Worker 的状态、事件、决策、证据、产物和控制 | “为什么是这个状态？我能做什么？” |
| Command Bar | 文本意图、候选命令、影响预览、确认状态、结果链接 | “我希望系统如何改变？” |

## 8. User Journey

用户由 Idea 开始，系统先创建 `Production Draft`，再澄清需求并产生 `Master Plan Revision 1`。在未批准时，只能做计划生成、编辑、模拟和风险分析，绝不能 materialize 为真正可执行任务。用户批准后，系统将获批计划映射至既有 Project/Task/Graph 结构，创建权威生产快照，并允许 Scheduler 只对 READY 节点发起执行。

执行中，用户可从图中看到当前阶段、运行节点、Worker、验证和依赖阻塞。用户提出变更时，系统不直接改代码或修改任务，而是创建 `PlanChangeRequest`，生成 Impact Analysis 与 Revision Diff，要求适用的批准或 Gate，随后由 Scheduler Reconciliation 落地。交付时，Production Inspector 汇总验证、Evidence、Artifact、风险和剩余开放项；只有既有 Control Plane 的 Project 交付条件达成，UI 才显示可交付。

## 9. Factory Home

Factory Home 的首屏应是一块大型 Idea Entry，而不是会话历史。输入框上方使用问题“**What do you want to build?**”，下方给出范围、约束和已有仓库/附件的可选补充。主按钮为 **Start Planning**；在产生并批准 Master Plan 前，页面不得显示“开始执行”的承诺。

首页的生产清单以状态分区呈现：Running、Waiting Gates、Needs Attention、Recent Drafts、Completed 和 Failed。每张卡片至少显示 Production 名称、当前 Phase、当前 Node、已完成/总节点、最近事件、等待原因、风险级别和最后权威更新时间。Factory Status 显示 Control Plane 健康、事件流延迟、队列积压和可用 Worker 容量；Workforce Status 显示可用能力、繁忙 Worker、失效/隔离 Worker 与待分配工作。任何健康数据缺失必须显示 `Unknown`，不得假定为绿色。

## 10. Idea Entry

Idea Entry 需要把自然语言目标转换为生产约束，而不是把用户逼成 Prompt 工程师。最低字段是 Idea、目标用户、成功标准、约束/不可做事项、已有资产与交付偏好。系统可提出澄清问题，但每一个补全建议都应标识为“建议假设”，并进入可编辑 Plan Draft。

`Start Planning` 的结果是 `ProductionDraftCreated` 与一个可追踪的 Intake 记录。若输入含高风险操作、外部凭证或合规要求，系统只记录需求与风险，不收集或回显秘密；需要具体 secret 时由既有受治理的 secret/Human Gate 流程处理。

## 11. Plan Review

Plan Review 是真正生产前的硬门。页面将计划分为 Goal、Requirements、Constraints、Architecture、Production Phases、Plan Nodes、Dependencies、Risks、Verification Strategy、Delivery Strategy、Workforce Requirements 与 Assumptions。左侧是章节目录，中间是可编辑文档与节点结构，右侧显示风险、缺失信息、计划检查和版本历史。

用户可以直接编辑文本，也可以执行受控结构操作：Add/Remove Requirement、Split/Merge Node、Change Dependency、Ask Proteus to revise、Rebuild Plan、Approve 和 Reject。文本编辑只改 Plan Draft；结构编辑产生操作日志，并即时进行 DAG 校验、最大深度/最小粒度检查、风险重算和依赖解释。用户批准时，系统展示不可变的 `PlanApprovalPreview`：版本号、内容 hash、计划差异、将 materialize 的节点、预计 Workforce、风险与验证策略。批准命令包含 expected plan version；冲突时必须重新加载，不可静默覆盖。

## 12. Master Plan

Master Plan 是 **用户可读的意图与约束模型**，不是 Scheduler 的私有队列。每个 Revision 有不可变快照、父版本、作者、创建原因、审批/拒绝记录、影响分析、兼容性结论和关联 Evidence。其 Plan Node 是层级表达，Plan Edge 是依赖表达；两者共同构成 Tree + DAG。一个 Plan Node 可以在批准后映射为一个或多个 Task，也可在局部重规划时被替换为新的子图。旧 Node 永不被“改没”，而是标记 `SUPERSEDED` 或保留为已完成复用候选。

| 字段 | 说明 | 设计约束 |
| --- | --- | --- |
| `revision_id` / `revision_number` | 计划版本身份 | 单调递增，不能重用。 |
| `base_revision_id` | 变更基线 | 用于 diff、并发检测和回滚到“新 revision”。 |
| `goal_snapshot` | 用户目标与成功标准 | 变更时触发 L3 判定。 |
| `nodes` / `edges` | 层级与依赖 | 必须经过 DAG/循环检查；Tree 仅表示归属。 |
| `verification_strategy` | 验证层级与通过条件 | 映射到既有 Verification Plan，而不替代它。 |
| `approval` | 审批者、时间、hash、决策理由 | 计划获批才可解锁生产。 |
| `materialization_map` | Plan Node 至 Task/Execution 的关系 | 防止 UI 假设一对一映射。 |

## 13. Live Production

Live Production 是最核心的页面。顶部展示 Production 状态、当前 Phase、总进度、最后权威更新时间、事件流连接状态、当前 Plan Revision、风险摘要与全局控制。左栏展开计划阶段与节点；中栏展示 Graph；右栏展示所选实体 Inspector；底部提供 Command Bar。用户进入时先拉取权威 Snapshot，再以该 Snapshot 的 watermark/cursor 订阅事件。只有当 Snapshot 与 Event Stream 均健康时，页面才显示“Live”。

页面不将百分比伪装成精确事实。进度由已完成节点权重、阶段完成、执行 attempt 和验证状态组成，并标明来源；无法计算时显示“进度待估”。Running Node 的动画只是视觉提示，实际状态以权威投影为准。Blocked/Waiting Human/Failure 必须在图、结构树和顶部摘要同时可见，并给出一句可行动解释。

## 14. Live Workflow Graph

Workflow Graph 是获批 Master Plan 的结构与运行时事实的组合投影。它支持 Tree + DAG：父子边表达分解/归属，依赖边表达“必须先满足”的执行条件。节点以状态、风险、Worker、验证结果、证据状态和时间表现；边以满足、等待、失效、冲突或阻塞表现。默认视图按 Phase 分组，可在 `Plan`、`Execution`、`Evidence`、`Risk` 四个图层间切换。

| 图元素 | 定义 | 交互 |
| --- | --- | --- |
| Node | Plan Node 映射的工作单元或运行时 Task 投影 | 点击打开 Inspector；多选查看影响范围。 |
| Parent/Child Edge | 计划分解关系 | 可在草稿 revision 中编辑；运行中需走 Mutation。 |
| Dependency Edge | DAG 前置关系 | 显示“等待谁/为什么”；变更需做循环与影响检查。 |
| Milestone | 阶段/交付目标 | 聚合进度、Gate 与验收条件。 |
| Worker Binding | 某 execution attempt 的分配关系 | 显示 Worker、capability、lease 状态；不是永久指派。 |
| Evidence Link | 结果与证据/产物关系 | 打开 Evidence drawer；失效会回流图状态。 |

用户可 Pause、Resume、Stop、Inspect、Modify、Decompose、Replan、Retry、View Evidence 与 Reassign Worker，但不同操作根据实体状态、角色、风险和现有 lease 决定是否可用。`Skip` 不应作为普通快捷操作：只允许具备明确 policy 的非关键节点，并必须展示被跳过的验证/依赖后果、理由、审计和可能的 Gate；默认 P6 不开放 Skip 的实际执行。

## 15. Node Inspector

Node Inspector 有 Overview、Execution、Events、Decisions、Evidence、Artifacts、Verification、Errors 与 Controls 标签。Overview 显示 Node ID、标题、描述、父级、子级、依赖、当前状态、风险、Plan Revision、最近状态变化和当前行动。Execution 显示 Worker、Runtime、Execution Request、Lease/fencing 的用户友好摘要、进度、已完成/剩余行动及 retry 次数；原始 token 或安全细节不直接暴露。

Controls 不直接写状态。用户点 Pause/Stop/Retry/Modify/Decompose/Replan/Reassign 后，Inspector 先打开预览抽屉，解释目标节点、当前执行、影响范围、权限、是否需要 checkpoint 或 Gate、以及将提交的语义命令。命令接受后，控件变为 `REQUESTED`/`COORDINATING`，直到权威事件确认完成或拒绝。

## 16. Production Inspector

当未选中 Node 时，右栏显示 Production Inspector：Goal、当前 Plan Revision、阶段进度、全局风险、关键决策、等待 Gate、活跃 Worker、最近失败、交付准备度与计划版本历史。它还提供生产级 Pause/Resume/Stop 和 Master Plan Rebuild 入口。Production 停止显示为一个受协调流程：先说明“停止请求已接受”，再显示 Worker cancellation、checkpoint、lease release、资源结算、对账和最终 Project 状态；只有最终权威状态为 `CANCELLED` 才显示“已停止”。

## 17. Workforce View

Workforce View 以能力和执行尝试为中心，而非将 Worker 人格化。它显示 Worker Template/能力、状态、可用容量、当前绑定节点、最近心跳、隔离/失败原因、运行时、允许的环境与最近执行结果。用户的 Reassign Worker 不是“指定任意 Agent 继续写”，而是新建受策略和能力匹配约束的 WorkerAssignment 候选；原运行必须先通过 checkpoint/lease/fencing 结束或超时对账。P6 可先提供只读 Workforce 汇总与受限 reassign preview；真正复杂的人工能力调度留到后续阶段。

## 18. Real-time Event Model

P0–P5 已有 Event/Outbox/Relay 语义。P6 不应创建第二个事件事实来源，而应定义面向 UI 的 **Production Projection Stream**：它从权威事件和查询投影导出稳定 schema，附带 `event_id`、`production_id`、`aggregate_type`、`aggregate_id`、`aggregate_version`、`production_sequence`、`occurred_at`、`correlation_id`、`causation_id`、`schema_version` 与 `snapshot_watermark`。

建议 UI 事件类别如下；若底层命名不同，适配器必须保存底层原始事件和映射版本。

| UI 事件类别 | 典型事件 | UI 作用 |
| --- | --- | --- |
| Production | `production.created/started/paused/resumed/cancellation_requested/cancelled/completed` | 更新顶栏、列表与全局控制。 |
| Plan | `plan.created/revised/approved/rejected/rebuild_proposed` | 更新版本、diff、审批状态。 |
| Node | `node.materialized/ready/queued/started/progress/blocked/paused/completed/failed/superseded` | 更新图和 Inspector。 |
| Worker/Execution | `worker.assigned/started/lost/reassigned`、`execution.lease_changed/checkpointed/cancelled` | 解释运行归属和恢复。 |
| Verification | `verification.started/passed/failed/invalidated` | 更新完成可信度和重跑需求。 |
| Gate | `human_gate.created/answered/applied/expired/cancelled` | 更新等待状态和审批收件箱。 |
| Artifact/Evidence | `artifact.created`、`evidence.recorded/invalidated` | 打开可审计产物链。 |
| Intervention | `intervention.requested/accepted/rejected/coordinating/applied/failed` | 驱动控制按钮的过渡 UI。 |

客户端一致性规则如下：首先获取 Snapshot；其次从 watermark 订阅流；按 production sequence 与 aggregate version 去重、排序；发现缺口、未知关键 schema、版本跳跃、401 或连接重建时，显示 `Reconnecting`/`State may be stale`，冻结高风险写控件，拉取新 Snapshot 后再续订。重复事件是幂等 no-op；乱序事件不能回退较新实体版本；事件流不能替代最终查询确认。

## 19. Human Intervention

Human Intervention 是用户意图到 Control Plane 受控变更的统一模型。每次 Intervention 有 `intervention_id`、target、action、actor、reason、expected version、risk assessment、policy decision、required gate、checkpoint policy、cancellation deadline、status、command/event refs 与审计结果。它将“停一下后端”这类语言转化为可预览、可确认、可跟踪的对象，而不是杀掉一个进程。

| 生命周期 | 用户看见什么 | 系统行为 |
| --- | --- | --- |
| Draft/Preview | 目标、影响、风险、可选范围 | 解析 intent、权限检查、读取权威版本。 |
| Submitted | “请求已提交，等待 Control Plane 接受” | 提交幂等语义命令。 |
| Coordinating | checkpoint、取消、租约释放的实时进度 | 控制 Worker cancellation，保存 checkpoint，避免 fencing 失效写入。 |
| Waiting Human | Gate 卡片、证据和审批动作 | 进入既有 Human Gate / resume context 流。 |
| Applied | 新状态、关联 Revision/Task、审计链接 | 提交权威状态/对账结果，发布事件。 |
| Rejected/Failed | 原因、当前状态、可重试/查看证据 | 保持事实不变，提供解释与安全下一步。 |

## 20. Pause / Resume / Stop

**Pause** 保留继续所需的恢复上下文；**Stop** 是有意终止并可能取消节点或整个 Production；**Resume** 不是前端“继续跑”，而是在权威 Guard、Policy、Budget、Gate 和 resume context 均仍有效时重新允许调度。现有 Project 状态机已具备 `PAUSED` 与 `WAITING_FOR_HUMAN` 语义，P6 应适配而非重造。

对于运行节点，Pause 的正确序列是：Intervention Request → Authority/Policy Check → cancellation signal → graceful checkpoint → persist state → release/expire execution lease under fencing → settle/reconcile resources → authoritative Project/Task projection update → UI event。若 Worker 无法停止，UI 显示 cancellation timeout 与“执行状态不确定”；不能把它显示成已暂停，也不能立即分配第二个 Worker。Stop 同理，但产生 `CANCELLED` 意图、明确哪些 Artifact/Evidence 仍保留、哪些外部副作用需要核查。Resume 必须重新评估 resume context、当前 Plan Revision、证据有效性和资源，不得盲目复用过期 Worker token。

## 21. Plan Mutation

![计划变更、对账与恢复流程](assets/plan_mutation_flow.png)

用户说“把 PostgreSQL 换成 MySQL”时，Proteus 必须创建 `PlanChangeRequest`，而不是让 Agent 直接改代码。系统先将自然语言归类为修改、分解、局部重规划或 Master Plan 重建，展示候选目标与歧义；随后在现有 Plan Revision 上计算 Impact Analysis，列出受影响/未受影响节点、已完成成果可否保留、Artifact/Evidence 是否失效、验证重跑、预计新增工作、风险与建议 Gate。用户批准后才创建 `Plan Revision #N`，Scheduler 执行受影响图的 reconciliation，并在安全边界后恢复。

每一次修改都记录提议者、原因、基线版本、diff、影响分析版本、policy/risk/gate 结论、审批、应用结果和关联 Evidence。所谓“回滚”不是删除新版本，而是以旧 snapshot 为基线产生新的 Forward Revision，并再次进行兼容性、验证与审批。

## 22. Impact Analysis

Impact Analysis 是变更确认页的核心，而不是一句“可能影响后端”。它展示图形化的 dependency cone，并提供结构化表格。

| 分区 | 必答问题 | 示例：PostgreSQL → MySQL |
| --- | --- | --- |
| Affected | 哪些节点、依赖、产物、验证必须改变？ | Database、Repository、Backend、Integration Tests。 |
| Unaffected | 哪些成果在当前约束下仍兼容？ | Frontend、Authentication UI，前提是不依赖数据库语法。 |
| Completed | 已完成项是否保留、失效还是需要再验证？ | 已通过的 API 文档可保留；DB migration Evidence 失效。 |
| In-flight | 哪些运行必须 checkpoint、取消或等待？ | 当前 Backend Worker 进入协调暂停。 |
| Cost/Risk | 新增节点、预计工作、不可逆操作、Gate？ | 新 schema/migration 风险，可能要求 Gate。 |
| Decision | 推荐 L1/L2/L3 与批准范围 | L2 Local Replan，替换数据层依赖锥。 |

Impact Analysis 的计算结果也需要版本和 hash；若批准前 Plan、Node、Artifact 或 Policy 已变化，则预览作废，用户必须刷新分析。P6 可实现基于 Plan Edge、Task DAG、Artifact/Evidence 引用的确定性第一版影响锥，不应声称已实现完美的语义代码影响分析。

## 23. Plan Decomposition

任何 Plan Node 可被分解为子节点，例如 Backend → API Design、Authentication、User Service、Todo Service、Repository、Error Handling、Tests。分解发生在 Plan 域，运行时 Task 则在获批后 materialize。系统应支持用户主动分解、系统建议分解与受策略限制的自动分解；每次均检查最大深度、最小可执行粒度、依赖完整性、估计收益与并行安全性。

运行中的 Node 分解必须先进入 mutation 协调。系统暂停或 checkpoint 当前 execution，读取已产生的 Artifact/Evidence 和执行进度，创建子图，更新依赖与 materialization map，再由 Scheduler 为可运行子节点分配 Worker。原 Node 记录为 `SUPERSEDED` 或“partial checkpoint source”，而不是从历史中消失。P6 应支持用户发起的单层、同阶段分解；递归自动分解和自动合并留到 P7。

## 24. Local Replan

Local Replan 用于影响某个节点及其下游依赖锥的改变，例如将 OAuth2 JWT 改为 Session。界面必须显示局部边界，而不是误导用户“只改认证”。批准后系统建立局部调度屏障，先让边界内的运行项到达 checkpoint 或安全取消点；新 Revision 只替换该子图与跨边界依赖，受影响验证失效并重建，边界外完成且兼容的节点作为输入保留。重新开始时，Scheduler 依据新子图、能力和锁范围重新选择 Worker。

## 25. Master Plan Rebuild

Master Plan Rebuild 适用于 Goal、核心产品类型或架构方向改变，例如“不要 Notion，改成 Linear 风格的项目管理系统”。它先 Freeze Current Plan 的新调度，不抹除历史；随后重新分析 Goal，生成新的 Master Plan，输出 Old vs New diff、可迁移成果、必须舍弃的成果、风险、估算与迁移/重建策略。此操作始终要求明确用户批准；高成本、破坏性或外部副作用还需 Human Gate。批准后旧计划保持可审计，新的 Revision 通过 reconciliation 创建新的工作图。

## 26. Human Gate

Human Gate 是 Control Plane 权威能力的产品表达，适用于用户批准不能替代的高风险事实。Gate 卡片必须显示风险等级、原因、行动摘要、目标范围、影响、Evidence 数量、提出者、过期时间、拒绝后果与审批者权限。按钮为 Reject / Approve；每个按钮先显示将提交的 decision，不直接恢复生产。

| Gate 类别 | P6 默认策略 |
| --- | --- |
| 不可逆或破坏性外部副作用，例如删除生产数据库 | 必须 Gate。 |
| 涉及部署、凭证、secret、外部账户或费用承诺 | 按既有 policy/risk 动态 Gate；默认保守。 |
| Master Plan Rebuild、重大架构替换 | 必须用户批准；依风险可追加 Gate。 |
| 低风险、可重试、隔离 sandbox 内操作 | 可自主执行，但仍保留审计。 |
| 仅查看状态、Evidence、Artifact | 不需 Gate，但遵守访问控制。 |

Gate 生命周期必须覆盖 Created、Waiting、Approved/Rejected、Applied、Expired、Cancelled。Gate 过期不等于拒绝或执行；它将 Production 保持在等待/阻塞的权威状态，等待重新发起或恢复策略。P6 沿用既有 request → enter waiting → submit decision → apply decision → guarded resume 的边界。

## 27. Command Bar

Command Bar 位于 Production 工作空间底部，是自然语言的 **Intent Layer**，不是绕过 Authority 的命令行。它支持“暂停后端”“为什么数据库节点卡住了”“把 PostgreSQL 换成 MySQL”“把这个节点拆成三个任务”“重新规划认证模块”“继续生产”“停止所有 Workers”等表达。

| 阶段 | UI 责任 | Control Plane 责任 |
| --- | --- | --- |
| Intent Classification | 显示识别出的 action、target 和置信度；歧义时要求用户选择。 | 不授予权限。 |
| Preview | 展示影响、风险、当前版本、建议操作和取消路径。 | 读取权威状态，生成/验证预览。 |
| Confirmation | 对可变或高风险意图要求显式确认/Gate。 | 绑定 actor、reason、expected version、idempotency。 |
| Execution | 显示请求状态而非乐观成功。 | 应用语义命令、事件、调度/Worker 协调。 |
| Result | 链接到 Node、Revision、Gate、Evidence、Error Explain。 | 返回命令回执和相关 refs。 |

P6 的 Command Bar 只覆盖少量 allowlisted intent：inspect/explain、pause/resume/stop、retry preview、request node modification、request decomposition、request local replan、request master rebuild。任何未知或高歧义句子都转为 Draft Change Request，不得自动调用执行器。

## 28. Evidence & Decision Chain

Evidence 页面必须让用户从一个状态结论回溯到原因。每个“通过”“失败”“暂停”“重新规划”“Gate 应用”都链接到 Decision、Evidence、Artifact、Verification Result、Execution Run、Worker/Verifier identity、时间、关联 ID 和失效关系。展示层默认脱敏：secret 值、token、原始凭证和不必要的租约 token 不可出现在 UI、事件详情、搜索索引或下载包。

对于 Evidence Invalidated，UI 不能继续显示绿色通过。应显示“原验证因 artifact hash/依赖变更失效”，标记影响节点，提供 re-verification 的预览入口。对于缺失 Evidence，显示 `MISSING`，而不是合成“无问题”。

## 29. Failure UX

| 异常 | 用户看见什么 | 系统处理 | Gate |
| --- | --- | --- | --- |
| Worker crash | 节点标记 `Execution uncertain`，显示最后心跳和 lease 到期时间。 | 等待/检测 lease 过期，fencing 旧写入，reconcile 后重试或分配替代 Worker。 | 通常不需；高风险恢复策略按 policy。 |
| Network disconnect | 顶部 `Reconnecting — commands limited`，保留最后权威时间。 | 不改变权威状态；重连后 Snapshot rehydrate。 | 否。 |
| Event stream disconnect | 图层显示陈旧，不接受高风险控制。 | 从 cursor 恢复；若有 gap 则全量快照。 | 否。 |
| Duplicate/out-of-order event | 用户通常无感；诊断可见计数。 | 按 event ID/sequence/aggregate version 去重排序。 | 否。 |
| Task timeout | 显示超时、执行上下文、建议恢复。 | 取消/检查点/lease/reconcile，创建反馈而非伪装为业务失败。 | 视策略。 |
| Verification failure | 节点红色，验证检查、Evidence 和失败原因可见。 | 进入 Feedback → Situation → Diagnosis → Planner 的既有恢复链。 | 修复可自主；重大策略切换可需 Gate。 |
| Plan conflict | “计划在你查看后已变化”，展示 diff。 | 拒绝旧 expected version；不覆盖。 | 否。 |
| 用户变更计划时 Worker 运行 | 显示协调屏障和受影响执行。 | checkpoint/cancel/reconcile，之后才替换图。 | 依据风险与范围。 |
| Worker cannot stop | `Cancellation timeout / execution uncertain`。 | 不重复分配、等待 fencing/人工检查、记录审计。 | 可能需要。 |
| Proteus restart | `Recovering`，显示恢复阶段。 | checkpoint/replay/reconcile；replay 不直接覆盖权威状态。 | 异常/破坏性修复依策略。 |

## 30. Recovery UX

Recovery 页面是 Production Inspector 的状态化子页面。它用时间线展示“发生了什么、系统已验证什么、尚不确定什么、下一步是谁决定”。当 Control Plane 重启后，用户看到 `Recovering`，包括 checkpoint cursor、已重放的事件范围、当前 lease/reconciliation 结果、隔离的迟到结果与建议处理。恢复完成前，不把 Production 显示为正常 Running；如果未能确定外部执行实际是否发生，必须明确标为 Unknown，并提供 Human Gate/Operator 路径。

## 31. State Machine

P6 使用 **双层适配**，不新建第二套 Task/Project 权威状态机。Plan 域有独立版本状态；运行域将现有 ProjectState/TaskState 映射为体验状态；Intervention 域描述 Pause/Stop 等过渡。

| UX 层 | 状态 | 权威映射或来源 |
| --- | --- | --- |
| Plan Revision | `DRAFT`、`IN_REVIEW`、`APPROVED`、`REJECTED`、`SUPERSEDED`、`ARCHIVED` | **[P6 REQUIRED]** 新 Plan 域；APPROVED 才可 materialize。 |
| Production 显示 | `DRAFT`、`PLANNING`、`READY`、`RUNNING`、`PAUSED`、`WAITING_HUMAN`、`BLOCKED`、`RECOVERING`、`FAILED`、`COMPLETED`、`CANCELLED` | 适配 `ProjectState`，不覆盖它。 |
| Node 显示 | `DRAFT`、`PLANNED`、`READY`、`QUEUED`、`RUNNING`、`VERIFYING`、`COMPLETED`、`FAILED`、`RETRYING`、`BLOCKED`、`CANCELLED`、`SUPERSEDED` | `DRAFT/PLANNED` 来自 Plan；其余适配 TaskState/Execution/Verification。 |
| Intervention | `PREVIEW`、`SUBMITTED`、`ACCEPTED`、`COORDINATING`、`WAITING_HUMAN`、`APPLIED`、`REJECTED`、`FAILED`、`EXPIRED` | **[P6 REQUIRED]** 新的请求/投影域；不能假装是 Task 状态。 |

`PAUSING` 与 `STOPPING` 仅作为 Intervention 的协调状态，而不是向 TaskState 直接插入两个未经审计的状态。用户会看到过渡，但底层 Task/Project 仍遵循 P0–P5 既有合法迁移。`COMPLETED` 在 UX 上代表 Task `PASSED` 且相关验证有效；Worker 完成 execution 不足以显示已完成。

## 32. Domain Model

| 实体 | 责任 | 生命周期与版本 |
| --- | --- | --- |
| `Production` | 用户级生产单元，绑定既有 `project_id` | 读模型/别名；权威状态来自 Project。 |
| `ProductionPlan` | Production 的计划根与当前已批准 revision 指针 | **[P6 REQUIRED]**，不可覆盖历史。 |
| `PlanRevision` | Master Plan 不可变快照、diff、approval、impact refs | 单调 version；通过新 revision 前进。 |
| `PlanNode` / `PlanEdge` | 层级、依赖、节点约束与 Task materialization map | 归属于 revision；边有类型与条件。 |
| `PlanChangeRequest` | 用户/系统提出的变更意图 | 草稿→分析→待批→应用/拒绝/过期。 |
| `ImpactAnalysis` | 受影响锥、复用/失效、风险和估算 | 与 plan/graph/artifact 版本绑定。 |
| `Intervention` | 暂停、停止、重试、重新分配等受控请求 | 独立过渡状态与审计。 |
| `WorkerAssignment` | 特定 Task/Execution attempt 的候选/有效绑定 | 复用既有执行分配与 lease 事实。 |
| `Execution` | 真实运行尝试、租约、检查点、result | 复用既有 ExecutionRequest/lease/run。 |
| `Decision` / `Evidence` / `Artifact` / `HumanGate` | Why/Proof/Output/Approval | 直接复用既有权威域；新增只读关联投影。 |

ER 关系为：`Production 1—1 Project`，`Production 1—N ProductionPlan Revision`，`PlanRevision 1—N PlanNode/PlanEdge`，`PlanNode 0—N Task`，`Task 0—N Execution`，`Execution 0—N Evidence/Artifact`，`Task 0—N VerificationResult`，`PlanChangeRequest 1—1 ImpactAnalysis`，`Intervention/Gate/Decision` 通过 immutable refs 关联至 Production、Plan Revision、Node 或 Execution。所有 UI 可写实体都必须拥有 `version`、actor、reason、时间、correlation/causation 和不可变审计轨迹。

## 33. Event Model

生产 UI 使用事件来刷新投影，不使用事件直接作为唯一读取源。每个事件至少包含：identity、schema version、生产/聚合 ID、聚合版本、全局 sequence、发生时间、actor、correlation/causation、最小安全 payload 与链接 refs。客户端对未知的非关键字段容忍；对未知关键 enum/state 或 schema version 进入 sync/error，不做猜测性渲染。

Plan、Impact、Intervention 事件应是 **[P6 REQUIRED]** 的新事件族，但必须经现有 Command/Event Protocol、Outbox、幂等、expected version、DLQ/replay 约束。底层既有 `project.*`、`task.*`、`verification.*`、`feedback.*`、Human Gate 与执行事件经 Projection Adapter 映射到稳定 UI taxonomy；适配映射不得修改原始事件含义。

## 34. API Contract Proposal

REST 负责版本化 Snapshot、可缓存查询与语义命令；SSE 负责浏览器友好的单向实时投影；WebSocket 仅在 P7 需要双向协作光标、图编辑会话或高频客户端交互时引入。P6 优先 SSE，降低连接状态和代理复杂度。

| 方法与路径 | 语义 | 结果 |
| --- | --- | --- |
| `POST /productions` | 提交 Idea，创建 Production Draft | 202 + `production_id`、draft revision。 |
| `GET /productions` | 筛选生产列表/状态 | Factory Home 投影。 |
| `GET /productions/{id}/snapshot` | 权威工作空间快照 | 含 revision、graph、inspector summaries、watermark。 |
| `GET /productions/{id}/plans/{revision}` | 读取不可变计划版本 | 计划文档、nodes、edges、approval/diff。 |
| `POST /productions/{id}/plan-change-requests` | 创建变更请求 | 202 + request/analysis job refs。 |
| `GET /plan-change-requests/{id}/impact-analysis` | 读取影响分析 | 版本、有效期、affected/unaffected/invalidated。 |
| `POST /plans/{revision}/approve` | 批准计划 | 语义命令回执；不直接写 Task。 |
| `POST /interventions` | Pause/Resume/Stop/Retry/Reassign 请求 | 202 + intervention status。 |
| `POST /human-gates/{id}/decisions` | 沿用既有 Gate 决策表面 | 202；由 Control Plane 应用。 |
| `GET /nodes/{id}/inspect` | Node 深度查询 | events、decisions、evidence、artifacts、verification。 |
| `GET /productions/{id}/events` | SSE 投影流 | snapshot cursor 后的事件。 |

所有 POST 命令至少包含 `command_id`、`idempotency_key`、`expected_version`、`actor`、`reason` 和 correlation context。所有拒绝都返回机器可读 rejection code、当前版本、可安全展示的解释与可刷新链接。禁止 `PATCH /state`、`PUT` 泛化更新、任意 event 注入、通用 SQL 或前端选择目标状态，这与现有 Product API 的防护保持一致。

## 35. WebSocket / SSE Contract

SSE 握手示例为 `GET /productions/{id}/events?after=<snapshot_watermark>`。服务端先验证权限，再发送 `snapshot_hint`、增量 projection events 与 keepalive；事件 ID 用于网络重试，`production_sequence` 用于逻辑顺序。若 `after` 已过期、schema 不兼容或服务端无法保证连续性，返回 `reset_required`，客户端必须重新请求 Snapshot。SSE 不承载用户写命令；命令通过 REST 语义端点提交，从而保留审计、幂等和 HTTP 结果语义。

WebSocket 被明确推迟。只有 P7 需要多人同步编辑、图形选区协作、长时间双向流控或终端代理时，才提出单独 ADR 来定义授权、背压、重连、消息确认和审计边界。

## 36. TUI Design

`proteus tui` 是 Factory Control Console。默认布局为顶部 Production/Control Plane 健康摘要，左侧运行/等待/失败生产表，中部事件 tail 与活跃执行表，右侧选中实体详情，底部显示键盘操作和过滤条件。核心命令为 `productions list`、`production inspect`、`events tail`、`gates list`、`gate inspect`、`intervention request pause|resume|stop`、`evidence show` 和 `doctor`。所有可变 TUI 命令与 API 一样生成 preview/confirmation/semantic command，不允许特殊后门。

TUI 不复制 Web 图画布。它用文字表达 DAG 位置、阻塞链、lease/heartbeat 和恢复状态，支持 SSH、CI/CD 和低带宽环境。富文本 Plan 编辑、复杂 dependency 拖拽和长 Evidence 浏览仍属于 Web。

## 37. Authority Integration

| 问题 | 设计回答 |
| --- | --- |
| UI 如何读取 Authority State？ | 从版本化 Snapshot/查询投影读取 Project、Task、Plan、Execution、Gate、Evidence；事件只刷新。 |
| UI 如何读取 Event？ | SSE 订阅 Projection Stream；保留 cursor，缺口即重建快照。 |
| UI 如何显示 Execution / Verification / Evidence？ | 通过 Node/Production Inspector 的只读关联查询，显示安全摘要与 immutable refs。 |
| UI 如何触发 Gate / Intervention？ | 提交带元数据的语义命令；Gate 决策与恢复沿既有 authority path。 |
| UI 如何修改 Plan / Replan？ | 创建 Change Request → Impact Analysis → Revision → Approval → Reconciliation。 |
| UI 如何恢复 Production？ | 仅提交 resume intent；Control Plane 再检查 guard、policy、budget、gate、resume context。 |
| UI 如何处理 Worker failure？ | 显示不确定性与 lease/recovery 状态；不把崩溃等同失败完成。 |
| UI 如何处理 stale state / concurrent modification？ | watermark、entity version、409/reload、diff；禁止客户端静默重放。 |
| 如何保证用户看到 authoritative state？ | Snapshot 有版本/水位；事件按序重放；最终查询确认；显式 stale banner。 |

## 38. P0–P5 Compatibility

| 既有能力 | UX 复用方式 | P6 不得做的事 |
| --- | --- | --- |
| Project/Task 状态机 | Production/Node 体验状态适配 | 新建冲突的运行状态或直接改 `state`。 |
| Task DAG / Work Graph | Graph 结构与依赖投影 | 把 UI tree 当成调度图。 |
| Command idempotency / expected version | 每个干预与计划批准命令的前置条件 | 忽略版本冲突或将重试变成重复执行。 |
| Event / Outbox / Relay | Projection Stream 的事实来源 | 增加无 Outbox 的前端专用事实事件。 |
| Scheduler lease / fencing / locks | Pause/Stop/Retry/Worker UX 的协调语义 | 直接 kill 后立即认定已停止，或复用旧 token。 |
| Worker lifecycle / Docker adapter | Execution/Worker Inspector | Worker 自报 PASS 即显示完成。 |
| Verification / Evidence invalidation | 完成、失败、失效和重跑显示 | 将旧证据继续展示为有效。 |
| Recovery / replay / reconcile | Recovery UX、错误不确定性 | replay 覆盖权威状态。 |
| Human Gate / OIDC | Gate Inbox、审批、恢复 | 前端直接恢复项目或伪造审批。 |
| Product API / FastAPI | 查询和命令统一入口 | 通用 PATCH、任意 SQL、状态写入 API。 |
| Artifacts / Secrets / OTLP | 产物引用、可观测性摘要 | 回显 secret 或把监控遥测当作 authority。 |

## 39. P6 Required Changes

以下为设计明确标记的 **[P6 REQUIRED]** 能力。它们是把现有 Control Plane 接线为可用产品的增量，不是对 P0–P5 权威逻辑的替换。

| 能力 | 最小 P6 内容 | 原因 |
| --- | --- | --- |
| Production/Plan 查询投影 | Production Snapshot、Plan Revision、Node/Edge、关联 Task/Execution/Evidence | 当前 API 无完整工作空间读模型。 |
| Master Plan 域 | Draft、Review、Approve、Revision、diff、immutable history | 当前 Planner/Task 图不是用户可审阅主计划。 |
| Idea / Software Request 语义入口 | allowlisted intake command | 当前 P6 计划已识别该入口缺失。 |
| PlanChangeRequest + ImpactAnalysis | L1 变更与确定性影响锥 | 防止运行中直接改代码/图。 |
| Intervention 域与命令 | pause/resume/stop request + status projection | 使既有控制协议对用户可见且可跟踪。 |
| Projection Stream（SSE） | Snapshot watermark、事件 cursor、去重/重连规则 | 当前 API 没有实时工作流订阅。 |
| Live Workflow Graph / Inspector | 最小 Web Workspace 与 Gate/Evidence 关联 | 当前仅有最小 Human Gate HTML。 |
| P6 验收和故障 UX 测试 | stale/reconnect、重复/乱序、intervention、mutation、Gate 表现 | UI 不能绕开既有 conformance 原则。 |

## 40. Security Considerations

权限检查在服务端执行，UI 只根据权限投影隐藏或禁用控件，不能作为授权依据。每个命令绑定身份、理由、预期版本、幂等键与审计；自然语言解析永远不授予额外权限。Evidence 和 Artifact 默认最小展示，secret、token、密码、原始凭证、可利用的内部网络细节和 fencing token 全部脱敏。Gate 必须防止过期、重放、跨 Production 复用、越权审批和“Approve 后内容已变”的 TOCTOU；审批对象必须绑定 revision/hash/impact analysis/风险上下文。

## 41. Concurrency Considerations

Plan 编辑使用 revision-level optimistic concurrency；Node/Graph 结构操作使用 Plan Revision 版本；执行控制使用现有 Task/Project/Execution lease/lock scopes。两个用户同时编辑时，第二个提交收到 409 与三方 diff，不做最后写入者获胜。一个用户变更计划而 Worker 在运行时，变更不立即取代 runtime；先设置调度屏障、达成 checkpoint/cancellation 或确定执行不确定性，再 reconcile。完成节点是否复用取决于 Artifact hash、Verification 有效性和依赖兼容性，不取决于 UI 显示的绿色状态。

## 42. Accessibility

Graph 之外必须提供完整结构树和文本摘要；不能要求鼠标拖拽才能理解依赖。所有颜色状态提供标签、图标、文字与可读 tooltip；红/绿不是唯一编码。节点、Gate、Command Bar、Inspector tab 和弹窗均可键盘操作；焦点按逻辑图顺序移动；实时更新不抢焦点，紧急状态以可配置 aria-live 通告。事件时间显示为本地时区并保留绝对时间；动画可按系统偏好减少；错误文本必须说明下一步而非只显示代码。

## 43. UX State Matrix

| Production | Node | 用户动作 | 系统响应 | UI 响应 |
| --- | --- | --- | --- | --- |
| DRAFT | DRAFT | Start Planning | 创建 Intake 与 Plan Draft | 跳转 Plan Review，显示草稿版本。 |
| PLANNING | PLANNED | Approve Plan | 校验 revision、创建审批事实、materialize 可运行任务 | 显示“已批准，正在准备生产”。 |
| RUNNING | RUNNING | Pause Node | 创建 Intervention，协调 checkpoint/cancel/lease | 节点显示 `Pausing`，完成后显示 Paused 或解释失败。 |
| RUNNING | RUNNING | Stop Production | 提交取消意图，协调所有受影响执行 | 顶部显示 Stopping；只在权威取消后显示 Stopped。 |
| PAUSED | READY/PAUSED | Resume | 重新检查 guard/policy/budget/gate/resume context | 显示 Resume requested，成功后图恢复可运行状态。 |
| RUNNING | FAILED | Retry | 读取 failure/策略，创建新的执行尝试或 recovery action | 显示 retry preview；不覆盖旧失败。 |
| RUNNING | RUNNING | Modify Node | 创建 Change Request 与 Impact Analysis | 打开受影响图与 Revision Diff。 |
| RUNNING | RUNNING | Decompose | 协调运行、创建子图、更新依赖 | 原节点标为 Superseded/Checkpoint source，新节点待批准/就绪。 |
| RUNNING | BLOCKED | Explain | 读取 blockers、决策、事件、依赖状态 | Inspector 显示阻塞链与安全建议。 |
| WAITING_HUMAN | 任意 | Approve Gate | 提交 Gate decision 并由 authority apply | Gate 显示 Applying；成功后恢复或进入下一状态。 |
| VERIFYING | VERIFYING | 查看证据 | 只读查询当前验证与 Evidence | 显示进行中检查；不能提前显示通过。 |
| RUNNING | PASSED | L2 Replan | 计算受影响锥与证据有效性 | 已完成节点显示 Keep/Reverify/Invalidate 结论。 |
| RECOVERING | RUNNING uncertain | 页面重连 | Snapshot + cursor 重新同步 | 显示恢复进度；控制受限直到权威状态明确。 |
| 任意 | 任意 | 旧版本提交 | expected version 冲突，拒绝命令 | 显示冲突 diff、刷新和重新预览入口。 |

## 44. User Stories

| ID | 用户故事 | 验收核心 |
| --- | --- | --- |
| US-001 | 作为产品负责人，我能从 Idea 创建 Production Draft。 | Idea 有追踪 ID，未批准计划不执行。 |
| US-002 | 我能审阅 Master Plan 的目标、约束、架构和节点。 | 计划可读、可编辑、版本化。 |
| US-003 | 我能批准或拒绝 Plan。 | 批准绑定 revision/hash；拒绝不启动生产。 |
| US-004 | 我能看到获批 Production 自动进入运行准备和执行。 | 仅 READY 节点被调度。 |
| US-005 | 我能在图中看到 Live Workflow 和下一步。 | 图来自权威 Snapshot/事件。 |
| US-006 | 我能知道哪个 Worker 正在做什么。 | Worker 与 execution attempt/lease 关系可解释。 |
| US-007 | 我能暂停 Production 而不破坏恢复能力。 | checkpoint/guard/审计可见。 |
| US-008 | 我能停止一个运行 Node。 | cancellation 不等于强制 kill；不确定性可见。 |
| US-009 | 我能请求修改 Node 的技术选择。 | 系统先输出 Impact Analysis。 |
| US-010 | 我能将过大的 Node 分解为安全粒度。 | 依赖、历史和运行协调保留。 |
| US-011 | 我能在生产中修改局部计划。 | L1 revision 不影响无关完成成果。 |
| US-012 | 我能触发 Local Replan。 | 下游依赖锥和重新验证显式可见。 |
| US-013 | 我能触发 Master Plan Rebuild。 | 旧计划冻结可查，新计划需审批。 |
| US-014 | 我能理解系统如何计算影响。 | Affected/Unaffected/Invalidated/Keep 清晰可见。 |
| US-015 | 我能审批 Plan Revision。 | 审批绑定分析和版本，冲突拒绝。 |
| US-016 | 我能处理 Human Gate。 | Gate 有风险、证据、过期和审计。 |
| US-017 | 我能理解 Worker Failure 后系统在做什么。 | lease、reconcile、retry/未知状态可见。 |
| US-018 | 我能理解 Verification Failure 与恢复方案。 | Worker 结果与 verifier 结论不混淆。 |
| US-019 | 我能在断线或重启后恢复可信视图。 | Snapshot rehydrate，陈旧状态显式标注。 |
| US-020 | 我能在交付时检查验证、证据与产物。 | Delivery 结论可追溯。 |

## 45. Acceptance Criteria

A. 用户可在接近实时的 Snapshot + Event Stream 中看到 Production 状态；断线后显示陈旧并可正确重连。
B. 用户可请求停止运行工作；系统必须确认 cancellation/checkpoint/lease 后才显示最终停止。
C. Stop 不得绕开 authoritative state、破坏 fencing、资源结算或恢复能力。
D. 用户可修改计划，但只能经 Change Request、Impact Analysis、Revision 与批准。
E. 系统可计算并呈现确定性的图/产物/验证影响。
F. 系统可对受影响节点做局部重规划，并将无关完成节点作为显式复用候选。
G. Plan Revision、Intervention、Gate 和 Worker execution 均具版本与审计。
H. Evidence 和 Verification 结果可从 Graph/Inspector 访问，Evidence 失效会更新 UI。
I. Production 可在合法 resume context 下恢复；Gate 决策不等于前端直接恢复。
J. 重复、乱序、缺失事件和 stale UI 不得造成错误状态回退或副作用重复。
K. Command Bar 不得绕过 Authority，未知/高风险命令必须停在预览或 Gate。
L. P0–P5 的命令幂等、expected version、lease/fencing、验证隔离、恢复、secret 边界和 Product API 禁止通用 mutation 的测试基线持续通过。

## 46. P6 Implementation Roadmap

| Slice | 目标 | 退出证据 |
| --- | --- | --- |
| P6-A：Read Model Foundation | Production Snapshot、Node Inspector 查询、watermark、权限/脱敏 | Snapshot contract 与 P0–P5 投影一致性测试。 |
| P6-B：Idea and Plan Gate | Software Request、Master Plan Draft/Approve、Revision history | 未批准时零执行；批准版本可追溯。 |
| P6-C：Live Workspace | Factory Home、三栏布局、Graph、SSE 重连/stale UX | 真实运行能展示 Worker/Verification/Evidence。 |
| P6-D：Intervention | Pause/Resume/Stop preview 与受控命令 | checkpoint/fencing/recovery 端到端证据。 |
| P6-E：Mutation MVP | L1 Node Modification + 影响锥 + Revision approval | 未受影响成果保留、受影响验证重跑。 |
| P6-F：Hardening | Failure/recovery UI、Gate、访问控制、可访问性、验收矩阵 | 断线、重复/乱序、崩溃、Gate、冲突测试。 |

### Recommended P6 Scope

| 优先级 | 范围 |
| --- | --- |
| **MUST HAVE** | Idea Entry；Master Plan Draft/Review/Approve；权威 Production Snapshot；最小 Live Workflow Graph；Node/Production Inspector；Evidence/Verification 链接；SSE + reconnect/stale；Pause/Resume/Stop Intervention；Human Gate 收件箱；L1 Plan Mutation 与确定性 Impact Analysis；版本、审计、并发冲突、P0–P5 回归。 |
| **SHOULD HAVE** | Workforce 汇总；运行 Node 的单层 Decompose；L2 Local Replan；Command Bar allowlist；交付准备度视图；TUI inspect/events/gates。 |
| **NICE TO HAVE** | 图层切换、节点多选、计划差异的视觉 overlay、基于角色的首页视图、变更成本估计。 |
| **FUTURE（P7/P8）** | L3 Master Plan Rebuild 的全自动迁移编排；多人实时计划编辑；WebSocket 协作；任意图形拖拽编辑；自动/递归分解与合并；复杂代码语义影响分析；跨 Production 资源调度；Skip 的可执行策略；高级 TUI；移动端专用体验。 |

## 47. Open Questions and Product Decisions Required

以下问题需要产品负责人明确决定，不能由 UX 文档或模型自行假设。

| 决策 | 选项/影响 | 建议 |
| --- | --- | --- |
| Plan Approval 默认门槛 | 每个 Production 必须批准，还是允许低风险模板自动批准？ | P6 一律显式批准，建立信任与审计基线。 |
| Production 的人类角色 | Owner、Editor、Approver、Operator 的最小 RBAC 如何划分？ | P6 至少 Owner/Approver/Operator/Viewer 四类；复用 OIDC identity。 |
| Gate policy | 哪些部署/数据库/成本操作强制 Gate？ | 先采取 allowlist 和保守默认，再以 ADR/Policy 扩展。 |
| Pause SLA | 多久后将 cancellation 视为 timeout/uncertain？ | 按 Worker runtime 配置；UI 展示 deadline。 |
| 计划保留与审计 | Revision/Evidence/Artifact 保存多久？ | 对齐 P4 retention/secret policy，禁止 UI 自定义绕过。 |
| 进度算法 | 是否允许展示估算百分比？ | P6 显示阶段/节点事实优先；百分比标注来源。 |
| 命令语言 | 中文/英文混合意图、低置信度行为、敏感命令策略？ | P6 allowlist + 明确澄清，不自动执行未知命令。 |

## Final Conclusion

1. **Proteus Web UI 是什么？** 它是接线到 Control Plane 的 Live Production Workspace：一个对软件生产过程进行可视化、控制、审阅与审计的界面。
2. **为什么不是 Chat UI？** Chat 不能天然表达版本化计划、DAG、Worker lease、验证、证据、并发冲突和恢复；它只能作为意图入口。
3. **为什么是 Live Production Workspace？** 因为用户管理的是持续生产的系统状态和交付责任，而非单次文本问答。
4. **Workflow Graph 是什么？** 它是获批 Plan 结构与权威运行时事实合成的 Tree + DAG 投影，可观察、可检查、可经治理修改。
5. **Plan 和 Workflow 的关系是什么？** Plan 是意图与约束的版本化蓝图；Workflow 是该蓝图 materialize 后，叠加 Task/Execution/Verification/Evidence 的实时事实。
6. **Production 和 Task 的关系是什么？** Production 是长期的用户目标和交付单元；Task 是某个获批版本下受控的执行单元。
7. **Worker 和 Node 的关系是什么？** Worker 绑定某次 execution attempt，以 capability、lease 和 fencing 为界；它不永久拥有 Node，也不能自证完成。
8. **Human Intervention 如何工作？** 用户提出受审计 Intervention；系统预览、授权、协调 checkpoint/lease/gate，再由 Control Plane 应用与事件投影确认。
9. **Plan Mutation 如何工作？** Change Request → Impact Analysis → Revision Diff → Approval/Gate → Scheduler Reconciliation → Worker Reassignment → Resume；历史不覆盖。
10. **Proteus 与 Manus 的核心差异是什么？** Manus 以 Task/计划确认/消息生命周期降低任务试错；Proteus 以 Production/Workflow/Authority 管理可验证的软件生产。
11. **Proteus 与 Hermes 的核心差异是什么？** Hermes 是强 Control Plane 运行时；Proteus 是将其安全、可理解地暴露给用户的产品工作空间。
12. **P6 应实现哪些能力？** 实现本文 MUST HAVE 的窄而真纵向切片，优先连接既有权威能力。
13. **哪些能力必须留到 P7/P8？** 将多人协作、任意图编辑、复杂自动重建、跨生产线调度与高频双向协作留到已有 P6 证据成立之后。

## References

[1]: [Manus — Introducing Plan Mode: A New Way to Work with Manus](https://manus.im/blog/manus-plan-mode)
[2]: [Manus Open API — Task Lifecycle](https://open.manus.im/docs/v2/task-lifecycle)
[3]: [Manus Open API — task.listMessages](https://open.manus.im/docs/v2/task.listMessages)
[4]: [Manus Open API — task.confirmAction](https://open.manus.im/docs/v2/task.confirmAction)
[5]: [Proteus repository — architecture, runtime and P0–P5 documentation](https://github.com/yanzhao77/Proteus)
[6]: [第三方 Plan Mode 演示（仅辅助观察，不作为产品事实依据）](https://www.youtube.com/watch?v=NrcGo9AXr9A)
