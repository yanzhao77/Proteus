# Proteus Production Entry & Factory Workspace Design V1.0

**状态：** 正式设计基线
**作者：** Manus AI
**日期：** 2026-08-17
**范围：** 最终用户的 Production Entry / Factory Home / Portfolio / Plan 前置体验，以及到既有 Live Production 的连接。本文只包含设计与开发规格，**不实现代码、不修改 P0–P5，也不修改当前 P6 Autonomous Production Trial**。

> **核心决策：** Proteus 的入口不是 Chat Session；它是 **Production Creation**。用户不是来“问 AI 一个问题”，而是把一个 Idea 交给 Software Factory，并以生产负责人的身份审阅、批准、进入和控制一个 Production。

![Production Entry 到 Live Production 的权威流程](assets/production_entry_flow.png)

## 1. Executive Summary

Proteus 已具备 P0–P5 Control Plane：Project/Task 权威状态、命令幂等与版本检查、任务 DAG、规划/策略/风险/选择、执行请求、Scheduler lease/fencing、Worker/Verifier 隔离、Evidence/Artifact、恢复、人类审批、审计和受限 Product API。当前 P6 Autonomous Production Trial 正在将这些能力连接成真实的受限软件生产闭环。现有最终用户表面仍十分有限：FastAPI 暴露项目状态、决策解释、Human Gate、对账发现和 Docker 观察；HTML UI 只有最小 Human Gate 页面；没有完整的生产入口、Portfolio 或 Live Workspace。[1] [2]

本设计把 **Factory Home** 定义为 Production Portfolio 与 Production Creation 的统一入口。它首先让用户看到问题“**What do you want to build?**”，用一句自然语言 Idea 即可开始；系统先创建可恢复的 Entry Draft，再生成 Understanding、必要澄清、可见 Assumptions、Production Proposal 和 Master Plan。只有用户明确批准有效 Master Plan，才通过语义命令建立/关联既有 `Project` 权威聚合，并交由既有 Control Plane 物化 Task、调度执行和进入 Live Production。入口不能直接启动 Worker、写 Project/Task 状态，或成为第二套执行系统。

P6 Entry 的最小版本只解决“首次进入、自然语言 Idea、Plan 前理解、明确批准、Production Portfolio、打开运行中的 Production、Gate 可见性和到 Live Production 的导航”。完整 Plan 编辑、运行中 Plan Mutation、图形编辑、多人协作、跨 Production 编排和高级自然语言控制应延后至 P7+。这个收敛保证入口层既能为 P6 Trial 提供未来用户接口，又不会打断或替代正在进行的 Trial。

## 2. Product Philosophy

Proteus 的承诺是：**默认自主生产，人类随时可理解、介入和改变生产。** 这要求入口体验既避免复杂表单把技术选择推给用户，也避免黑箱自动执行。用户给出意图；Proteus 对可逆、低风险、行业常规的细节提出可见假设；当缺失信息会改变产品类型、成功定义、合规边界、不可逆成本或主要架构时，系统提出少量高价值澄清；最终由用户批准可读的计划后才进入生产。

| 入口原则 | 体验含义 | 不允许的反模式 |
| --- | --- | --- |
| Idea first | 首屏接受产品目标和成果，而非任务脚本或模型参数。 | 把第一屏做成泛聊天历史。 |
| Minimal input | 一句话可启动；更多信息按需展开。 | 首次使用即要求语言、框架、数据库、Worker、模型和部署配置。 |
| Explain before execute | Understanding、Proposal、Plan 均先于真实执行。 | Idea 一提交就创建执行请求或开始写代码。 |
| Autonomous by default | 系统自动分析、提出假设、生成计划、选择受策略约束的 Workforce。 | 把可合理决定的默认项全部抛回用户。 |
| Human-controllable | 用户可改 Idea/Assumption/Plan，审批 Gate，随时打开 Production。 | UI 隐藏重大决定、状态或控制路径。 |
| Authority first | UI 只能请求、查询、预览、批准和发出语义命令。 | 浏览器直接改变 Project/Task/Execution 状态。 |
| Preserve work | 关闭浏览器不会丢失 Draft 或运行中的 Production。 | 让用户重新输入 Idea，或把本地表单当作唯一记录。 |

## 3. Product Positioning

Proteus 不是 `Chat → Agent → Answer`，而是 `Idea → Understanding → Proposal → Plan → Approval → Production → Live Production → Verification → Delivery`。聊天可以出现在 Idea 输入、澄清和 Command Bar 中，但只是语言界面；真正被创建、版本化、批准、执行与交付的是 Production。

| 概念 | 用户含义 | 后端/权威含义 |
| --- | --- | --- |
| Idea | “我想做一个类似 Linear 的项目管理系统。” | 一个可版本化的请求输入，不等于执行授权。 |
| Production Draft | 还在理解、澄清、Proposal 或 Plan 阶段的候选生产。 | **[P6 ENTRY REQUIRED]** 入口草稿及其 read/write contract；不是 Project/Task。 |
| Production Proposal | 对“做什么、为什么、产出什么、预计如何做”的轻量说明。 | **[P6 ENTRY REQUIRED]** 不可变 proposal revision，可引用 assumptions/risks。 |
| Master Plan | 可编辑、可审阅、可批准的完整生产蓝图。 | 与既有 Live Production UX 的 Plan Revision 域对齐。 |
| Production | 用户看到的长期生产单元。 | 对既有 `Project` 权威聚合的用户产品别名与 Portfolio projection。 |
| Live Production | 正在被 Control Plane 物化、调度、验证和交付的 Production 控制中心。 | 既有 Project/Task/Execution/Verification/Evidence 的权威投影。 |

因此，用户应输入 **Idea / Goal / Product Requirement**，而不是低层 Task。Task、Worker、模型、技术栈和执行顺序默认由 Proteus 在 Plan 与策略约束内决定。用户只在需要表达目标、硬约束、成功标准、法律/安全边界、已有资产、主要产品分岔或不可逆取舍时做决定。

## 4. Existing Proteus Architecture Context

审查确认现有域以 `Project` 和 `Task` 为权威对象。Project 状态包括 `CREATED`、`INTAKE`、`DISCOVERY`、`PLANNING`、`DESIGNING`、`IMPLEMENTING`、`VERIFYING`、`HARDENING`、`PACKAGING`、`DELIVERING`、`ACCEPTED`，以及 `WAITING_FOR_HUMAN`、`PAUSED`、`BLOCKED`、`RECOVERING`、`FAILED`、`CANCELLED`。Task 具有 `NEW`、`READY`、`ASSIGNED`、`RUNNING`、`VERIFYING`、`PASSED`、`FAILED`、`RETRYING`、`BLOCKED`、`CANCELLED`、`SUPERSEDED` 等运行状态。[1]

现有入口能力是底层语义入口，而非最终用户入口：`CreateProject`、Pause/Resume/Cancel Project application command；P5 Product API 的项目状态和 Gate 查询；Human Gate 的最小 HTML Inbox/Detail；Trial Driver 中正在形成的受限 Software Request/Run 入口。它们可以被 Production Entry 复用，但不足以构成“用户从 Idea 开始生产”的体验。当前不存在 Production Draft、Idea Understanding、Clarification、Assumption、Proposal、Master Plan 前置流程、Production Portfolio 或完整 Web/TUI Entry。

