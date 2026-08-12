# Hermes Autonomous Software Factory

## 自主软件工厂架构设计书 V1.0

**文档版本：** V1.0  
**项目名称：** Hermes Autonomous Software Factory  
**项目简称：** HASF  
**中文名称：** Hermes 自主软件工厂  
**架构定位：** Autonomous Software Engineering Platform  
**核心理念：** Autonomous-First / Human-on-the-Loop / Evidence-Driven  
**目标读者：** 架构师、工程负责人、Agent 平台开发者、软件工厂系统实现者

---

## 1. 项目概述

Hermes Autonomous Software Factory 的目标不是构建一个简单的 AI Coding Agent，也不是把多个 Agent 机械地组织成固定团队。它要构建的是一个面向完整软件生命周期的自主生产系统。

用户只需要提出一个软件项目目标，系统即可自主完成从需求理解、项目分析、可行性研究、架构设计、技术文档、开发计划、代码实现、单元测试、集成测试、代码审查、问题修复、性能测试、安全测试、UI 审查到最终部署展示的完整交付流程。

HASF 的基本判断是：Hermes 本身已经具备 Agent 执行、隔离 Subagent、Skills、Memory、MCP、沙箱和多种运行环境等底层能力。因此 HASF 不应该重造 Hermes，而应该在 Hermes 之上构建更高一层的软件工厂控制系统。

一句话定义：

> HASF 是一个以项目状态机为核心、以动态 Agent 集群为执行能力、以 Evidence 和 Judge 为质量闭环、以 Human Gate 为安全阀的自主软件工程平台。

---

## 2. 系统愿景

HASF 的最终愿景是让软件项目从“人类持续推动”变成“AI 持续推进，人类只在必要节点介入”。

传统 AI Coding Agent 的工作模式通常是：

```text
Human -> Prompt -> Agent -> Code -> Human Review -> More Prompt -> More Code
```

HASF 的目标模式是：

```text
User Goal
  -> Project State Machine
  -> Task Graph
  -> Agent Execution
  -> Artifact
  -> Evidence
  -> Independent Judge
  -> Feedback Loop
  -> Delivery
```

在这个模型中，人类不再充当普通工作流中的反复确认节点，而是承担目标设定、重大决策、授权、资源提供和最终验收等职责。

---

## 3. 最高设计原则

### 3.1 Autonomous First

所有任务默认由 AI 自主完成。系统不应把“等待人类确认”设计成常规步骤，而应尽可能通过状态、证据、策略和自动验证向前推进。

### 3.2 Human-on-the-Loop

人类位于循环之上，而不是循环之中。人类负责目标、方向、授权、资源和高风险决策，不负责日常写代码、跑测试、修 Bug、改配置。

### 3.3 Evidence Driven

系统状态不能由 Agent 的主观陈述推进。每一次完成、失败、回滚、发布都必须尽可能建立在证据之上，例如测试结果、构建日志、运行日志、截图、Benchmark、Review 报告、安全扫描结果和部署验证结果。

### 3.4 Failure Is Feedback

失败不是终点，而是反馈输入。

```text
FAIL -> DIAGNOSE -> FEEDBACK -> FIX -> RETEST -> PASS
```

当无法自主修复时，系统才进入 Human Gate。

### 3.5 Deterministic Control Plane

LLM 负责推理和生成，Control Plane 负责状态、权限、生命周期、预算、策略和审计。不能让 LLM 自己决定项目状态、权限边界、成本预算和生产操作授权。

### 3.6 Context Isolation

不同 Agent 不应共享完整上下文。每个 Worker Agent 只获取完成当前任务所需的 Project Brain、任务输入、相关 Artifact 和约束信息。这样可以降低上下文污染、减少 Token 消耗，并提升评审独立性。

### 3.7 Everything Is Recoverable

每个重要阶段都应产生 State、Artifact、Evidence 和 Checkpoint，从而支持 Retry、Rollback、Resume、Replan、Replay 和 Audit。

### 3.8 Explainable Human Escalation

系统找人时，不能只说“我不会了”。Human Gate 请求必须说明发生了什么、尝试过什么、失败原因是什么、可选方案有哪些、推荐方案是什么、需要用户决定什么。

