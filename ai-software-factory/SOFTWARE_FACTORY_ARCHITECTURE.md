# AI Software Factory — 架构设计（SOFTWARE_FACTORY_ARCHITECTURE.md）

> 基于 `RUNTIME_CAPABILITY_MAP.md` 的实测能力设计。
> 原则：不修改 Harness Core、不修改官方 shipped preset、优先 Plugin Composition、先 Inspect 再实现、小步验证。
> 本架构所有"机制"均映射到已实测存在的 DSH/Cordis 原语；所有"需自建"部分都有明确构建路径。

---

## 1. 总览

Software Factory 不是新的 Agent Runtime，而是**运行在 DSH 之上的一个 Agent 组织与生产系统**：

```
┌─────────────────────────── DSH / Cordis Runtime ───────────────────────────┐
│  Host Plane：tools/skills/subagents/workflow/storageDomain/approval/…      │
│  Agent Plane：software-factory preset（persona + tools + skills + prompt） │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    │  Factory Manager（一个 Agent，运行 software-factory preset）
        ┌───────────────────────────┼───────────────────────────────────────────┐
        ↓                           ↓                                           ↓
  Requirement & Planning      Dispatch（workflow + subagent）              Monitor & Recover
  （artifacts + state machine）  （角色 Agent = continuable subagent）     （events + goals + retry）
        └───────────────────────────┼───────────────────────────────────────────┘
                                    ↓
                         Software Production（每个项目）
        ┌───────────────┬───────────────┬───────────────┬───────────────┐
        ↓               ↓               ↓               ↓               ↓
   Product Dept    Engineering Dept   QA Dept         Release        Human-in-loop
   (PM/BA/UX/UI)   (FE/BE/AI/DB/DevOps)(Test/Security/Review)  (build/deploy)  (approve/pause/redirect)
                                    ↓
                              Delivery（可运行项目 + 全套产物）
```

### 1.1 两个平面如何分工（严格遵循 Cordis 规则）

| 平面 | 拥有 | Factory 中的对应物 |
|---|---|---|
| **Host Plane**（已有，不改动） | 注册表、沙箱/审批栈、持久化、模型路由、subagent 注册表与后端 | `storageDomain`、`workspaceRegistry`、`jobs`、`approval`、`tools` 注册表、`subagents` 注册表 |
| **Agent Plane**（新建） | 每个 preset：persona、工具行、prompt sections、技能目录、隔离 realm 服务 | `software-factory` preset（Factory Manager）+ 角色预设（后续按需） |

规则（实测）：
- preset 中的服务行必须包在带 `isolate` 的 group 里。
- 不向 preset 添加 `tool-subagent-report`（host-plane 专属）。
- 子代理通过 `composeFrom` 继承父 preset 组成 → **角色子代理天然获得 Factory Manager 的整套工具**（bash/fs/subagent/workflow…），Factory Manager 无需为每个角色另造工具栈，只需在委派 prompt 中声明角色 Contract。

### 1.2 决策：为什么 Factory Manager 是"一个 preset + 一个 Agent"而不是"一堆静态 Agent"

- DSH 的 subagent 机制是**动态创建**的：`subagent`（spawn，continuable）按需起子代理，持久会话可续跑、可打断。
- 规格书要求"根据项目需求动态决定需要哪些 Agent"——continuable subagent 天然满足。
- 因此：**角色 Agent = 由 Factory Manager 动态 spawn 的 continuable 子代理**，其"角色"由委派 prompt + 可选的子 persona/toolFilter（provider capability：`persona`、`toolFilter`、`outputSchema`）决定，而非静态进程。
- 角色 Contract（第 5 节）以文件形式沉淀在项目 `artifacts/contracts/`，每次委派时注入子代理 prompt。

---

## 2. 项目模型（Artifact-first + 状态机）

### 2.1 项目结构（规格书第 13 节，映射到 session workspace）