| 现有能力 | Entry 复用方式 | Entry 不可做的事 |
| --- | --- | --- |
| `CreateProject` / Project Guard | 在 Plan 批准后由语义命令创建权威 Production/Project。 | 将它暴露为无审阅的“Create”表单或在 Idea 输入时直接调用。 |
| Command Envelope / expected version / idempotency | Draft、Approval、Gate、Pause 等所有可写命令的安全前提。 | 忽略冲突，或用浏览器重试产生重复 Production。 |
| Planner/Policy/Risk/Selection | Proposal/Plan 的受控后端衔接；批准后才进入执行链。 | 让 UI 或 LLM 直接选择/启动 Worker。 |
| Human Gate/OIDC | 首页 Gate 卡片、Gate Detail、审批与恢复。 | 将普通澄清问题伪装为 Gate，或前端直接 resume。 |
| Artifact/Evidence/Verification | Portfolio 和 Production Detail 的结果/可信度摘要。 | 在 Entry 阶段伪造 Evidence 或显示未验证为已完成。 |
| Event/Outbox/Replay | Portfolio 实时投影与重新打开后的状态恢复。 | 用前端本地状态充当真相源。 |

## 5. Factory Entry Concept

Factory Entry 是一个五级逐步披露模型。用户不需要在开始前成为技术架构师；但系统也不把推断伪装为事实。

| 层级 | 用户的主要动作 | Proteus 的主要动作 | 执行边界 |
| --- | --- | --- | --- |
| L1 — Idea | 输入一句话、可选附件/已有仓库/约束。 | 创建 Entry Draft，分析目标和未知项。 | **禁止执行。** |
| L2 — Understanding | 认可或修正系统复述，回答必要问题。 | 提取目标、范围、成功标准、约束、风险与未知项。 | **禁止执行。** |
| L3 — Proposal | 快速确认“这是不是我要做的东西”。 | 提出成果、阶段、技术方向、Workforce、验证/交付策略与复杂度。 | **禁止执行。** |
| L4 — Master Plan | 编辑、批准、拒绝或要求修订。 | 生成完整版本化计划并进行 Plan Review。 | 只有 APPROVED 后才允许 materialization。 |
| L5 — Live Production | 观察、控制、审计、处理 Gate。 | 使用既有 Control Plane 执行、验证、恢复和交付。 | 已有 Live Production 规则生效。 |

这个模型采用 **Progressive disclosure（渐进式披露）**：第一，它不要求用户填写“语言/框架/数据库/Worker/模型”大表单；第二，它不让 Agent 在用户尚未确认系统理解前直接写代码。所有渐进层级都可以保存和恢复，且都有明确的 Exit：修改、返回上一步、生成下一层或放弃 Draft。

## 6. Factory Home

### 6.1 定义与目标

Factory Home 是 **Production Portfolio 的总览入口**，不是项目管理工具，也不是 Live Production 的缩小版。它解决四个问题：我现在可以创建什么？哪些 Production 在运行？哪些事项需要我决定？我如何回到上次的生产上下文？它的核心布局是“新建生产优先、行动请求优先、继续生产优先、历史结果随后”。

### 6.2 信息架构与布局

| 区域 | 内容 | 用户动作 | 数据来源 |
| --- | --- | --- | --- |
| Header | Proteus、Productions、Workforce、Activity、Settings；全局状态。 | 导航、打开 Gates、查看状态。 | 权限/Portfolio/健康投影。 |
| Hero — Production Creation | 标题 `What do you want to build?`、多行 Idea 输入、可选附件/已有资产入口、`Start Planning`。 | 提交 Idea、继续 Draft。 | Entry Draft command/read model。 |
| Action Required | Waiting Human Gates、失败/阻塞、将过期的 Plan Approval。 | Review、Open Production。 | Gate/Project/Plan projection。 |
| Continue Production | Running、Paused、Recovering 的生产卡片。 | Open Production / Resume。 | Project/Task/Execution projection。 |
| Recent Outcomes | Completed/Cancelled/Failed 生产与最近产物。 | Open delivery / inspect evidence。 | Project/Artifact/Verification projection。 |
| Factory Status | Workforce 可用性、Control Plane/API 观测、事件延迟。 | 查看诊断。 | 只读运维投影。 |

Hero 是唯一的主 CTA。输入占据视觉中心，placeholder 用“描述你希望交付的软件、用户或业务问题”，而不是“Ask Proteus anything”。按钮文案为 **Start Planning**；使用该文案而非 Start Execution/Start Build，明确表示下一步是理解和计划，不是执行。

### 6.3 Production 卡片

Production 卡片显示名称、状态、当前阶段、进度来源、当前 Node/Blocker、更新时间、Owner、Gate 徽标和主动作。进度的呈现必须标注为“已完成节点权重”或“阶段进度”；未知时显示 `Progress not yet estimated`，不能制造精确百分比。状态永远使用 icon、label 和文本三重表达，例如 `● RUNNING`、`⏸ PAUSED`、`⚠ WAITING FOR HUMAN`、`✓ COMPLETED`、`✕ FAILED`。

## 7. Idea Entry

### 7.1 交互

用户可以只输入一句话，例如“我想做一个类似 Linear 的项目管理系统”。`Start Planning` 立即创建一个服务端 Entry Draft 和第一版 Idea Revision；UI 显示“正在理解你的目标”，而不显示执行进度。可选字段仅在用户需要时展开：已有仓库/文件、必须遵守的约束、目标用户、交付偏好。它们不是必填技术表单。

系统不要求用户选择项目类型、Worker、模型、语言、框架、数据库或部署目标。项目类型是 Understanding 的候选结论；Worker/模型是批准后受 policy/capability 约束的选择；技术栈是可见 Assumption 或 Plan 中的决定。用户可以表达硬约束，例如“必须部署在现有 Docker 环境”“不能使用第三方 SaaS”“必须兼容 Postgres”，但无需先选实现细节。

### 7.2 页面规格

| 项目 | 规格 |
| --- | --- |
| Purpose | 以最少输入创建一个可恢复、可审计、尚未执行的 Production Draft。 |
| User | 首次用户、Returning User、Product Owner。 |
| Entry | Factory Home Hero、New Production、Command Bar 的新建意图。 |
| Exit | Idea Understanding、保存为 Draft、取消。 |
| Primary Action | Start Planning。 |
| Secondary Actions | 附加资产、恢复草稿、查看示例、取消。 |
| Data | Idea text、optional attachments/constraints、actor、draft version、created/updated time。 |
| Events | `entry_draft.created`、`idea.revision_submitted`、`understanding.requested`（入口投影事件；底层命名需映射现有规范）。 |
| Error | 空输入、附件不支持、权限不足、草稿版本冲突、网络失败。 |
| Empty State | 首次使用说明一句话即可开始，给出 2–3 个示例。 |
| Loading State | Skeleton + “Proteus is understanding your goal”；允许关闭后稍后恢复。 |

## 8. Idea Understanding

Understanding 不是模型的长篇自言自语；它是用户确认系统是否正确理解的可审阅摘要。页面按五个块呈现：`I understand your goal as`、Core objectives、Potential requirements、Potential assumptions、Potential risks / unknowns。每一项有来源标签：**来自你的输入**、**Proteus 推断**、**需要确认**。这样用户知道哪些是事实、哪些是系统建议。