---

## 4. 总体架构

HASF 分为五层：Human Layer、Interaction Layer、Control Plane、Agent Plane 和 Execution Plane。

```text
┌──────────────────────────────────────────────────────────┐
│                       HUMAN LAYER                        │
│                                                          │
│                           User                           │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│                    INTERACTION LAYER                     │
│                                                          │
│                       Human Gate                         │
│      Approval / Decision / Resource / Intervention       │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│                      CONTROL PLANE                       │
│                                                          │
│  Main Hermes / Project Manager / State Machine           │
│  Task Graph / Policy Engine / Autonomy Engine            │
│  Budget Manager / Evidence Store / Artifact Manager      │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│                       AGENT PLANE                        │
│                                                          │
│  Research / Product / Architecture / Coding / Testing    │
│  Security / UI / Performance / DevOps / Review Agents    │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│                     EXECUTION PLANE                      │
│                                                          │
│  Local Runtime / Docker Sandbox / Remote VM / Browser    │
│  Database Sandbox / Kubernetes / GPU Runtime             │
└──────────────────────────────────────────────────────────┘
```

---

## 5. 核心闭环

HASF 的核心不是“更多 Agent”，而是以下闭环：

```text
Project State
  -> Task
  -> Agent
  -> Execution
  -> Artifact
  -> Evidence
  -> Judge
  -> Feedback
  -> Next State
```

对应系统图：

```text
                   HERMES SOFTWARE FACTORY
                              │
                              ▼
                    ┌─────────────────┐
                    │ PROJECT STATE   │
                    │    MACHINE      │
                    └────────┬────────┘
                             │
                             ▼
                        CURRENT STATE
                             │
                             ▼
                    ┌─────────────────┐
                    │   ORCHESTRATOR  │
                    │   MAIN HERMES   │
                    └────────┬────────┘
                             │
                             ▼
                        SELECT AGENT
                             │
                             ▼
                        EXECUTE TASK
                             │
                             ▼
                    ┌─────────────────┐
                    │    EVIDENCE     │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │      JUDGE      │
                    └────────┬────────┘
                     ┌───────┴────────┐
                     ▼                ▼
                   PASS              FAIL
                     │                │
                     ▼                ▼
              STATE TRANSITION    FEEDBACK BUS
                                      │
                              ┌───────┼───────┐
                              ▼       ▼       ▼
                             FIX   REPLAN  ESCALATE
                              │       │
                              └───┬───┘
                                  ▼
                               EXECUTE
                                  │
                                  └────── LOOP
```

---

## 6. Main Hermes

Main Hermes 是用户入口和项目总协调 Agent，但不是万能 Agent。

Main Hermes 负责：

- 理解用户目标和项目边界。
- 初始化 Project Brain。
- 将目标转换为项目状态机、任务图和阶段目标。
- 根据项目状态选择合适的 Specialist Agent 或 Worker Agent。
- 观察 Evidence、Judge 结果和项目状态。
- 当系统触发 Human Gate 时，向用户发起可解释的请求。

Main Hermes 不负责：

- 独自写完所有代码。
- 独自执行所有测试。
- 独自做所有专家判断。
- 直接管理权限、预算和生产操作授权。
- 用自己的主观判断替代 Evidence 和 Judge。

Main Hermes 的定位更接近 AI Software Factory 的项目总控 Agent。

---

## 7. Project Control Plane

Project Control Plane 是 HASF 的系统内核。它不必是 LLM，本质上应是确定性的项目操作系统。

核心模块包括：

- Project Manager：管理项目元数据、目标、阶段、里程碑和交付物。
- State Machine：管理项目生命周期和合法状态迁移。
- Task Graph：将计划拆解为可执行 DAG。
- Dependency Graph：管理任务、模块、Artifact、环境之间的依赖。
- Policy Engine：判断动作是否被允许。
- Autonomy Engine：判断是否继续自主恢复，或升级到 Human Gate。
- Budget Manager：管理 Token、时间、成本、重试、Agent 和资源预算。
- Evidence Manager：收集和索引测试、日志、截图、报告、扫描结果。
- Artifact Manager：管理文档、代码、构建物、测试报告、部署包。
- Checkpoint Manager：支持恢复、回滚、重试和审计。
- Audit Manager：记录关键动作、决策、授权和状态迁移。