```
<factory-root>/                        # = 本 session workspace 下的工厂根（如 ai-software-factory/）
└── projects/
    └── <project-id>/                  # 每个项目一个目录（workspaceRegistry.create 登记）
        ├── project.json               # 项目状态机 + 元数据（storageDomain 同源镜像）
        ├── artifacts/                 # 所有阶段产物（markdown/yaml/sql/spec…）
        │   ├── requirements.md
        │   ├── product-spec.md
        │   ├── user-stories.yaml
        │   ├── architecture.md
        │   ├── api-spec.yaml
        │   ├── database-schema.sql
        │   ├── design-system.json
        │   ├── ui-spec.json
        │   ├── implementation-plan.md
        │   ├── test-plan.md
        │   ├── test-cases.yaml
        │   ├── security-report.md
        │   ├── build-report.md
        │   ├── deployment-manifest.yaml
        │   └── release-notes.md
        ├── contracts/                 # 角色契约 + 质量门槛定义（版本化）
        ├── tasks/                     # 任务表（DAG 的文件表示）
        │   └── <task-id>.yaml         # 每任务：状态/依赖/负责角色/产物/验收
        ├── workspace/                 # 被生产软件的源码树（git 仓库）
        ├── reports/                   # 阶段报告、验收矩阵、证据
        ├── logs/                      # 每任务的运行日志、工具调用摘要
        └── memory/                    # 决策记录 ADR、需求变更记录、失败记录
```

> **为什么文件是权威、storageDomain 是镜像**：文件可被任何工具（git、diff、review）消费，且随项目目录可备份；storageDomain 提供结构化查询与事件。二者以 `project.json` 的 revision 对齐。**跨进程恢复以文件为准**（storageDomain 单进程限制，见 Capability Map §Risks-6）。

### 2.2 项目状态机（规格书第 8 节）

状态（持久于 `project.json` + storageDomain `project` domain）：

```
PROJECT_CREATED → REQUIREMENT_ANALYSIS → REQUIREMENT_CLARIFICATION
  → REQUIREMENT_APPROVED → PRODUCT_DESIGN → UX_DESIGN → ARCHITECTURE_DESIGN
  → TECH_DESIGN_APPROVED → IMPLEMENTATION_PLANNING → IMPLEMENTATION
  → INTEGRATION → QA → SECURITY_AUDIT → ACCEPTANCE → RELEASE → DELIVERED
```

每个状态的运行时细分状态（`status` 字段）：

```
RUNNING | PAUSED | FAILED | RETRYING | BLOCKED | WAITING_APPROVAL | COMPLETED | CANCELLED
```

- 迁移规则：每步迁移 = 一个函数（Factory Manager 的决策 + 校验），写入 `project.json` 并触发 `domain/changed`。
- **WAITING_APPROVAL**：需要用户审批（`ask_user_question` / `approval`）时进入，得到结果后继续。
- **PAUSED**：用户"暂停"（goal pause / 显式指令）→ 冻结当前阶段；Resume 恢复。
- **FAILED → RETRYING**：质量门槛失败或子代理失败 → 进入恢复流程（第 9 节）。

### 2.3 任务模型（规格书第 6 节，DAG）

```
Project → Epic → Feature → Story → Task → Subtask
```

- 文件表示：`tasks/<task-id>.yaml`，字段：

```yaml
id: t-014
title: 实现用户注册 API
epic: auth
parent: t-008          # 可选
dependsOn: [t-012]     # 前置任务（DAG 边）
role: backend          # 负责角色
status: pending        # pending|ready|running|blocked|failed|done|cancelled
outputs: [backend/app/api/auth.py]
artifacts: [artifacts/api-spec.yaml]
acceptance: ["POST /register 201", "密码 bcrypt", "token 返回"]
attempts: 0
```

- **执行模型**：Factory Manager 每轮从 `ready`（依赖全 done）任务中按 DAG 顺序挑选，派发给角色子代理；**执行本身不是长驻进程**，而是"派发 → 子代理产出 → 校验产物/验收 → 更新任务状态"的循环（由 Goal 自动续轮驱动，见第 8 节）。
- 并行：多个 `ready` 任务可并行派发给多个子代理（workflow `parallel` 或 Manager 自己并发 `subagent`）。

---

## 3. 生产流水线（Workflow 设计）

### 3.1 阶段 DAG（规格书第 9 节）

```
Requirement ──▶ Architecture ──┬──▶ Frontend ──┐
                               ├──▶ Backend  ──┼──▶ Integration ──┬──▶ QA ──┐
                               └──▶ Database ──┘                   ├──▶ Security ──┼──▶ Release
                                                                   └──▶ Performance─┘
```

### 3.2 实现方式：workflow 脚本 = 一次流水线的执行器

每次"跑一个阶段组"就是一次 `workflow` 工具调用（前台 run，脚本内用 `agent()` 并行/串行派子代理）。**脚本不持有状态**：每阶段开始/结束时读写项目文件 + storageDomain。