用户可选择 `Continue to Proposal`、`Modify Idea`、`Answer questions` 或 `Ask Proteus to explain`。修改 Idea 产生新 Idea Revision；旧 Understanding 不被覆盖，而是标记为 superseded input。若用户离开，Draft 保留在 Portfolio 的 `Drafts` 分区；若 Understanding 生成失败，显示可重试、查看已保存 Idea、或手动编辑简短补充，不得丢失输入。

## 9. Smart Clarification

Proteus 只在问题会显著改变生产方案且不存在安全默认值时询问用户。每一轮最多显示一至三个问题，并优先使用选择卡、短文本或“使用建议”按钮，而不是开放式追问链。

| 类别 | 触发条件 | 示例 | 体验 |
| --- | --- | --- | --- |
| Required clarification | 产品模式、主用户、合规、不可逆成本、主要成功标准缺失。 | “电商网站是单商户、平台型多商户，还是先按单商户？” | 必须回答或显式选择“使用安全建议”后才能 Proposal。 |
| Optional clarification | 能改善方案但不影响 MVP 基本成立。 | “是否优先移动端体验？” | Proposal 侧栏显示，不阻断。 |
| Assumption | 低风险、可逆、可解释的默认决定。 | “数据库默认为 PostgreSQL；理由：现有运行时与验证基线。” | 显示 Accept / Change；记录进计划链。 |
| Risk warning | 需要高风险外部动作、秘密、生产数据或显著成本。 | “未来部署可能需要生产数据库迁移。” | 先预警；只有实际动作才创建 Human Gate。 |

Clarification 不是 Human Gate。澄清的目的是获得产品意图；Gate 的目的是对明确的高风险权威行动进行批准。混用两者会让普通用户把需求回答误认为安全审批，也会破坏既有 Gate 的审计语义。

## 10. Assumption System

Assumption 是 Proteus 保持低摩擦而不失透明度的关键机制。每项假设具有类别、默认值、理由、风险级别、可逆性、来源、状态和计划影响。用户可 Accept、Change 或 Ask Why。用户 Change 后系统重新生成受影响的 Understanding/Proposal/Plan，但不得静默保留旧的技术结论。

| 示例 | 默认值 | 理由 | 用户控制 |
| --- | --- | --- | --- |
| Backend | Python | 与当前运行时、Golden Todo/验证基线兼容。 | 可在 Proposal/Plan 中修改。 |
| Database | PostgreSQL | 当前 Control Plane 与试验基线已使用 PostgreSQL。 | 可修改；触发计划影响说明。 |
| API | REST | 可验证、可文档化的默认边界。 | 可修改为其他接口风格。 |
| Deployment | Docker | P5 单节点部署和 P6 Trial 的已有基线。 | 可设为“不含部署”或另行约束。 |
| Testing | automated | Verification/Evidence 的系统原则。 | 不能完全取消最低验证；可调整策略。 |

Assumption 不能只出现在 UI。接受/变更必须生成可追踪的 Decision/Plan ref；Master Plan 必须列出当前有效 assumptions；之后的 Plan Mutation/Impact Analysis 才能知道哪些节点或验证受影响。P6 Entry MVP 可先提供 Assumption 列表、接受和编辑请求；复杂的自动语义影响分析留到 P7。

## 11. Production Proposal

Production Proposal 是 Master Plan 前的轻量确认层。它以一页回答：我们要构建什么？为什么？成功时的可见结果是什么？Proteus 认为需要做哪些阶段？预计架构与 Workforce 是什么？主要风险与复杂度如何？Proposal 的目标不是替代 Plan Review，而是让用户快速确认“这确实是我要交给工厂的生产”。

Proposal 包含：Product statement、target outcome、scope in/out、关键 requirements、assumptions、候选 architecture、预计 Phases、Workforce profile、verification/delivery approach、complexity band 与已知 risk。用户可 `Generate Master Plan`、`Modify Idea`、`Change assumptions`、`Ask Proteus to revise` 或 `Reject Draft`。Proposal 仅创建不可变 revision；它不能创建 ExecutionRequest、分配 Worker 或改变 Project state。

## 12. Master Plan Transition

Production Entry 是既有 **Master Plan Review** 的上游，不是竞争流程。Proposal 被用户接受后，系统用 Idea/Understanding/Clarifications/Assumptions/Proposal 作为来源材料生成 `Master Plan Revision 1`。Plan Review 随即沿用 Live Production UX V1.0 的 Goal、Requirements、Constraints、Architecture、Phases、Nodes、Dependencies、Risks、Verification、Delivery 与 Workforce 结构。

用户可 Edit、Add/Remove Requirement、Split/Merge Node、Change Dependency、Ask to Revise、Reject、Approve。没有计划批准，绝不进入 Autonomous Production。批准前的 `Plan Revision` 是可审阅对象；批准后才触发 `Production Creation` 命令。若 Plan 生成中浏览器关闭，后台任务可继续或安全停止，但状态必须记录为 `PLAN_GENERATING`/`PLAN_REVIEW`；用户重新打开 Draft 时能看到最新权威进度，而非重新输入 Idea。

## 13. Plan Review

| 项目 | 规格 |
| --- | --- |
| Purpose | 将 Proposal 扩展为可执行前审阅的版本化 Master Plan。 |
| User | Production Owner、Authorized Approver。 |
| Entry | `Generate Master Plan`、Draft Resume、Proposal revision。 |
| Exit | Approved → Production Created；Reject/Revise → Draft/Proposal；Save → Plan Review。 |
| Primary Action | Approve Master Plan。 |
| Secondary Actions | Edit、Ask to revise、Add/Remove requirement、Decompose、Reject。 |
| Data | Plan Revision、assumption refs、risk/verification/delivery/workforce、content hash、approval status。 |
| State | Generating、Review、Revision Requested、Awaiting Approval、Approved、Rejected、Superseded。 |
| Events | `plan.created`、`plan.revised`、`plan.approved`、`plan.rejected`（映射至既有 Event Protocol）。 |
| Error | Validation/DAG conflict、stale version、generation failure、authorization failure。 |
| Empty/Loading | 无计划时提供 retry/return Proposal；生成时显示输入快照和可安全离开提示。 |

## 14. Production Creation

**真正创建 Production 的时刻是：用户明确批准一个仍有效的 Master Plan Revision。** 在此之前，系统只有 Entry Draft、Proposal 和 Plan revision；它不应创建可调度的 `Project`、Task Graph、ExecutionRequest、Artifact 或 Evidence。这个分界点让“用户只是探索一个 Idea”与“用户授权工厂开始生产”具有明确、可审计的语义。

| 时间点 | 创建对象 | 说明 |
| --- | --- | --- |
| 首次提交 Idea | `entry_draft_id`、Idea Revision | 服务端持久化，支持离开/恢复；不执行。 |
| Understanding/Proposal | 对应 revision、clarification/assumption records | 只形成审阅材料与决策链。 |
| 生成 Master Plan | Plan Revision | 仍然禁止 scheduler/materialization。 |
| 批准有效 Plan | `production_id` 与现有 `project_id` 的绑定、审批/command receipt | 通过受控 application command 建立 Authority。 |
| Authority 后续物化 | Task/Graph/Execution/AgentRun | 由既有 Control Plane 和 P6 Trial chain 决定。 |
| Worker/Verifier 实际产出 | Artifact/Evidence/VerificationResult | 入口不创建或伪造。 |