---

## 8. Project Brain

每个项目都应拥有自己的 Project Brain。它是项目客观事实来源，而不是某个 Agent 的聊天记忆。

推荐目录结构：

```text
project-root/
├── .hermes/
│   ├── project.yaml
│   ├── requirements/
│   ├── feasibility/
│   ├── architecture/
│   ├── design/
│   ├── plans/
│   ├── tasks/
│   ├── decisions/
│   ├── tests/
│   ├── reviews/
│   ├── evidence/
│   ├── artifacts/
│   ├── checkpoints/
│   └── release/
├── source/
├── tests/
└── deployment/
```

Project Brain 中应保存：

- 用户目标和业务约束。
- PRD、架构设计、技术设计、API 规范、数据库设计、UI 规范。
- Development Plan、Task Graph、Test Plan、Deployment Plan。
- 决策记录、风险记录、Human Gate 记录。
- 每个阶段的 Artifact 和 Evidence。
- 可恢复 Checkpoint 和审计日志。

Project Brain 的价值在于把“项目事实”与“Agent 个人上下文”分离，使任意 Agent 都能按需读取可靠上下文。

---

## 9. Project State Machine

HASF 的项目生命周期由状态机驱动。

```text
CREATED
   ↓
ANALYZING
   ↓
FEASIBILITY_CHECK
   ↓
REQUIREMENTS_READY
   ↓
ARCHITECTURE_READY
   ↓
PLAN_READY
   ↓
DEVELOPING
   ↓
INTEGRATING
   ↓
SYSTEM_TESTING
   ↓
REVIEWING
   ↓
HARDENING
   ↓
ACCEPTANCE
   ↓
DEPLOYING
   ↓
DELIVERED
```

异常路径：

```text
Any State -> RECOVERING -> Original State
Any State -> RECOVERING -> NEED_HUMAN
Any State -> PAUSED
Any State -> CANCELLED
```

状态机的关键点是：它不是线性瀑布。任何阶段发现上游问题，都可以通过 Feedback Loop 回到 Requirements、Architecture 或 Planning。

---

## 10. 状态定义模板

每个状态必须使用统一模板定义：

```yaml
state: ARCHITECTURE_READY
entry_condition:
  - requirements evidence passed
agent:
  - architecture-hermes
input:
  - prd.md
  - feasibility-report.md
action:
  - design system architecture
  - define module boundaries
  - define runtime and deployment model
evidence:
  - architecture.md
  - architecture-review.md
judge:
  - architecture-judge
pass_transition: PLAN_READY
fail_transition: RECOVERING
retry_policy:
  max_retry: 2
  allow_replan: true
exit_condition:
  - architecture judge result is PASS
```

---

## 11. V1.0 状态表