示例脚本骨架（Phase 4 后落地）：

```js
// run-pipeline.js —— Factory Manager 通过 workflow 工具提交
const project = await readProjectState()           // 从 project.json 读状态
const stage = project.nextStage                    // 下一个阶段
const agents = await planDispatch(stage)           // 读 tasks/ 决定派发计划
const results = await parallel(agents.map(a => () =>
  agent(dispatchPrompt(a), { label: a.role, schema: taskResultSchema })
))
for (const r of results) await recordTaskResult(r) // 写任务状态 + artifacts
return { stage, results: summarize(results) }
```

> 注意（实测限制）：workflow run 无 journaling、进程重启即丢。因此**单次 workflow run 只做"一个阶段的一批任务"**，不要在一个 run 里跑完整项目。长项目 = 多次 run + Goal 续轮 + 每次从 `project.json` 恢复。

### 3.3 备选：Manager 手写编排（MVP 阶段默认）

Phase 1–3 阶段，Factory Manager 直接在会话里"顺序调用子代理 + 校验 + 更新状态"，不必依赖 workflow 脚本。workflow 工具在需要**大规模并行 fan-out**（如一次性生成 10 个独立模块）时使用。

---

## 4. Agent 组织与动态调度

### 4.1 角色清单（规格书第 5 节，按需创建）

| 角色 | 何时创建 | 主要产出 |
|---|---|---|
| Requirement Agent | 总是 | requirements.md、澄清问题 |
| PM / BA | 需求批准后 | product-spec.md、user-stories.yaml |
| UX / UI Designer | 产品设计阶段 | ui-spec.json、design-system.json |
| Solution Architect | 需求稳定后 | architecture.md |
| DB / API Architect | 架构阶段 | database-schema.sql、api-spec.yaml |
| FE / BE / AI / DB Engineer | 实现阶段 | workspace/ 源码、模块任务 |
| QA / Security / Review | 集成后 | test-cases、test-report、security-report |
| DevOps / Release | 发布阶段 | build-report、deployment-manifest、release-notes |

### 4.2 动态调度规则（规格书第 5、6 节）

1. **角色即子代理**：`subagent(dispatchPrompt(role, task), { background: true })` → 得到 durable child id。
2. **筛选**：实现阶段根据 `implementation-plan.md` 中标注的领域（web/mobile/ai/db）决定创建哪些角色；纯 CRUD 不建 AI Engineer。
3. **契约注入**：委派 prompt = 角色 Contract（第 5 节）+ 任务定义 + 相关 artifacts 路径 + 输出要求（`outputSchema` 结构化任务结果）。
4. **并行上限**：默认同时 ≤ 3 个角色子代理（防上下文/成本失控）；可在项目配置调整。
5. **复用与回收**：同角色连续任务复用同一 continuable 子代理（send_message 续投递，子代理保留其会话上下文=角色记忆）；任务完成后视需要 `interrupt_agent`/保留待命。
6. **失败换人**（第 9 节）：同任务重试 N 次失败 → 换新子代理（fresh spawn）→ 再失败 → 拆分任务 → 再失败 → 升级给 Manager 亲自做 → 仍失败 → 用户审批/求助。

### 4.3 子代理权限边界（实测硬约束）

- 子代理 approval policy = `never`：**子代理内不能请求升级沙箱**。因此：
  - 编码/测试/写文件 → 子代理做（sandbox workspace-write 覆盖项目目录）。
  - 需要升级权限的操作（安装系统依赖、启动 Docker、部署、访问凭据）→ **Factory Manager 亲自执行**（Manager 是用户会话中的 Agent，可触发审批）。
  - 安全敏感步骤（secret 读取）→ 只在 Manager 层，且通过 `credentials` 服务 + 审批。

---

## 5. Agent Contract（规格书第 15 节）

每个角色契约沉淀为项目内 `contracts/<role>.yaml`（模板在 `ai-software-factory/templates/`），委派时注入：

```yaml
role: backend
mission: 实现后端 API（FastAPI），遵循 api-spec.yaml 与 database-schema.sql
input:
  - artifacts/api-spec.yaml
  - artifacts/database-schema.sql
  - artifacts/architecture.md#backend
  - tasks/t-014.yaml
output:
  - workspace/backend/**（源码）
  - artifacts/backend-implementation.md（变更说明）
  - 任务状态更新（done + attempts + evidence）
tools: [bash, read, write, edit, glob, grep, job_*]   # 默认全部
constraints:
  - 不修改 api-spec.yaml（如需变更 → 报告 Manager）
  - 不安装未批准的依赖
  - 不在子代理内请求沙箱升级
artifacts: 见 output
qualityCriteria:
  - 通过 workspace 中 pytest 测试（由 QA 角色验证，不自证）
  - 不引入未声明的 schema 变更
failurePolicy: 报告失败原因 + 已完成部分 → Manager 决定 retry/拆分/换人
```