批准命令必须含 actor、reason、idempotency key、expected Plan version、approved content hash、assumption/proposal refs 和 correlation context。若 Plan 在预览后变化、假设被改、风险策略变化或用户权限已失效，批准必须失败并回到最新 Plan Review；前端不能“替用户确认旧版本”。

## 15. Production Portfolio

Portfolio 是 Factory Home 的列表与搜索层，且不引入额外 Organization/Workspace/Project Management SaaS 概念。Production 是唯一用户核心对象；`Project` 保持为后端权威聚合。用户可以在 All、Drafts/Planning、Running、Waiting, Paused、Completed、Failed、Cancelled 中筛选，按名称、Owner、状态、最后更新、Gate 和创建时间搜索/排序。

每个 Portfolio Item 最小字段包括：`production_id`、display name、状态/阶段、last authoritative update、current action/node summary、progress source/value、owner、waiting gate count、plan revision、health/staleness 和导航链接。列表的所有状态来自权威 read model；加载中显示 skeleton；没有 Production 时将用户引回 Idea Entry；没有筛选结果时显示清空筛选，而不是“创建一个假结果”。

## 16. Running Production

Running Production 从 Factory Home 的 Continue Production 区或 Production List 打开，直接进入既有 **Live Production Workspace**，而非在 Home 里复制图、Worker、证据和控制面板。卡片的主要按钮是 `Open Production`；如状态为 `PAUSED`，主按钮可为 `Open & Review Resume`，仍然先进入详情/受控恢复预览，不在首页后台直接 resume。

Factory Home 只回答“哪些生产值得我关注”和“我从哪里继续”；Live Production 回答“该生产正在发生什么、为什么、谁在做、证据是什么、我能做什么”。这种边界可避免首页变成第二个 Execution System，也符合 UX V1.0 的三栏工作区和 Inspector 模型。[2]

## 17. Resume Experience

用户关闭浏览器不会停止 Production，也不会丢失 Draft。再次打开后，Factory Home 的 Welcome Back 摘要显示：运行中的 Production 数、等待 Gate 数、暂停/恢复中数、最近完成数和可恢复 Draft 数。它提供最多三个高优先级 CTA：`Review gate`、`Open running production`、`Continue planning`。

恢复运行 Production 时，系统先读权威 Snapshot，再进入 Live Production；恢复草稿时，系统读最新 Draft revision、当前 Understanding/Proposal/Plan 生成状态与未回答的问题。浏览器本地只可保存非敏感导航提示；最终版本、状态和审批结果始终来自服务器。若事件流断开，UI 显示“State may be stale”，并刷新 Snapshot，不能把旧的 Running 卡片当成最终事实。

## 18. Human Gates

Human Gates 必须在 Factory Home 突出但不喧宾夺主。Action Required 区按风险、过期时间和对 Production 的阻塞程度排序；每张 Gate 卡展示 Production 名、具体行动、风险 label、原因、Evidence 数量、到期时间和 `Review`。用户点击后进入现有 Gate Detail/Decision 流；Approve/Reject 依然通过 Product API、身份断言、语义 decision 和 authority apply，Home 不能直接改变 `WAITING_FOR_HUMAN` 或 resume Project。

入口阶段的 Clarification 与未来可能发生的 Gate 必须明确区分。用户回答“按单商户设计”是产品澄清；用户批准“重置生产数据库”是高风险 Gate。前者改变 Proposal/Plan；后者改变具体受权威治理的执行路径。

## 19. Command Bar

Factory Home 可在 P6 以后提供自然语言 Command Bar，但它不是入口的主路径，也不能绕过 Authority。最小意图包括：`继续上次的知识库项目`、`查看需要我审批的 Production`、`打开 DreamKnowledge`、`创建新的 Production`。暂停所有 Production、重新规划、停止 Worker 等高影响操作必须显示 intent resolution、目标列表、影响预览、权限/风险、确认/Gate，并交给既有 Intervention/Plan Mutation 权威链。

P6 Entry MVP 可将 Command Bar 限定为导航和创建意图；高风险 control/plan intent 仅显示“Open the relevant Production to continue”，推迟到 Live Production Command Bar。这样 Home 不会获得意外的全局执行权限。

## 20. Information Architecture

```text
Proteus
├── Factory Home
│   ├── New Production / Continue Draft
│   ├── Action Required
│   ├── Continue Production
│   └── Recent Outcomes / Factory Status
├── Productions
│   ├── All
│   ├── Drafts & Planning
│   ├── Running
│   ├── Waiting
│   ├── Paused
│   ├── Completed
│   ├── Failed
│   └── Cancelled
├── Production
│   ├── Overview
│   ├── Idea & Proposal (before approval)
│   ├── Plan
│   ├── Live Production
│   ├── Workers
│   ├── Verification
│   ├── Evidence
│   └── Activity
├── Gates
└── Settings
```

`Idea & Proposal` 是 Draft/Plan 前的上下文页；Production 在批准后仍保留其来源材料的只读引用，以便用户理解最初目标和假设。Web 是主用户体验；TUI 是 Operator/Developer 的 monitor/inspect/debug/control 入口；API 是 machine/automation 的 Production creation/query/control/subscribe 接口。三者共享同一 Contract，但不共享对权威状态的直写权限。

## 21. User Journeys

### Journey A — 首次使用：Idea 到 Live Production

用户打开 Proteus，看到 Factory Home Hero 和空 Portfolio。用户输入“一款类似 Linear 的项目管理系统”，点击 Start Planning。系统保存 Draft，显示 Understanding；用户确认目标、选择“团队协作为主”，接受 PostgreSQL/Docker 等假设，查看 Proposal 后请求 Master Plan。用户审阅、编辑并批准 Plan；系统创建 Production/Project 权威关联，显示 `Production created — preparing controlled execution`，随后跳转至 Live Production Workspace。用户在那里看到 Plan、Workflow、Worker、Verification 和 Evidence，而不是回到聊天页面。

### Journey B — 用户中途离开

Production 正在运行时用户关闭浏览器。Control Plane 和 Worker 按既有协议继续/恢复，不依赖浏览器。用户重新打开 Proteus，Welcome Back 提示“2 Running Productions，1 Waiting Gate”；点击某卡片即加载权威 Snapshot 并进入对应 Live Production。用户不需要重新输入 Idea，也不需要依赖浏览器缓存恢复状态。

### Journey C — 需求不明确

用户输入“帮我做一个电商网站”。Understanding 将产品类型标为未知；系统只问一个 Required Clarification：“单商户商城、多商户平台，还是先采用单商户建议？”用户选择建议后，系统生成 Proposal。数据库、语言等可安全默认的选择作为 Assumption 展示，不用多轮问答阻断。

### Journey D — 用户修改需求

用户在 Proposal 中发现产品应支持“团队级权限”，点击 Modify Idea 或 Add Requirement。系统建立新 Idea/Proposal revision，显示变化对范围、假设和预计阶段的影响；旧 Proposal 保留可追溯。用户重新生成 Plan；未批准前始终不执行。

### Journey E — 已有 Production

用户从 Portfolio 搜索 `DreamKnowledge`，在卡片看到 `● RUNNING`、当前 Backend Implementation、最后权威更新时间和一个 Gate 徽标。点击 Open Production，进入 Live Production；首页不试图在卡片内展示完整 Graph 或执行控制。

### Journey F — Human Gate