| State | Entry Condition | Main Agent | Output Artifact | Evidence | PASS Transition | FAIL Transition |
| --- | --- | --- | --- | --- | --- | --- |
| CREATED | User goal received | Main Hermes | project.yaml | project initialized | ANALYZING | NEED_HUMAN |
| ANALYZING | Project exists | Research / Product Agent | project-analysis.md | analysis review | FEASIBILITY_CHECK | RECOVERING |
| FEASIBILITY_CHECK | Analysis ready | Feasibility Board | feasibility-report.md | feasibility judge | REQUIREMENTS_READY | RECOVERING / NEED_HUMAN |
| REQUIREMENTS_READY | Feasibility pass or accepted warning | Product Agent | prd.md | requirement review | ARCHITECTURE_READY | RECOVERING |
| ARCHITECTURE_READY | PRD approved by judge | Architecture Agent | architecture.md | architecture review | PLAN_READY | RECOVERING |
| PLAN_READY | Architecture pass | Planning Agent | task-graph.yaml | plan review | DEVELOPING | RECOVERING |
| DEVELOPING | Ready tasks exist | Coding Agents | source code / tests | unit tests / static analysis | INTEGRATING | RECOVERING |
| INTEGRATING | Module tasks complete | Integration Agent | integrated build | integration test | SYSTEM_TESTING | RECOVERING |
| SYSTEM_TESTING | Integrated build ready | QA Agents | test reports | functional / E2E / UI / performance evidence | REVIEWING | RECOVERING |
| REVIEWING | System tests pass | Review Agents | review reports | independent review result | HARDENING | RECOVERING |
| HARDENING | Review pass or warnings accepted | Security / Performance / DevOps Agents | hardening changes | regression evidence | ACCEPTANCE | RECOVERING |
| ACCEPTANCE | Release candidate ready | Acceptance Judge | acceptance-report.md | acceptance checklist | DEPLOYING | NEED_HUMAN / RECOVERING |
| DEPLOYING | Acceptance pass | DevOps Agent | deployment package | smoke test / deployment logs | DELIVERED | RECOVERING |
| DELIVERED | Deployment pass | Main Hermes | release notes / demo link | final evidence bundle | Closed | RECOVERING |

---

## 12. Task Graph

项目计划不能只是线性任务列表，而应该是 DAG。

```text
                Requirements
                     │
             ┌───────┴───────┐
             ▼               ▼
       Architecture       UX Design
             │               │
             └───────┬───────┘
                     ▼
                  Backend
                     │
             ┌───────┴───────┐
             ▼               ▼
          Frontend          API
             │               │
             └───────┬───────┘
                     ▼
               Integration
                     │
                     ▼
                   Test
```

任务定义示例：

```yaml
task:
  id: TASK-004
  title: JWT 登录
  goal: 实现用户登录并签发 JWT
  dependencies:
    - TASK-003
  assigned_capability:
    - backend
    - security
  acceptance_criteria:
    - 正确账号密码可以登录
    - 错误密码会被拒绝
    - token 过期逻辑正确
    - token issuer 和 audience 被校验
  test_command:
    - ./mvnw test
  evidence_required:
    - unit-test-report.xml
    - auth-integration-test.json
    - security-review.md
  status: READY
```

Task Graph 允许 HASF 并行调度 Agent，同时保留依赖约束和回滚路径。

---

## 13. Agent Cluster

HASF 不采用固定组织结构，而采用 Capability-based Agent Architecture。

可用能力包括：

- Research Agent
- Product Agent
- Architecture Agent
- Backend Agent
- Frontend Agent
- Database Agent
- AI / ML Agent
- Coding Agent
- Testing Agent
- Security Agent
- UI / UX Agent
- Performance Agent
- DevOps Agent
- Review Agent
- Judge Agent

Agent Team 是动态生成的。普通 CRUD 项目可能只需要 Architecture、Coding、Testing 和 Review；AI 视频平台可能需要 Product、AI Research、Backend、Frontend、GPU、Performance、Security、Testing 和 DevOps。

关键原则：需要什么能力，就调用什么 Agent；不为了组织完整而创建无效角色。

---

## 14. Agent 类型

### 14.1 Main Agent

Main Hermes 负责项目协调、状态观察和 Human Gate 沟通。

### 14.2 Specialist Agent

Specialist Agent 负责某一类专业任务，例如架构、安全、性能、数据库、UI、DevOps。

### 14.3 Worker Agent

Worker Agent 执行具体任务，例如实现某个 API、修复某个 Bug、编写某组测试。

### 14.4 Judge Agent

Judge Agent 独立评估 Artifact 和 Evidence，不应与 Worker Agent 是同一个上下文。

### 14.5 Reviewer Agent

Reviewer Agent 提供专家审查结论，例如 Security Review、Architecture Review、Performance Review、Maintainability Review 和 UI Review。

---

## 15. Autonomy Engine

Autonomy Engine 负责回答：这个问题 AI 应该继续自己解决，还是应该找人？

自主恢复分为六级：

```text
L0 Self Repair
  -> L1 Strategy Switch
  -> L2 Agent Switch
  -> L3 Expert Collaboration
  -> L4 Replan
  -> L5 Human Gate
```