**关键原则**：子代理**不自证成功**。任务"完成"的唯一权威是 Manager 运行的校验（测试/构建/lint/产物检查）——即 Proteus 同款的"Evidence over claims"，但用 DSH 原生工具实现。

---

## 6. Quality Gate（规格书第 10 节）

每个阶段出口一个 Gate；Gate 定义在项目 `contracts/gates.yaml`（类型 + 通过标准），执行由 Manager（或专门的 QA/Review 子代理）完成：

| Gate | 验证手段（DSH 原语） | 失败动作 |
|---|---|---|
| Requirement Coverage | 检查 user-stories.yaml 每项在 implementation-plan.md 有任务 | 补任务 |
| Architecture Consistency | 架构审查子代理（读 architecture.md vs 代码） | 修复架构产物 |
| API Completeness | api-spec.yaml vs 代码路由/方法扫描 | 补实现 |
| Code Quality | lint + 代码 Review 子代理 | 修复 → 重跑 |
| Test | 跑测试套件（bash/jobs），覆盖率统计 | 修复 → 重跑 |
| Security | 依赖扫描 + 安全审查子代理（OWASP 清单） | 修复 → 重跑 |
| Build | 构建命令（bash），产物校验 | 修复 → 重跑 |
| Performance（可选） | 基准/负载脚本 | 优化 → 重跑 |
| Deployment | docker compose up + 健康检查（Manager 层，需审批） | 修复 → 重跑 |

Gate 结果写入 `reports/<stage>-gate.md` + 状态机（FAILED→RETRYING）。

---

## 7. Human-in-the-loop（规格书第 11 节）

| 用户动作 | 机制 |
|---|---|
| 澄清（需求阶段） | `ask_user_question`（带选项） |
| 审批（Gate/危险操作） | `approval`（沙箱升级、部署、凭据）；动态插件运行 |
| 暂停/恢复 | Goal `pause`/`resume`（persist 到会话） + 项目状态 PAUSED |
| 停止/取消 | Goal `clear` / Manager 中断子代理 + 状态 CANCELLED |
| 重试 | Manager 命令 → 状态 RETRYING → 重新派发 |
| 修改/重定向 | 用户输入变更 → **需求变更引擎**（第 8 节） |
| 中途换数据库（示例） | 变更引擎：impact analysis → 受影响 artifacts/tasks → 变更计划 → 用户确认 → 增量执行 |

---

## 8. 需求变更引擎与工厂记忆

### 8.1 需求变更引擎（规格书第 12 节）

- **依赖图**：每个 artifact/task 记录 `dependsOn`/`producedBy`/`consumes` 引用（在 yaml 中显式声明，Manager 解析）。
- 变更流程：

```
User Change（自然语言）
   ↓ 1. 解析为 requirements.md 的 diff
   ↓ 2. Impact Analysis：沿依赖图标记受影响 artifacts/tasks（requirements→spec→arch→api→db→code→tests→deploy）
   ↓ 3. 产出变更计划（受影响节点 + 建议动作 + 预计成本）
   ↓ 4. ask_user_question 确认
   ↓ 5. 增量执行：只重跑受影响子树（状态机回退到相应阶段）
```

- 不需要重新生成整个项目。

### 8.2 工厂记忆（规格书第 21 节）

三层持久化，全部可恢复：

| 层 | 载体 | 内容 | 恢复方式 |
|---|---|---|---|
| 项目记忆 | `<project>/memory/` + `project.json` | 需求、决策(ADR)、架构、artifacts 清单、任务、失败记录、用户修改 | Manager 新会话读 `project.json` + memory/ 即恢复 |
| 会话记忆 | 子代理持久会话（continuable） | 每个角色子代理的完整历史 | `send_message` 唤醒 / cold resume |
| 运行记忆 | `~/.dsh/sessions/` JSONL | Manager 自身会话（含所有工具调用） | DSH 会话恢复机制 |