首页 Action Required 显示“DreamKnowledge：Approve database migration，HIGH”。用户点击 Review，查看原因、风险与 Evidence，在现有 Gate 流中批准或拒绝。Control Plane 应用决策后，事件与 Snapshot 更新 Portfolio；首页最终显示新的状态，而不是在点击时乐观显示“已恢复”。

## 22. State Machine

入口 UI 使用 **Entry Flow 状态机** 描述用户体验，但不得覆盖或冲突现有 Project/Task 状态机。Entry Flow 在 Plan 批准后结束，并映射至 Project 的权威状态；Production 显示状态直接适配 ProjectState/TaskState/Execution/Gate 投影。

| Entry 状态 | 含义 | 可用动作 | 权威边界 |
| --- | --- | --- | --- |
| `IDLE` | 没有未完成输入。 | 输入 Idea、打开 Production。 | 无状态写入。 |
| `IDEA_INPUT` | 用户正在编辑未提交文本。 | Start Planning、保存草稿、取消。 | 本地临时状态；提交后服务端化。 |
| `UNDERSTANDING` | 已提交 Idea，系统分析中/已生成。 | Modify、Continue、Answer。 | 不可执行。 |
| `CLARIFICATION_REQUIRED` | 缺少阻断 Proposal 的关键意图。 | Answer、Use recommendation、Back。 | 不是 Human Gate。 |
| `PROPOSAL_READY` | 可审阅轻量方案。 | Generate Plan、Modify、Reject。 | 不可执行。 |
| `PLAN_GENERATING` | 正在生成 Master Plan。 | Leave safely、Cancel request、等待。 | 不可执行。 |
| `PLAN_REVIEW` / `PLAN_REVISION` | 用户审阅/修订 Plan。 | Edit、Approve、Reject、Rebuild。 | 不可执行。 |
| `AWAITING_APPROVAL` | Plan 有效且等待授权。 | Approve/Reject。 | Approve 是语义命令。 |
| `APPROVED` | Plan 批准回执已接受。 | 查看创建进度。 | 准备 Project authority creation。 |
| `PRODUCTION_CREATED` | Project/Production 关联已确立。 | Open Live Production。 | 后续由 Control Plane 物化。 |
| `RUNNING/WAITING_HUMAN/PAUSED/STOPPED/COMPLETED/FAILED/CANCELLED` | 运行期体验状态。 | Open、受控控制、查看 Gate/Evidence。 | 适配既有 Project/Task 状态，不另建权威状态机。 |

## 23. Event Flow

Entry 事件遵从现有 Command/Event Protocol：命令与状态/Outbox 在权威事务中一致提交，事件有 idempotency、schema version、correlation/causation 和可重放语义。以下名称是面向 UI 的投影分类，落地时必须映射到既有事件命名约定，而不是创建旁路 event store。

```text
Idea submitted
  → entry_draft.created / idea.revision_submitted
  → understanding.requested → understanding.ready
  → clarification.requested / answered
  → assumption.proposed / accepted / changed
  → proposal.created / revised
  → plan.created / revised
  → plan.approved
  → production.created (Project authority established)
  → production.started / node.started / node.progress
  → verification.completed
  → production.completed
```

客户端先请求 Entry/Production Snapshot，再订阅事件投影；重复事件按 event ID 去重，乱序按 aggregate version/sequence 处理；断线、未知关键 schema 或 cursor gap 时重新拉取 Snapshot。事件流只能加速 UI 更新，不能替代最终权威查询。

## 24. Authority Boundary

```text
User
  → Web Entry: input / query / preview / approve
  → Product API: semantic command + actor + reason + idempotency + expected version
  → Entry/Plan Authority: validate revision, assumptions, policy and approval
  → Project Authority: create/advance only after approved plan
  → Decision + state transition + outbox event
  → Portfolio/Live Production projection
  → Web/TUI/API read model
```

UI 可以 Request、Query、Preview、Approve 和 Command；UI 不可以直接写 authoritative state、选择最终 Task state、创建无 lease 的 execution、把 Worker 状态改为完成、应用 Gate decision 后直接 resume、或用本地 progress 覆盖服务端。Entry UI 也不可以为“更快体验”建立第二套 Scheduler、Task Graph、Plan 权威表或事件存储。

## 25. API Contract Proposal

本节是接口设计，不是实现任务。现有 `ProductApiFacade` 的禁止 PATCH/PUT/DELETE、禁止 state/SQL/event 字段、强制命令元数据和安全 response 策略必须延续。[1]

| 接口 | 用途 | 成功响应 | 关键约束 |
| --- | --- | --- | --- |
| `POST /production-drafts` | 创建 Draft 并提交初始 Idea。 | 202：draft ID、idea revision、status URL。 | actor/reason/idempotency；无 execution 字段。 |
| `GET /production-drafts/{id}` | 恢复 Draft/Understanding/Proposal/Plan 状态。 | revision、状态、问题、假设、next action。 | actor scope、content redaction。 |
| `POST /production-drafts/{id}/idea-revisions` | 修改 Idea。 | 新 revision 和重新分析引用。 | expected draft version。 |
| `POST /production-drafts/{id}/understanding` | 请求生成 Understanding。 | 202：analysis request/reference。 | 不创建 Project/Task。 |
| `POST /production-drafts/{id}/clarifications/{qid}/answer` | 回答必要/可选问题。 | 新 draft revision。 | 答案 schema 与 question 绑定。 |
| `POST /production-drafts/{id}/assumptions/{aid}/accept` | 接受默认。 | Decision/plan input ref。 | 记录理由/版本。 |
| `POST /production-drafts/{id}/assumptions/{aid}/change` | 改变默认。 | 新 revision/impact hint。 | expected version。 |
| `POST /production-drafts/{id}/proposal` | 生成 Proposal。 | 202：proposal revision。 | 不启动生产。 |
| `POST /production-drafts/{id}/plan` | 生成 Master Plan。 | 202：plan revision/ref。 | 进入 Plan Review。 |
| `POST /plans/{id}/approve` | 批准 Plan 并创建/关联 Production。 | 202：production/project ID、receipt。 | plan hash/version、actor/reason/idempotency。 |
| `GET /productions` | Portfolio。 | 分页的 card summaries。 | 状态来自权威投影。 |
| `GET /productions/{id}` | Production Overview。 | Snapshot/links to Plan/Live/Gates。 | 不暴露 secret/token。 |
| `GET /productions/{id}/events` | 未来 SSE 投影流。 | cursor-based events。 | P6 可定义，具体流实现按路线图。 |
| `POST /productions/{id}/pause|resume|stop` | 受限 control 入口。 | 202 intervention receipt。 | 复用既有 Project/Gate authority；禁止直写。 |

## 26. Web / TUI / API Boundary

| Surface | 主要职责 | 允许操作 | 不承担 |
| --- | --- | --- | --- |
| Web — Factory Workspace | Idea、Draft、Understanding、Proposal、Plan Review、Portfolio、Live Production 导航、人类控制。 | 逐步披露编辑、批准、查看 Gate/状态。 | 本地调度、直接 authority mutation、通用运维后门。 |
| TUI — Factory Control Console | Operator/Developer 的监控、inspect、debug、SSH/CI 控制。 | list/inspect drafts/productions/gates，提交受限语义控制。 | 富文本 Proposal/Plan 编辑、可视化 Portfolio。 |
| API — Automation Interface | Machine creation/query/control/subscribe。 | 版本化 read model 与 allowlisted commands。 | Chat-like 任意命令、通用 PATCH/SQL/事件注入。 |