### L0 Self Repair

当前 Agent 根据失败日志直接修复并重测。

```text
Build FAIL -> Analyze -> Fix -> Test
```

### L1 Strategy Switch

当前策略失败后切换技术或实现路径。

```text
Strategy A FAIL -> Strategy B FAIL -> Strategy C
```

### L2 Agent Switch

当前 Agent 无法解决时，切换更匹配或更强的 Agent。

```text
Coding Agent -> Senior Coding Agent
Backend Agent -> Database Agent
```

### L3 Expert Collaboration

复杂问题由多个专家 Agent 并行分析，再由 Judge 汇总证据并形成共识。

### L4 Replan

如果失败来自计划或架构错误，而不是局部代码错误，则触发重新规划。

### L5 Human Gate

当自主预算耗尽、权限边界触发、业务决策不可自动化或外部资源缺失时，进入 Human Gate。

---

## 16. Autonomy Budget

为了防止无限循环，每个项目、阶段和任务都必须有自主预算。

预算维度包括：

- Token Budget
- Time Budget
- Cost Budget
- Retry Budget
- Agent Budget
- Model Budget
- Resource Budget

示例：

```yaml
task:
  max_runtime: 2h
  max_cost: 10
  max_tokens: 300000

autonomy:
  max_retry: 5
  max_strategy_switch: 3
  max_agent_switch: 2
  max_replan: 2
```

预算耗尽不代表项目失败，而是触发更高层级的恢复策略或 Human Gate。

---

## 17. Policy Engine

Policy Engine 负责判断动作是否被允许。Autonomy Engine 判断“是否应该继续尝试”，Policy Engine 判断“是否允许这样做”。

例如，AI 可能知道如何操作生产数据库，但这不代表它有权执行生产数据库变更。

策略判断应综合：

- Capability：Agent 是否具备能力。
- Policy：项目策略是否允许。
- Authorization：用户或组织是否授权。
- Risk：动作是否涉及高风险。
- Environment：动作发生在本地、沙箱、测试环境还是生产环境。

典型高风险操作包括：

- 生产数据库写入或迁移。
- 删除或覆盖用户数据。
- 产生显著成本的云资源创建。
- 外部系统凭证使用。
- 公开发布、推送、部署。
- 安全策略关闭或绕过。

这些操作必须通过 Human Gate 或预先授权策略。

---

## 18. Human Gate

Human Gate 是人类与自主软件工厂之间的控制接口。它不是普通 Agent，也不是日常专家。

Human Gate 处理五类请求：

- DECISION：必须由人类做出的业务或产品决策。
- AUTHORIZATION：需要授权的高风险操作。
- RESOURCE：AI 无法自行获得的资源、账号、密钥、预算。
- CLARIFICATION：需求存在无法自行消解的冲突或模糊点。
- INTERVENTION：系统陷入无法恢复的故障，需要人工介入。

Human Gate 请求模板：

```yaml
human_gate_request:
  type: NEED_DECISION
  summary: 当前数据库架构无法满足 10000 QPS 目标
  evidence:
    - benchmark-report.html
    - database-profile.log
  attempts:
    - Index Optimization
    - Redis Cache
    - Connection Pool
    - Read Replica
  options:
    - id: A
      title: 引入 Kafka
      tradeoff: 架构复杂度提高，但削峰能力更强
    - id: B
      title: 使用 Redis Stream
      tradeoff: 实现较快，适合当前吞吐目标
    - id: C
      title: 降低 QPS 目标
      tradeoff: 成本最低，但产品能力收缩
  recommendation: B
  required_user_action: 请选择 A / B / C
```

---

## 19. Verification Engine

Verification Engine 的原则是：不能相信 Agent 自己说“完成了”。系统必须通过 Evidence 判断是否完成。

验证类型包括：

- Unit Test
- Integration Test
- E2E Test
- API Test
- Security Test
- Performance Test
- Stress Test
- Chaos Test
- UI Test
- Accessibility Test
- Build Verification
- Deployment Verification
- Smoke Test

每次验证都应产生结构化结果：