启动恢复流程（Manager 每次开始）：读 `project.json` → 状态机 → 未完成任务 → 派发续跑。**不从零开始**。

---

## 9. 失败恢复（规格书第 25 节）

```
任务失败
  ↓ 记录失败（attempts++，logs/，失败原因）
  ↓ Retry（同子代理 send_message 重派，≤2 次）
  ↓ Retry with Context Reduction（缩小任务范围/减少引用文件）
  ↓ Switch Agent（fresh spawn 新子代理）
  ↓ Task Decomposition（拆分任务）
  ↓ Escalate（Manager 亲自执行）
  ↓ Human Approval（求助/询问用户）
```

每次失败都写 `memory/failures.md`（原因、处置、教训），供后续项目参考。

---

## 10. 可观察性与事件（规格书第 22、23 节）

- 事件源（全部实测存在，可监听）：
  - `workflow/start|end|phase|log|agent-start|agent-end`
  - `subagent/start|end`
  - `agent/created|status|error|session-start`
  - `session/event`、`domain/changed`、`tools/result`、`goal/changed`
- Factory 自有事件词汇：写入 `project.json` 的 `events[]`（持久）或 storageDomain 的 `projectEvent` domain；事件 = `{ts, type, projectId, taskId?, actor?, data}`。
- Dashboard（未来）：动态插件 Client half 挂 `conversation.input.dock` / `settings.section`，经 `host.call` 读 Manager 提供的 `factory.snapshot` RPC（Host half 从 storageDomain/项目文件聚合）→ 显示项目进度、任务 DAG、最近事件、Gate 状态、构建/部署状态。
- 立即可用：每阶段结束向用户输出结构化报告（reports/），无需 UI。

---

## 11. 成本控制（规格书第 24 节）

- 账本：`<project>/memory/budget.json`（storageDomain `budget` domain 镜像），字段：`projectBudget`、`spent.planning|development|testing|security|release|reserve`、`perAgent`、`tokenUsed`（经 `tokenMeter` 估算）。
- 执行点：每次 workflow/子代理派发前预估（阶段预算 + 子代理数 + 任务规模），执行后回写。
- 超预算：状态 → PAUSED + `ask_user_question`（"继续 / 调预算 / 降级范围"）。
- 上限：单子代理 maxRounds、单任务 attempts、workflow maxTotalAgents、Goal max_goal_rounds。

---

## 12. 安全边界（规格书第 26 节）

| 面 | 策略 |
|---|---|
| 命令执行 | bash 走沙箱（workspace-write）；`rm`/`sudo` 等触发审批或拒绝 |
| 文件访问 | fs-sandbox 限定 workspace；越界一次性升级需审批 |
| Secrets | 凭据只在 `credentials` 服务（provider-managed），Manager 层 + 审批使用；子代理 prompt 中禁止携带 secret |
| 网络 | 子代理无网络（web_search 仅 Manager）；依赖安装走审批 |
| 依赖 | 锁定版本（package-lock/pip freeze），安全扫描 Gate |
| Prompt/工具注入 | 子代理产出视为不可信输入：Manager 校验产物/测试证据后才置 done |
| 工作区隔离 | 每项目独立目录 + git；角色子代理共享项目 workspace（DSH 子代理同进程），危险面收敛在 Manager |
| 沙箱/审批 | 不关闭；子代理 never-approval 由父级兜底 |

---

## 13. 部署抽象（规格书第 27 节）

MVP 只实现接口与 Docker 起步：

```
deployment-manifest.yaml（项目产物）
   ├── build:   docker build / npm build / pip install …（命令化）
   ├── deploy:  docker compose up（Manager 层 + 审批）
   └── env:     dev | prod 配置占位
```

扩展点（Phase 7+）：`BuildProvider / DeployProvider / EnvironmentProvider` 以 contract 文件 + 脚本形式定义；云平台（Railway/Vercel/AWS…）按 provider 实现，不预置。

---

## 14. 多项目与多用户（规格书第 28、29 节）

- **多项目**：每项目 = workspace 注册 + 独立目录 + 独立 `project.json`/memory/artifacts/tasks/budget/git。Manager 同一 preset 处理多项目（每项目独立状态文件），项目间隔离。
- **多用户**：MVP 不实现 SaaS；保留扩展点——`project.json` 的 `owner/team/members[]/roles` 字段占位；未来可在 Host 加 `org/team/project` 域。

---

## 15. 组件清单与归属（谁建、放哪）