## 27. Error & Recovery UX

| 情况 | 用户看见什么 | 系统处理 | 可行动下一步 |
| --- | --- | --- | --- |
| Idea 无法理解 | “需要更多上下文”，显示已理解片段和一个简短追问。 | 保留 Draft，不丢输入。 | Add detail / Use example / Save Draft。 |
| 信息不足 | Required clarification 卡片，不超过三题。 | 标记阻断原因。 | 回答 / 采用建议。 |
| Understanding/Plan 生成失败 | 保存的输入、失败时间、Retry。 | 记录错误/ref；不创建 Production。 | Retry / Edit / Return Proposal。 |
| Worker 不可用 | Portfolio/Proposal 显示 Workforce unavailable，批准预览提示。 | 不启动或保持 WAITING_FOR_RESOURCE。 | Review capability / Wait / 修改约束。 |
| Runtime 不可用 | Factory Status degraded，按钮说明受限。 | 保持权威状态，不显示假成功。 | Retry later / inspect status。 |
| 用户断网 | `Draft saved locally?` 仅限未提交输入；已提交显示 reconnect。 | 已提交状态以服务器为准。 | Reconnect / Refresh Snapshot。 |
| Event stream 断开 | `State may be stale`、最后更新时间。 | 从 cursor 恢复或 Snapshot rehydrate。 | Refresh / Open details。 |
| Production 创建失败 | Plan 仍为 APPROVED/可重试，显示 rejection code。 | 不产生半成品 Project；若事务未知则 reconcile。 | Retry safely / Review plan/version。 |
| Plan Approval 过期/冲突 | 显示版本差异与当前 Plan。 | 拒绝旧 approval。 | Review latest plan。 |
| 修改 Idea | 显示会生成新 revision、旧版本保留。 | 重新计算 Understanding/Proposal。 | Confirm change。 |
| 生成中离开 | Draft 卡片显示 `Preparing plan`。 | 后台按权威 job 状态继续/结束。 | Resume Draft。 |
| 重新打开运行 Production | Welcome Back + card。 | 读 Snapshot，进入 Live Workspace。 | Open Production。 |

## 28. Design System

Entry Design System 只定义语义与层次，不实现 CSS。视觉层级依次为：用户目标/主 CTA、需要用户处理的 Gate/失败、正在进行的 Production、可恢复 Draft、历史结果、Factory 运维摘要。所有状态不能只靠颜色；必须同时提供 icon、label、文本和可访问的状态描述。

| 语义 | 表达 | 使用位置 |
| --- | --- | --- |
| Running | `● RUNNING` + 活动文案 + 非侵入动态提示。 | Production card、Portfolio、Live link。 |
| Paused | `⏸ PAUSED` + resume context。 | Continue Production。 |
| Waiting Human | `⚠ WAITING FOR HUMAN` + 风险/行动。 | Action Required、Gate Detail。 |
| Completed | `✓ COMPLETED` + 验证/交付摘要。 | Recent Outcomes。 |
| Failed | `✕ FAILED` + 失败说明与 Evidence/Recovery link。 | Portfolio、Action Required。 |
| Planning/Draft | `○ PLANNING`/`DRAFT` + 当前层级。 | Drafts、Entry Flow。 |
| Loading | Skeleton + 保留上一次内容 + 状态文案。 | Home、Understanding、Plan。 |
| Empty | 解释价值 + Idea 示例 + 主 CTA。 | First-use、无筛选结果。 |
| Warning | 明确的影响/理由/下一步。 | Assumption、risk、Gate。 |

所有可点击卡片有清晰标题和状态；键盘可进入 Hero、卡片、Gate、筛选和导航；实时更新不抢焦点；用户减少动画偏好被尊重。进度必须声明来源，不能用色彩和百分比暗示未经验证的完成。

## 29. P6 Scope

| 优先级 | P6 Entry 内容 | 说明 |
| --- | --- | --- |
| **MUST HAVE** | Factory Home；一句话 Idea Entry；服务端可恢复 Draft；Understanding；Required Clarification；可见 Assumptions；Proposal；Master Plan 跳转/Review；显式 Approval；批准后 Production/Project 创建语义；Portfolio；Open Running/Paused/Waiting Production；Human Gate visibility；权威状态/权限/错误恢复。 | 形成用户入口到 P6 Execution/Live Production 的最小桥梁。 |
| **SHOULD HAVE** | Optional Clarification；Assumption change；Portfolio 搜索/筛选；Welcome Back；最小 Proposal complexity/risk；受限 API/TUI draft inspect。 | 提升可用性，不改变 Control Plane。 |
| **NICE TO HAVE** | Examples/templates、轻量命令导航、结果摘要、Factory capability status。 | 不阻塞入口闭环。 |
| **明确不做** | 任意 DAG/拖拽图编辑、运行中 Plan Mutation UI、全局控制 Command Bar、多人协作、跨 Production 编排、模型/Worker 手工挑选器。 | 避免让 P6 无限膨胀。 |

P6 当前优先级仍是 Autonomous Production Trial 的权威闭环、真实 Worker/Verifier、Evidence、故障恢复和 Gate。Entry 是其未来的 user-facing entry layer，不能阻塞或篡改 Trial。若 Trial 的 T01 Software Request / Plan Authority 尚未完成，Factory Home 可先设计/实现为 Draft/Portfolio read layer，Production Creation approval 的实际执行必须等该正式语义入口就绪。

## 30. P7+ Scope

P7+ 才考虑：完整 Master Plan 富编辑器、Plan Mutation/Impact Analysis 的入口 UI、任意 DAG/拖拽依赖编辑、运行中节点分解、Command Bar 的高风险控制、多人协作/评论/审批、跨 Production workforce/资源编排、advanced semantic code impact analysis、模板市场、组织/工作区层级和移动端专用体验。它们都必须建立在 P6 的 Snapshot、语义命令、Evidence、版本、策略和恢复证据之上。

## 31. Implementation Architecture

### 31.1 模块边界

未来实现建议分成四个薄层：`Entry Draft & Revision`、`Entry Analysis/Proposal`、`Plan Approval to Project Bridge`、`Portfolio Projection`。其中 Draft/Analysis/Proposal 都不能写 Execution；Bridge 是唯一可以在有效 Plan approval 后调用现有 Project 创建/Plan materialization 的地方；Portfolio 只读聚合 Project/Task/Gate/Execution/Verification/Evidence。这样入口不会成为影子 Control Plane。

### 31.2 前端组件规格

| 模块 | 责任 | 输入 | 输出/边界 |
| --- | --- | --- | --- |
| `FactoryHome` | 组合 Hero、Action Required、Continue、Outcomes。 | Portfolio snapshot。 | 导航/创建 intent，不持有权威运行状态。 |
| `IdeaComposer` | 输入、附件、最小约束、草稿恢复。 | Draft state。 | `submitIdea` 语义请求。 |
| `UnderstandingReview` | 显示目标/来源/未知项/风险。 | Understanding revision。 | modify/continue/clarify action。 |
| `ClarificationPanel` | 提供必要/可选问题。 | Question schema。 | 版本化 answer。 |
| `AssumptionList` | 显示默认/理由/可逆性。 | Assumption records。 | accept/change request。 |
| `ProposalReview` | 快速确认范围、阶段、复杂度。 | Proposal revision。 | generate plan/revise action。 |
| `PlanApprovalBridge` | 展示 Plan Review，提交审批。 | Plan revision/hash。 | authority command receipt，跳转 Production。 |
| `ProductionPortfolio` | 搜索、筛选、状态卡片。 | Server projection。 | open production/gate。 |
| `ResumeBanner` | Welcome Back 摘要。 | Recent authoritative activity。 | open/review navigation。 |