```json
{
  "task": "TASK-102",
  "result": "PASS",
  "evidence": [
    "pytest-report.xml",
    "integration-test.json",
    "coverage.html",
    "docker-build.log"
  ]
}
```

---

## 20. UI Verification

UI 验证必须是视觉验证，而不是只检查代码。

推荐流程：

```text
Start Frontend
  -> Browser Runtime
  -> Screenshot
  -> UI Judge
  -> Design Rule Check
  -> PASS / FAIL
```

检查维度包括：

- Layout
- Spacing
- Font
- Color
- Component State
- Responsive Behavior
- Interaction
- Animation
- Image Rendering
- Icon Rendering
- Accessibility

失败示例：

```yaml
ui_review:
  result: FAIL
  finding:
    component: Header
    expected_height: 72px
    actual_height: 64px
  action: create_frontend_fix_task
```

---

## 21. Performance Verification

Performance Agent 负责根据 API 规范、部署配置和目标流量生成压测计划，并运行 k6、JMeter、Locust、Gatling 等工具。

示例：

```yaml
performance_target:
  endpoint: /api/jobs
  qps: 10000
  p95_latency: 200ms

actual:
  qps: 8200
  p95_latency: 310ms

result: FAIL
```

失败后进入反馈链路：

```text
Performance Evidence
  -> Performance Agent
  -> Architecture Agent
  -> Coding Agent
  -> Retest
```

---

## 22. Security Verification

Security Verification 包括：

- SAST
- Dependency Scan
- Secret Scan
- Container Scan
- API Security
- Authentication
- Authorization
- Injection
- SSRF
- XSS
- CSRF
- Path Traversal
- Permission Bypass
- Prompt Injection
- Resource Exhaustion

安全问题不应只进入报告，而应自动转化为 Fix Task。

```text
Security FAIL
  -> Security Finding
  -> Create Fix Task
  -> Coding Agent
  -> Security Retest
```

---

## 23. Chaos and Abuse Testing

所谓暴力测试应定义为 Chaos / Abuse Testing，而不是随机乱点。

测试维度包括：

- 非法输入
- 超长输入
- 空参数
- 重复请求
- 并发请求
- 异常 Token
- 过期 Token
- 恶意文件
- 超大文件
- 网络抖动
- 服务重启
- 数据库连接中断
- 第三方 API 失败

目标是验证系统在异常条件下能否保持正确、安全和可恢复。

---

## 24. Sandbox Architecture

所有 Agent 的代码执行都应该进入可控 Runtime。

```text
                     Agent
                       │
                       ▼
                 Sandbox Manager
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
      Local          Docker        Remote VM
        │              │              │
        ▼              ▼              ▼
     Fast Test     Full Runtime    Heavy Task
```

HASF 应将执行环境抽象为统一 Runtime，而不是绑定单一沙箱类型。

推荐 Runtime 类型：

- Local Runtime：快速执行低风险任务。
- Docker Sandbox：隔离构建、测试和完整运行。
- Browser Runtime：前端和 UI 验证。
- Database Sandbox：数据库迁移、数据模型和集成测试。
- Remote VM：长任务、大资源任务或特殊依赖任务。
- GPU Runtime：AI / ML、多媒体、推理和训练任务。

---

## 25. Artifact System

所有重要结果都应该成为 Artifact。

示例结构：

```text
artifacts/
├── requirements/
├── feasibility/
├── architecture/
├── plans/
├── source/
├── tests/
├── reports/
├── screenshots/
├── benchmarks/
├── security/
├── deployment/
└── release/
```

每个 Artifact 应包含元数据：

```yaml
artifact:
  id: ART-202
  type: test-report
  owner: testing-agent
  task: TASK-102
  timestamp: 2026-08-11T00:00:00+08:00
  parent:
    - ART-190
  evidence:
    - EV-310
  status: PASS
```

---

## 26. Evidence System

Evidence 是整个系统可信度的基础。Agent 的“完成了”不能直接推动状态迁移，只有 Evidence PASS 才能推动状态机。

Evidence 类型包括：