| 组件 | 归属平面 | 形态 | 构建阶段 |
|---|---|---|---|
| `software-factory` preset（persona+skills+tools+prompt） | Agent Plane | `~/.dsh/.agent-presets/software-factory/`（复制 standard/cordis 后改） | Phase 1 |
| Factory 技能包（requirements/architecture/frontend/backend/qa/security/…） | Agent Plane | `~/.dsh/.agent-presets/software-factory/skills/<name>/SKILL.md`（或项目级 `.agents/skills`） | Phase 1–4 |
| 工厂模板（项目骨架、契约、gate、artifact 模板） | 文件 | `ai-software-factory/templates/`（workspace 内，git 管理） | Phase 1 |
| 工厂 CLI/脚本（状态机读写、任务调度辅助） | 文件 | `ai-software-factory/scripts/`（bash/node 小工具，Manager 经 bash 调用） | Phase 1–3 |
| Factory Dashboard（可选） | 动态插件（实验）→ preset 正式化 | Host half（`harness.handle` + storageDomain 聚合）+ Client half（Slot） | Phase 4+ |
| 工厂事件/记账服务 | 实验用动态插件；正式化走 preset 私有服务（isolate realm） | — | Phase 3+ |
| 角色子代理 | 运行时（不落盘） | continuable subagent | Phase 1 起 |

**归属规则（复述）**：跨 session 共享、进程级、注册表/持久化 → Host（已存在，只消费）；单 session/单 agent 的工具、persona、技能 → Agent preset；临时实验 → 动态插件；正式能力 → 复制到 preset 目录。

---

## 16. 与现有 Proteus 仓库的关系

- 本 workspace（Proteus）是另一个"自主软件工厂"实现（Hermes：Python + PostgreSQL + React + Control Plane/Worker/Verifier/Evidence）。
- 本架构是 **Harness/Cordis 原生**实现：Agent 由 DSH 管理，状态用文件 + storageDomain，流水线用 workflow + subagent。
- 借鉴（不复制代码）：Evidence-over-claims、Authority-first、Fail-closed、Recovery-as-protocol 的思想已融入第 5/6/9 节（子代理不自证、Gate 独立验证、失败恢复协议）。
- 两个实现可共存；本架构的产物是**任何技术栈的真实软件项目**（Phase 7 验收），与 Proteus 自身代码互不依赖。

---

## 17. 架构决策记录（ADR 摘要）

| # | 决策 | 理由（实测依据） |
|---|---|---|
| A1 | 角色 = continuable subagent，不静态起 Agent | subagent 持久会话 + 动态创建 + 可打断/续跑 |
| A2 | 项目状态权威在文件，storageDomain 为镜像 | workflow 无恢复 + storageDomain 单进程 |
| A3 | 长流程 = 多次 workflow run + Goal 续轮 | workflow 无 journaling/resume |
| A4 | 子代理不自证成功，Manager 独立验证 | Evidence over claims；子代理 approval=never 也要求 Manager 兜底危险操作 |
| A5 | 危险/审批操作只在 Manager 层 | 子代理 approval policy 固定 never（实测） |
| A6 | 正式能力落 preset，实验用动态插件 | 动态插件不跨重启（实测） |
| A7 | 不依赖 agentTeams（catalog-only） | Provider 未安装于本部署（实测）；若需，先选装验证 |
| A8 | preset 从 standard 复制，不修改 shipped | 官方约束（实测文档） |

---

## 18. 验证策略（每阶段验收，对应实现计划）

| 阶段 | 验证动作（DSH 原语） |
|---|---|
| Preset | `agentPresets.list()` 见 `software-factory`；`resolve()` 成功；新会话选它后工具目录正确（Tool.listTools） |
| 技能 | `skills.snapshot()` 含 Factory 技能；`skill(name)` 可加载 |
| 状态机 | 跑一个示例项目到 REQUIREMENT_APPROVED，检查 project.json + storageDomain 一致 |
| 流水线 | 示例 Todo 项目：requirement→arch→impl→test→release 闭环，产物齐全 |
| 角色 | 观察 subagent 事件（start/end）、list_agents 见角色、任务状态迁移正确 |
| Gate | 注入缺陷，确认 Gate FAIL→RETRYING→修复→PASS |
| 变更 | 改需求，确认只重跑受影响任务 |
| 交付 | 项目可 `docker compose up` 真实运行（验收清单见 FACTORY_IMPLEMENTATION_PLAN.md §Phase 7） |