所有模块以服务端 Snapshot 为输入，以命名 command 为输出；loading、error、stale、permission 和 version conflict 是一等状态。路由建议为 `/home`、`/new`、`/drafts/{id}`、`/productions`、`/productions/{id}`、`/gates`，不引入没有现实边界的 Workspace/Organization 域。

### 31.3 数据与版本策略

Entry Draft、Idea、Understanding、Clarification、Assumption、Proposal 和 Plan 都必须版本化并带 actor/time/reason/content hash（适用时）。客户端每次写入携带 expected version；409 显示差异并让用户选择重载/重新应用，而不是最后写入者获胜。所有系统生成内容标记生成版本和来源；用户输入与系统默认严格区分。Draft/Proposal 可保留期限应继承后续 retention policy；secret 不应进入 Idea/Proposal/日志/事件正文。

### 31.4 页面规格与页面状态矩阵

以下页面规格将“页面看起来是什么”转换为可实现的状态、数据和事件边界。所有页面都遵循同一规则：读取服务端权威 Snapshot/Projection；用户动作只产生 Draft 或语义命令；Loading、Error、Empty、Stale 均是一等状态。

| 页面 | Purpose / User / Entry | Exit / Primary / Secondary | Data / State / Events | Error / Empty / Loading |
| --- | --- | --- | --- | --- |
| Factory Home | 让 Owner 首次创建或恢复 Production；从 `/home`、登录后、导航进入。 | 主动作为 Start Planning；次要为 Open Production、Review Gate、筛选。退出到 Draft、Production 或 Gate。 | Portfolio Snapshot、Factory status、Gate summaries；状态为 ready/degraded/stale；消费 portfolio/gate/projection 事件。 | 无 Production 显示 Idea Hero 与示例；加载 skeleton；断线显示 as-of 与 refresh。 |
| Idea Entry | 创建最小 Production Draft；由 Hero、New Production 或创建 intent 进入。 | 主动作为 Start Planning；次要为附件、保存、取消。退出 Understanding/Draft。 | Idea text、可选 assets/constraints、draft version；事件为 draft/idea revision submitted。 | 空输入禁用提交；附件/网络失败保留输入并给 retry；首次无历史是正常空状态。 |
| Idea Understanding | 让用户校准系统理解；由 Idea 提交/恢复 Draft 进入。 | 主动作为 Continue to Proposal；次要为 Modify、Answer、Ask Why。退出 Clarification/Proposal/Draft。 | Understanding revision、来源、未知项、风险、assumptions；状态 generating/ready/superseded。 | 生成失败保留 Idea，提供 retry/edit；loading 显示输入快照和可离开提示。 |
| Smart Clarification | 收集真正阻断的意图；由 Understanding 的 required question 进入。 | 主动作为 Submit answer/Use recommendation；次要为 back、save. 退出 Understanding/Proposal。 | Question schema、answer、draft version；事件 clarification requested/answered。 | 答案不合法显示字段级错误；无 required question 不显示页面而直接继续。 |
| Production Proposal | 快速确认要做什么及为何值得做；由 Understanding 完成进入。 | 主动作为 Generate Master Plan；次要为 Modify Idea/Assumption、Revise、Reject。退出 Plan/Draft。 | Proposal revision、scope、outcome、phases、risk、complexity；状态 ready/revising/superseded。 | 无法生成时显示保留的 Understanding 与 retry；loading 不显示任何执行进度。 |
| Master Plan Review | 审阅可批准的完整计划；由 Proposal/Draft Resume 进入。 | 主动作为 Approve Master Plan；次要为 edit/revise/reject/decompose。退出 Production Created 或 Proposal。 | Plan revision/hash、nodes/edges、verification/delivery、approval status；事件 plan created/revised/approved。 | DAG/版本/权限错误可解释；无计划回 Proposal；loading 显示计划输入与进度。 |
| Production Created | 确认授权已被受理，衔接到真实运行；由 approved receipt 进入。 | 主动作为 Open Live Production；次要为 View Plan/Overview。退出 Production Overview/Live。 | production/project ID、receipt、materialization status；状态 accepted/preparing/failed. | 创建失败显示 rejection/current revision，不显示半成品成功；loading 说明“preparing controlled execution”。 |
| Production Overview | 概览一个 Production 的状态、Plan 与结果；由 Portfolio/URL/Resume 进入。 | 主动作为 Open Live Production；次要为 Plan、Workers、Evidence、Activity。退出各子页/Home。 | Production Snapshot、phase、summary、links；状态 active/waiting/paused/completed/stale。 | 404/无权限明确说明；loading skeleton；无任务时解释尚未 materialize。 |
| Resume Production | 帮助 Returning User 回到最近上下文；由 Welcome Back 或 Paused card 进入。 | 主动作为 Open Production/Review Resume；次要为 inspect Gate/Plan。退出 Live Production/Overview。 | Recent activity、project resume context、Gate summary；状态 resumable/waiting/uncertain. | resume context 无效时不能自动继续，转 Gate/Recovery 解释；无可恢复生产时隐藏此区。 |
| Waiting Gate | 审阅具体高风险操作；由 Action Required/Gates/Production 进入。 | 主动作为 Review、Approve/Reject（通过既有 Gate 流）；次要为 Explain/Evidence。退出 Production/Home。 | Gate request、risk、reason、evidence refs、expiry；状态 requested/answered/applied/expired。 | 过期显示不可批准与重新请求路径；loading 保留安全摘要；无 Gate 时显示空收件箱。 |
| Production List | 搜索、筛选和打开 Portfolio；由 Produ​ctions 导航进入。 | 主动作为 Open Production；次要为 search/filter/sort. 退出 Overview/Live。 | Paginated portfolio cards、cursor、filter；状态 loading/ready/no-results/stale。 | 无筛选结果显示 clear filter；无任何 Production 回 Hero；分页失败保留已有数据。 |

| Page | State | User Action | System Response | UI Response |
| --- | --- | --- | --- | --- |
| Factory Home | No Productions | Start Planning | 创建 Entry Draft。 | 转 Idea Entry/Understanding；Hero 不消失。 |
| Factory Home | Waiting Gate | Review | 查询 Gate + Evidence/decision refs。 | 打开 Gate Detail，显示风险与状态。 |
| Factory Home | Stale/Disconnected | Refresh | 重新获取 Snapshot/从 cursor 对账。 | 显示最后更新时间，恢复后移除 stale banner。 |
| Idea Entry | Valid Idea | Start Planning | 保存 revision，排队 Understanding。 | 显示 analyzing，可安全离开。 |
| Understanding | Clarification Required | Answer | 写版本化 answer，重新判断缺口。 | 显示下一问题或 Proposal ready。 |
| Proposal | Ready | Generate Master Plan | 请求 Plan revision。 | 转 Plan generating，不创建执行。 |
| Plan Review | Awaiting Approval | Approve | 校验 actor/hash/version，建立 authority bridge。 | 显示 accepted/preparing，成功后进入 Production Created。 |
| Plan Review | Stale Version | Approve | 拒绝旧版本，返回 current revision/diff。 | 显示冲突，要求 review latest plan。 |
| Production List | RUNNING | Open | 读取 Production Snapshot。 | 跳转 Live Production，不复制控制界面。 |
| Resume | PAUSED | Review Resume | 查询 resume context/guard/Gate。 | 显示 preview；不能直接强制运行。 |
| Waiting Gate | Requested | Approve | 提交 Gate decision，authority apply 后发事件。 | 显示 applying，最终依 Projection 更新。 |
| Production Overview | Browser reopened | Open | 读当前权威 Snapshot。 | 展示实际运行/恢复/等待状态，不使用本地旧状态。 |