- Test Evidence
- Build Evidence
- Runtime Evidence
- Review Evidence
- Security Evidence
- Performance Evidence
- UI Evidence
- Deployment Evidence
- Human Decision Evidence

Evidence 示例：

```json
{
  "id": "EV-310",
  "task": "TASK-102",
  "kind": "integration-test",
  "result": "PASS",
  "produced_by": "testing-agent",
  "artifacts": [
    "integration-test.json",
    "coverage.html"
  ],
  "timestamp": "2026-08-11T00:00:00+08:00"
}
```

---

## 27. Judge System

Judge 不应该与执行任务的 Worker Agent 使用同一个上下文。

错误模型：

```text
Coding Agent -> Code -> Coding Agent says PASS
```

正确模型：

```text
Worker Agent
  -> Artifact
  -> Evidence
  -> Independent Judge
  -> PASS / FAIL / WARNING
```

Judge 的输入应包括：

- Acceptance Criteria
- Git Diff
- Test Result
- Build Log
- Runtime Log
- Coverage Report
- Security Finding
- Screenshot
- Performance Report
- Related Requirement

Judge 的输出应结构化：

```yaml
judge_result:
  result: FAIL
  confidence: high
  blocking_findings:
    - id: BUG-017
      severity: HIGH
      reason: acceptance criterion AC-03 not satisfied
  recommendation: create_fix_task
```

---

## 28. Feedback Engine

Feedback Engine 负责把失败证据转化为下一步行动。

```text
Execute
  -> Verify
  -> Evidence
  -> Judge
  -> FAIL
  -> Diagnosis
  -> Feedback
  -> Fix / Replan / Escalate
  -> Verify
```

Feedback 不只用于修改代码，也可以修改：

- 实现策略
- 任务拆分
- Agent 选择
- 模型选择
- 架构方案
- 测试计划
- 资源配置
- 项目范围

---

## 29. Expert Review

模块或 Release Candidate 完成后，应触发专家审查。

```text
Code
 ├── Architecture Review
 ├── Security Review
 ├── Performance Review
 ├── Maintainability Review
 └── UI Review
      ↓
 Release Judge
```

Review 输出示例：

```yaml
review:
  reviewer: security-agent
  result: FAIL
  findings:
    - id: SEC-003
      severity: HIGH
      file: AuthController.java
      line: 87
      description: JWT issuer is not validated
  recommendation:
    - validate JWT issuer and audience
```

高风险 FAIL 必须创建 Fix Task 并重新验证。

---

## 30. 完整自主开发流程

用户输入：

```text
帮我开发一个 AI 视频平台。
```

系统流程：

```text
Main Hermes
  -> Project Created
  -> Research
  -> Feasibility
  -> Requirements
  -> Architecture
  -> Technical Documentation
  -> Development Plan
  -> Task Graph
  -> Coding
  -> Unit Test
  -> Integration
  -> System Test
  -> Code Review
  -> Security Review
  -> Performance Test
  -> UI Review
  -> E2E Test
  -> Hardening
  -> Docker Build
  -> Sandbox Deploy
  -> Smoke Test
  -> Demo
  -> Delivery
```

任意阶段失败：

```text
FAIL -> Feedback Loop -> Fix / Replan / Escalate -> Retest
```

---

## 31. System Test Army

系统测试阶段才真正需要多个 Agent 大规模并行。

```text
                    RELEASE CANDIDATE
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
       ▼                   ▼                   ▼
 Functional              UI/UX              Security
 Tester                  Tester              Tester
       │                   │                   │
       ▼                   ▼                   ▼
 Performance            Browser             Abuse
 Tester                  Tester              Tester
       │                   │                   │
       └───────────────────┼───────────────────┘
                           ▼
                     Integration Judge
                           │
                           ▼
                       Final Judge
```

测试军团的目标不是证明 Agent 写得对，而是尽可能发现系统不对的地方。

---

## 32. Release Model

Release Agent 负责将通过验证的项目转化为可交付包。

Release 流程：

```text
Source
  -> Build
  -> Unit Test
  -> Integration Test
  -> System Test
  -> Security
  -> Performance
  -> Docker Build
  -> Sandbox Deploy
  -> Smoke Test
  -> PASS
```