## 32. Acceptance Criteria

| ID | 验收标准 |
| --- | --- |
| AC-001 | 用户进入 Proteus 后可从 Factory Home 的单一核心入口开始创建 Production Draft。 |
| AC-002 | 用户无需填写语言、框架、数据库、Worker、模型等大表单即可开始。 |
| AC-003 | 用户只输入自然语言 Idea 也可进入 Understanding。 |
| AC-004 | 在真实执行前，系统会以可审阅方式展示对 Idea 的理解。 |
| AC-005 | 系统能识别 Required Clarification，且只询问会改变关键方案的问题。 |
| AC-006 | 系统展示 Assumptions 的默认、理由、风险和来源。 |
| AC-007 | 用户可接受或修改 Assumption；变更留下可追踪 revision/decision。 |
| AC-008 | 用户可审阅并修订 Production Proposal。 |
| AC-009 | 用户可审阅完整 Master Plan。 |
| AC-010 | 只有用户明确批准有效 Plan 后才可创建 Production/进入执行链。 |
| AC-011 | Factory Home 可显示 Running Productions 和当前阶段/最后权威更新时间。 |
| AC-012 | 用户可直接重新进入正在运行/暂停/等待的 Production。 |
| AC-013 | 首页显著显示 Waiting Human Gates，并链接现有审批流。 |
| AC-014 | 所有入口写操作经 semantic command、actor、reason、idempotency、expected version 和权限控制。 |
| AC-015 | Entry 不创建第二套 Execution/Scheduler/Task authority。 |
| AC-016 | Factory Home（Portfolio/entry）与 Live Production（control center）职责清晰且不重复。 |
| AC-017 | Production 状态来自 authoritative snapshot/projection，断线时显式陈旧。 |
| AC-018 | 浏览器关闭不丢失已提交 Draft 或运行中的 Production。 |
| AC-019 | 重新打开后用户能恢复 Draft/Production context，无需重新输入 Idea。 |
| AC-020 | 页面、状态、事件、API、错误与空/加载状态规格足以直接指导后续实现和测试。 |

## 33. Open Questions

| 问题 | 需要的产品决定 | 推荐默认 |
| --- | --- | --- |
| Draft 的保留期限与可见性 | Draft 是私有、可共享还是可交接？保存多久？ | P6 默认 Owner 私有，按统一 retention policy。 |
| Proposal 是否需要显式 Accept | 是否可直接从 Understanding 生成 Plan？ | 保留 Proposal 作为轻量质量门；允许低风险模板合并显示，但保留 revision。 |
| Plan approval 角色 | Owner 是否可同时是 Approver？ | P6 可允许；高风险/生产动作仍走 Gate/RBAC。 |
| Assumption 默认策略 | 哪些技术假设可自动给出？ | 仅可逆、低风险且与既有基线兼容的默认。 |
| 生成失败的成本/重试 | 是否要显示成本或 retry budget？ | P6 显示状态和安全 retry；成本策略后续由 resource/policy 统一。 |
| Home 实时性 | P6 是否用 SSE 还是轮询？ | 先依 P6 Read Model/事件能力；无 SSE 时不伪装实时。 |
| Entry 与 Trial 的上线顺序 | 是否允许先发布只读 Portfolio/草稿体验？ | 是；Approval bridge 必须等待正式 Software Request/Plan Authority。 |

## 34. Final Recommendation

1. **Proteus 首页到底是什么？** 它是 Factory Home：一个以 Production Creation 为主、以 Portfolio/Action Required/Resume 为辅的工厂入口。
2. **第一次打开看见什么？** 看见 `What do you want to build?`、最小 Idea 输入、需要处理的 Gate、可继续的 Production 和最近结果，而不是聊天记录。
3. **用户输入 Idea 还是 Task？为什么？** 输入 Idea；因为用户委托的是产品目标和交付责任，Task 是获批 Plan 后由 Control Plane 物化的执行单元。
4. **为什么 Production 是核心对象？** 它跨越 Idea、Plan、Worker、验证、证据和交付，符合用户的长期心智；后端仍以 Project 权威聚合实现。
5. **Idea 如何变成 Production？** Idea → Understanding → Clarification/Assumption → Proposal → Master Plan → explicit Approval → Project/Production Authority → Live Production。
6. **Proposal 与 Master Plan 的区别？** Proposal 是快速确认的产品生产陈述；Master Plan 是可编辑、版本化、可批准并可物化的完整蓝图。
7. **何时询问用户？何时系统决定？** 只有关键意图/风险没有安全默认值时询问；低风险、可逆、可解释的技术选择显示为可改 Assumption。
8. **Factory Home 与 Live Production 的区别？** Home 管理入口、Portfolio、Gate 和恢复；Live Production 管理单个 Production 的工作流、Worker、验证、证据和干预。
9. **与 Manus 的入口差异？** Manus 的 Plan Mode 以 Task/计划审阅降低一次任务试错；Proteus 的入口以 Production Creation 把 Idea 纳入可验证、可恢复、可审计的软件工厂，且计划批准连接 Authority/Workflow/Delivery。[3] [4]
10. **P6 应实现到哪一步？** 先完成 Entry MVP 到明确 Plan Approval、Portfolio/Gate/Resume 和 Live Production 导航；执行仍由正在进行的 P6 Trial 权威闭环承担。
11. **是否存在与现有设计冲突？** 未发现本质冲突。潜在命名歧义是用户概念 `Production` 与后端 `Project`：推荐保持“Production 是产品别名、Project 是权威聚合”，而非新增平行状态机。
12. **是否建议下一步进入实现？** 建议，但仅在 P6 Trial 的 Software Request/Plan Authority/Read Model 契约明确后，以 Draft/Portfolio read layer → Approval Bridge → Live navigation 的顺序增量实现；不得以 Entry UI 替代或打断 Trial。

## References

[1]: [`docs/P6_MINIMUM_IMPLEMENTATION_ROADMAP.md`](P6_MINIMUM_IMPLEMENTATION_ROADMAP.md)
[2]: [`docs/PROTEUS_LIVE_PRODUCTION_UX_V1.md`](PROTEUS_LIVE_PRODUCTION_UX_V1.md)
[3]: [Manus — Introducing Plan Mode: A New Way to Work with Manus](https://manus.im/blog/manus-plan-mode)
[4]: [Manus Open API — Task Lifecycle](https://open.manus.im/docs/v2/task-lifecycle)
[5]: [Proteus repository — architecture and P0–P5 documentation](https://github.com/yanzhao77/Proteus)