Release 目录示例：

```text
release/
├── frontend.tar
├── backend.jar
├── docker-compose.yml
├── docker-images.txt
├── database.sql
├── deployment.md
├── test-report.html
├── security-report.md
├── performance-report.html
└── release-notes.md
```

---

## 33. Demo and Delivery

交付不等于代码能跑。交付应包含可展示、可验证、可复现的 Demo 环境。

```text
FINAL RELEASE
  -> Docker Compose
  -> Frontend / Backend / Database
  -> Demo Environment
  -> Smoke Test
  -> User Acceptance
```

Delivery 输出包括：

- Demo URL 或本地运行入口。
- Release Notes。
- Deployment Guide。
- Operations Manual。
- Test Report。
- Security Report。
- Known Issues。
- Evidence Bundle。

---

## 34. 系统可靠性模型

HASF 的目标不是 100% 不犯错，而是让 100% 的重要错误都有机会被发现、记录、反馈和修复。

可靠性来自：

```text
Agent
  -> Independent Verification
  -> Evidence
  -> Judge
  -> Feedback
  -> Recovery
```

比起单纯提升模型能力，建立独立验证和反馈系统更重要。

---

## 35. V1.0 最小可行系统

V1.0 不需要一次实现全部能力。推荐 MVP 范围：

### 35.1 必须实现

- Project Brain 基础目录和 project.yaml。
- Project State Machine。
- Task Graph。
- Main Hermes Orchestrator。
- Worker Agent 调度接口。
- Evidence 存储。
- Judge 接口。
- Feedback Loop。
- Human Gate 请求格式。
- Local / Docker Runtime 抽象。

### 35.2 推荐实现

- UI Screenshot Verification。
- Security Scan 集成。
- Performance Test 集成。
- Release Evidence Bundle。
- Checkpoint 和 Resume。

### 35.3 暂缓实现

- 大规模 Agent 市场。
- 完整多租户权限系统。
- Kubernetes 生产部署自动化。
- 复杂成本优化调度。
- 跨云资源编排。

---

## 36. V1.0 非目标

HASF V1.0 不追求：

- 让 AI 永远不需要人。
- 让一个 Agent 写完所有东西。
- 用聊天上下文保存项目事实。
- 用主观回答替代测试和 Evidence。
- 一开始就支持所有语言、框架和云平台。
- 绕过安全授权完成高风险动作。

V1.0 的重点是先让核心闭环跑通。

---

## 37. 关键数据模型草案

### 37.1 Project

```yaml
project:
  id: hasf-demo-001
  name: AI Video Platform
  state: DEVELOPING
  goal: 构建一个 AI 视频平台
  autonomy_budget:
    max_runtime: 72h
    max_cost: 200
  created_at: 2026-08-11T00:00:00+08:00
```

### 37.2 Task

```yaml
task:
  id: TASK-001
  title: 初始化后端服务
  state: READY
  dependencies: []
  assigned_capability: backend
  acceptance_criteria:
    - 服务可以启动
    - health check 返回 200
  evidence_required:
    - build.log
    - unit-test.xml
```

### 37.3 Human Gate

```yaml
human_gate:
  id: HG-001
  type: AUTHORIZATION
  risk: HIGH
  summary: 需要创建云数据库实例
  recommendation: approve_test_database_only
  status: WAITING_FOR_USER
```

---

## 38. 总结

Hermes Autonomous Software Factory 的核心不是“搭一个 Agent 团队”，而是把软件生命周期变成一个可执行、可验证、可恢复的自主系统。

最终架构应围绕以下链路展开：

```text
Project State -> Task -> Agent -> Artifact -> Evidence -> Judge -> Feedback -> Next State
```

只要这个闭环成立，后续无论接入 Codex、Claude Code、OpenCode、自研 Worker，还是 Docker、Sandbox、Browser、GPU Runtime，都只是 Agent Engine 和 Runtime Engine 的不同执行器。

HASF 的目标不是让人完全消失，而是让人从重复推动软件生产的细节中释放出来，只在真正需要目标、判断、授权和资源的地方出现。

