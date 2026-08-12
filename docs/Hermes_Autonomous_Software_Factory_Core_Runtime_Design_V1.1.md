# Hermes Autonomous Software Factory

## 核心运行时详细设计书 V1.1

**文档版本：** V1.1  
**文档状态：** Draft  
**项目名称：** Hermes Autonomous Software Factory  
**项目简称：** HASF  
**所属项目：** Proteus / Hermes  
**主题：** 将 Subagent、并行委派、工具、Skills、Memory、Sandbox 等底层积木组织为可持续自主运行的控制系统  
**目标读者：** Agent Runtime 设计者、Control Plane 开发者、软件工厂系统实现者、质量与安全负责人

---

## 1. 文档定位

V1.0 定义了 Hermes Autonomous Software Factory 的总体架构、核心理念和系统边界。V1.1 不再重复愿景层概念，而是把 Hermes 真正能够“自己干活”的核心运行时设计出来。

本版本关注的问题是：

```text
当用户给出一个软件目标后，Hermes 如何持续自主推进？
当任务失败、证据不足、预算受限、风险升高时，Hermes 如何判断下一步？
当多个 Agent 并行工作时，系统如何协调、审计、恢复和验证？
```

V1.1 的核心判断是：Hermes 不应该被设计成一个更大的聊天 Agent，而应该被设计成一个事件驱动、证据驱动、策略约束、预算约束、可恢复的自治控制系统。

关键闭环如下：

```text
Task DAG
  -> Agent Lifecycle
  -> Artifact / Evidence
  -> Judge / Verification
  -> Feedback Loop
  -> Autonomy Engine / Policy
  -> Task DAG
```

第 3 到第 8 项是 V1.1 的重点，因为它们决定系统能不能从“会执行任务”升级为“能持续自主运行”。

---

## 2. 核心运行时目标

V1.1 运行时必须满足以下目标。

### 2.1 可持续推进

系统不应完成一个任务后等待新的人工 prompt，而应根据 Project State、Task DAG、Evidence、Policy 和 Budget 自动选择下一步行动。

### 2.2 可验证完成

任何任务完成都不能只依赖 Agent 自述。完成状态必须绑定 Artifact 和 Evidence，并经过 Verification Protocol 或 Judge Protocol 判定。

### 2.3 可控自治

自治不是无限制行动。所有自主行为都必须被 Autonomy Policy、Human Gate Policy、Budget Policy 和 Sandbox Policy 约束。

### 2.4 可恢复运行

系统必须支持从失败、中断、重启、预算耗尽、Agent 崩溃、工具错误和验证失败中恢复。

### 2.5 可审计协作

所有 Agent 之间的委派、反馈、证据、决策和状态变化都必须通过 Event Bus 或可审计记录表达。

### 2.6 可插拔扩展

Project State Machine、Task DAG、Judge、Policy、Sandbox 和 Budget 需要被设计成可替换模块，而不是写死在某个 Main Agent prompt 中。

---

## 3. 总体运行时模型

HASF Runtime 由六个核心系统组成。

```text
┌─────────────────────────────────────────────────────────────┐
│                         Main Hermes                          │
│        Goal intake / User dialogue / High-level synthesis     │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                       Control Plane                          │
│  Project FSM / Task DAG / Policy / Budget / Gate / Recovery   │
└───────────────┬───────────────┬───────────────┬─────────────┘
                │               │               │
                ▼               ▼               ▼
┌─────────────────────┐ ┌────────────────┐ ┌──────────────────┐
│    Agent Runtime     │ │ Verification   │ │   Event Bus       │
│ lifecycle / context  │ │ Judge / tests   │ │ pub/sub / audit   │
└──────────┬──────────┘ └───────┬────────┘ └────────┬─────────┘
           │                    │                   │
           ▼                    ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                     Execution Plane                          │
│     Tools / Skills / Memory / MCP / Docker Sandbox / FS       │
└─────────────────────────────────────────────────────────────┘
```

运行时只允许 Control Plane 改变项目权威状态。Agent 可以提出状态变更请求，但不能直接把项目从 `IMPLEMENTING` 改成 `DELIVERED`。

权威数据包括：

- Project State
- Task DAG
- Agent Instance Registry
- Artifact Registry
- Evidence Store
- Budget Ledger
- Policy Decision Log
- Human Gate Queue
- Event Log
- Recovery Checkpoint

---

## 4. Project State Machine

Project State Machine 是项目级控制器，负责定义项目从目标输入到交付验收的生命周期。

### 4.1 状态列表

```text
CREATED
  -> INTAKE
  -> DISCOVERY
  -> PLANNING
  -> DESIGNING
  -> IMPLEMENTING
  -> VERIFYING
  -> HARDENING
  -> PACKAGING
  -> DELIVERING
  -> ACCEPTED
```

异常与等待状态：

```text
WAITING_FOR_HUMAN
WAITING_FOR_RESOURCE
PAUSED
BLOCKED
RECOVERING
FAILED
CANCELLED
```

### 4.2 状态定义

| State | 含义 | 进入条件 | 退出条件 |
| --- | --- | --- | --- |
| `CREATED` | 项目记录已创建 | 用户目标或系统任务创建 | 基础元数据完整 |
| `INTAKE` | 理解目标和约束 | 用户输入可解析 | 目标、范围、成功标准形成 |
| `DISCOVERY` | 读取代码库和环境 | 项目存在可分析对象 | 形成 Project Context |
| `PLANNING` | 生成 Task DAG | 上下文足够 | DAG 可执行且通过策略检查 |
| `DESIGNING` | 形成设计方案 | 需要架构或规格 | 设计 Artifact 通过 Judge |
| `IMPLEMENTING` | 执行代码或文档任务 | 至少一个任务可运行 | 所有实现任务完成或阻塞 |
| `VERIFYING` | 验证结果 | 有待验证 Artifact | Verification 完成 |
| `HARDENING` | 修复质量问题 | 验证发现问题 | 问题归零或进入 Gate |
| `PACKAGING` | 准备交付 | 验证通过 | 交付包形成 |
| `DELIVERING` | 给用户最终结果 | 交付包可用 | 用户接受或请求修改 |
| `ACCEPTED` | 项目完成 | 用户接受或自动验收策略满足 | 终态 |

### 4.3 状态转移规则

状态转移必须满足四类条件：

1. `guard`：状态转移前置条件。
2. `evidence`：支撑转移的证据集合。
3. `policy`：策略引擎允许该转移。
4. `budget`：预算允许继续推进。

状态转移请求示例：

```json
{
  "project_id": "proj_001",
  "from_state": "IMPLEMENTING",
  "to_state": "VERIFYING",
  "requested_by": "control_plane",
  "reason": "all runnable implementation tasks completed",
  "required_evidence": [
    "task_completion_summary",
    "artifact_manifest",
    "agent_execution_logs"
  ],
  "policy_checks": [
    "no_open_critical_task",
    "budget_not_exceeded",
    "human_gate_not_required"
  ]
}
```

### 4.4 权威推进原则

Project State Machine 只接受以下来源的状态推进：

- Control Plane 内部调度器。
- Human Gate 的明确决策。
- Recovery Controller 的恢复动作。
- 系统初始化和终止控制器。

Agent 输出只能成为 `state_transition_candidate`，不能成为最终状态。

---

## 5. Task DAG

Task DAG 是项目内所有可执行工作的权威结构。它不是静态计划，而是会被 Feedback Loop 和 Autonomy Engine 持续改写的动态图。

### 5.1 Task 类型

| Type | 含义 | 示例 |
| --- | --- | --- |
| `research` | 读取、调查、理解 | 分析代码库结构 |
| `design` | 设计方案或接口 | 设计运行时 API |
| `implementation` | 修改代码或文档 | 新增协议文档 |
| `verification` | 验证行为 | 运行测试、检查链接 |
| `review` | 独立审查 | Judge 审查 Artifact |
| `repair` | 修复失败 | 根据测试失败修复 |
| `packaging` | 打包交付 | 生成交付清单 |
| `human_gate` | 等待人类授权 | 申请生产部署权限 |

### 5.2 Task 状态

```text
NEW
READY
ASSIGNED
RUNNING
WAITING
VERIFYING
PASSED
FAILED
RETRYING
BLOCKED
CANCELLED
SUPERSEDED
```

### 5.3 DAG 节点 Schema

```json
{
  "task_id": "task_014",
  "project_id": "proj_001",
  "type": "implementation",
  "title": "Write Core Runtime Design V1.1",
  "description": "Create a detailed runtime design document under docs/.",
  "state": "READY",
  "priority": "high",
  "dependencies": ["task_011", "task_012"],
  "inputs": {
    "context_refs": ["artifact:v1_architecture_doc"],
    "constraints": ["chinese_body", "markdown", "docs_directory"]
  },
  "expected_outputs": [
    {
      "kind": "document",
      "path": "docs/Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.1.md"
    }
  ],
  "acceptance_criteria": [
    "covers_project_state_machine",
    "covers_agent_lifecycle",
    "covers_judge_and_human_gate_protocol"
  ],
  "verification_plan": ["heading_scan", "schema_consistency_review"],
  "budget": {
    "max_agent_runs": 2,
    "max_tokens": 80000,
    "max_wall_time_minutes": 60
  }
}
```

### 5.4 DAG 调度规则

Control Plane 每次调度时执行：

1. 找出依赖已满足的 `NEW` 或 `READY` 任务。
2. 根据优先级、风险、资源、预算和并行度计算可运行集合。
3. 为每个可运行任务选择 Agent Profile。
4. 创建 Agent Instance 并注入最小必要上下文。
5. 监听任务事件，持续更新 DAG。

### 5.5 动态改写规则

Task DAG 可以被以下事件改写：

- Judge 判定证据不足，追加 verification task。
- 测试失败，追加 repair task。
- Agent 报告需求歧义，追加 discovery task 或 human_gate task。
- Budget 接近阈值，降低并行度或合并任务。
- Policy 判定风险升高，暂停相关任务并进入 Human Gate。

所有 DAG 改写必须生成 `dag.patch.proposed` 和 `dag.patch.applied` 事件。

---

## 6. Agent Lifecycle

Agent Lifecycle 是 V1.1 的核心。它定义一个 Agent 从创建、执行、产出、验证到销毁的完整协议。

### 6.1 Agent 角色

| Role | 职责 | 是否可改状态 |
| --- | --- | --- |
| `main_hermes` | 用户交互、目标理解、总结交付 | 否 |
| `planner` | 生成或修订 Task DAG | 否 |
| `worker` | 执行具体任务 | 否 |
| `specialist` | 专家型任务执行 | 否 |
| `judge` | 独立验证与裁决 | 否 |
| `reviewer` | 人类可读审查 | 否 |
| `recovery_agent` | 诊断失败和恢复 | 否 |
| `control_plane` | 权威调度、状态、策略 | 是 |

### 6.2 生命周期状态

```text
CREATED
  -> CONTEXT_PREPARED
  -> ASSIGNED
  -> RUNNING
  -> REPORTING
  -> VERIFYING
  -> COMPLETED
```

异常状态：

```text
WAITING_FOR_TOOL
WAITING_FOR_EVENT
RETRYING
TIMED_OUT
CANCELLED
FAILED
QUARANTINED
```

### 6.3 生命周期协议

#### 6.3.1 Create

Control Plane 根据 Task Profile 创建 Agent Instance。

```json
{
  "agent_id": "agent_2026_001",
  "role": "worker",
  "task_id": "task_014",
  "profile": "documentation_worker",
  "isolation": {
    "context_scope": "task_minimal",
    "workspace_scope": "project_worktree",
    "tool_scope": ["read_files", "write_docs", "run_light_verification"]
  }
}
```

#### 6.3.2 Context Prepare

Agent 不直接读取全部 Project Brain。Context Builder 提供最小包：

```json
{
  "task": "task_014",
  "project_summary": "Hermes Autonomous Software Factory",
  "relevant_artifacts": ["artifact:v1_architecture_doc"],
  "constraints": ["write_to_docs", "do_not_commit"],
  "acceptance_criteria": ["all_required_protocols_present"],
  "allowed_tools": ["rg", "sed", "apply_patch", "wc"]
}
```

#### 6.3.3 Run

Agent 执行期间必须周期性发出 heartbeat 和 progress event。

```json
{
  "event_type": "agent.heartbeat",
  "agent_id": "agent_2026_001",
  "task_id": "task_014",
  "status": "running",
  "progress": {
    "phase": "writing",
    "completion_estimate": 0.62
  }
}
```

#### 6.3.4 Report

Agent 完成时不能只返回自然语言，必须返回结构化执行报告。

```json
{
  "agent_id": "agent_2026_001",
  "task_id": "task_014",
  "status": "completed",
  "summary": "Created V1.1 runtime design document.",
  "artifacts": ["artifact:core_runtime_design_v1_1"],
  "evidence": ["evidence:heading_scan", "evidence:line_count"],
  "open_issues": [],
  "recommended_next_tasks": ["review_runtime_api_consistency"]
}
```

#### 6.3.5 Verify

Judge 或 Verification Engine 根据任务验收标准检查 Artifact 和 Evidence。

#### 6.3.6 Complete or Retry

Control Plane 根据 Judge 结果决定：

- 标记任务 `PASSED`。
- 生成 repair task。
- 重试同一 Agent Profile。
- 更换 Agent Profile。
- 进入 Human Gate。

### 6.4 Agent 隔离原则

每个 Agent Instance 必须被隔离在以下维度：

- Context：只拿任务必要上下文。
- Tools：只开放任务必要工具。
- Filesystem：只开放必要路径和读写权限。
- Memory：只允许读取相关记忆，不直接写全局记忆。
- Budget：单 Agent 有独立 token、时间和调用预算。
- Authority：Agent 不能修改 Project State，也不能绕过 Human Gate。

---

## 7. Autonomy Engine

Autonomy Engine 负责在没有人工 prompt 的情况下决定下一步行动。它不是 LLM 本身，而是一个确定性控制器加 LLM 辅助推理的组合。

### 7.1 输入

Autonomy Engine 每轮读取：

- Project State
- Task DAG 状态
- Agent Reports
- Artifact Registry
- Evidence Store
- Judge Results
- Event Stream
- Budget Ledger
- Policy Decisions
- Human Gate Queue

### 7.2 输出

Autonomy Engine 只能输出受限动作：

```text
schedule_task
retry_task
split_task
merge_tasks
create_repair_task
create_verification_task
request_judge
request_human_gate
pause_project
resume_project
transition_project_state_candidate
```

真正执行动作前必须经过 Policy Engine。

### 7.3 自治决策循环

```text
observe
  -> classify_project_situation
  -> identify_available_actions
  -> score_actions
  -> policy_check
  -> budget_check
  -> execute_action
  -> emit_event
  -> wait_for_next_event
```

### 7.4 Situation 分类

| Situation | 含义 | 默认动作 |
| --- | --- | --- |
| `work_available` | 有 READY task | schedule_task |
| `all_work_done_unverified` | 任务完成但证据不足 | request_judge |
| `verification_failed` | 验证失败 | create_repair_task |
| `agent_stalled` | Agent 无进展 | retry_task 或 cancel_agent |
| `ambiguous_requirement` | 需求不明确 | discovery 或 human_gate |
| `budget_pressure` | 预算接近阈值 | reduce_parallelism |
| `policy_blocked` | 策略不允许 | human_gate |
| `resource_missing` | 缺少凭据、网络、服务 | waiting_for_resource |

### 7.5 行动评分

行动评分使用可解释的加权模型。

```text
score(action) =
  expected_progress * 0.35
  + confidence * 0.20
  + evidence_gain * 0.15
  + reversibility * 0.10
  - risk * 0.10
  - budget_cost * 0.10
```

评分结果必须写入 Policy Decision Log，便于之后审计为什么系统选择了某条路径。

---

## 8. Autonomy Policy

Autonomy Policy 定义系统可以自主做什么、不能自主做什么、什么时候必须找人。

### 8.1 Policy 层级

```text
System Policy
  -> Project Policy
  -> User Policy
  -> Task Policy
  -> Tool Policy
  -> Runtime Emergency Policy
```

冲突时优先级从上到下递减。Runtime Emergency Policy 可临时冻结高风险动作。

### 8.2 自治等级

| Level | 名称 | 允许行为 |
| --- | --- | --- |
| `A0` | Manual | 只分析和建议 |
| `A1` | Assisted | 可执行低风险读操作和草稿生成 |
| `A2` | Scoped Autonomous | 可在限定路径内改文件、跑测试、修复 |
| `A3` | Project Autonomous | 可调度多 Agent、自主重试、修复和验证 |
| `A4` | Operational Autonomous | 可操作外部服务，但需要严格 Gate |
| `A5` | Production Autonomous | 可自主生产变更，V1.1 不启用 |

V1.1 MVP 推荐默认等级为 `A3`，但生产部署、付费操作、删除数据、公开发布必须进入 Human Gate。

### 8.3 必须 Gate 的动作

以下动作不能自动执行：

- 删除用户数据或不可恢复文件。
- 修改生产环境配置。
- 使用真实付费资源超过阈值。
- 访问或外传敏感凭据。
- 发布公开版本。
- 合并到受保护分支。
- 修改安全策略或权限边界。
- 在证据不足时声明完成。

### 8.4 Policy Decision Schema

```json
{
  "decision_id": "pol_001",
  "project_id": "proj_001",
  "action": "schedule_task",
  "subject": "task_014",
  "result": "allow",
  "reasons": ["task_scope_is_docs", "budget_available", "no_sensitive_operation"],
  "constraints": ["write_only_docs", "no_git_commit"],
  "evaluated_at": "2026-08-12T10:00:00+08:00"
}
```

### 8.5 Policy 失败处理

Policy 返回 `deny` 时，Autonomy Engine 必须：

1. 停止相关动作。
2. 记录 denied decision。
3. 判断是否有替代动作。
4. 如无替代动作，创建 Human Gate。

---

## 9. Feedback Loop

Feedback Loop 把失败、审查意见、测试结果和用户反馈转化为新的 DAG 动作。

### 9.1 Feedback 来源

- Test failure
- Build failure
- Judge rejection
- Reviewer comment
- Human feedback
- Runtime timeout
- Tool error
- Sandbox violation
- Budget warning
- Security finding

### 9.2 Feedback Schema

```json
{
  "feedback_id": "fb_001",
  "project_id": "proj_001",
  "source": "judge",
  "severity": "medium",
  "target": {
    "type": "artifact",
    "id": "artifact:core_runtime_design_v1_1"
  },
  "finding": "Human Gate protocol lacks timeout handling.",
  "evidence_refs": ["evidence:judge_review_001"],
  "recommended_action": "create_repair_task",
  "must_gate": false
}
```

### 9.3 反馈归类

| Category | 处理方式 |
| --- | --- |
| `correctness` | 创建修复任务并重新验证 |
| `completeness` | 拆分补充任务 |
| `quality` | 创建 reviewer 或 refactor task |
| `security` | 提升风险等级，可能 Gate |
| `performance` | 创建 benchmark 或 optimization task |
| `ambiguity` | 创建 discovery 或 human_gate task |
| `resource` | 进入 waiting_for_resource |

### 9.4 自主修复层级

```text
L0 retry same action
L1 change tool or command
L2 change agent strategy
L3 create specialized repair task
L4 replan DAG
L5 human gate
```

系统最多允许连续自主修复 N 次，默认 N 为 3。超过阈值后必须进入 Human Gate，并附带完整尝试记录。

---

## 10. Judge / Verification Protocol

Judge / Verification Protocol 用来判断任务是否真的完成。

### 10.1 Judge 类型

| Judge | 用途 | 输入 | 输出 |
| --- | --- | --- | --- |
| `deterministic` | 可程序化检查 | 命令、文件、测试 | pass/fail |
| `llm_judge` | 语义质量判断 | Artifact、criteria | verdict |
| `specialist_judge` | 专业审查 | 安全、性能、架构 | findings |
| `human_judge` | 人类验收 | 交付包 | accepted/rejected |

### 10.2 Verification Plan

每个任务必须有 Verification Plan。没有 Verification Plan 的任务只能进入 `DRAFT_COMPLETED`，不能进入 `PASSED`。

```json
{
  "verification_plan_id": "vp_001",
  "task_id": "task_014",
  "checks": [
    {
      "kind": "file_exists",
      "target": "docs/Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.1.md"
    },
    {
      "kind": "heading_coverage",
      "required_headings": [
        "Project State Machine",
        "Task DAG",
        "Agent Lifecycle",
        "Autonomy Engine",
        "Human Gate Protocol"
      ]
    },
    {
      "kind": "semantic_review",
      "criteria": "protocols are implementable and cover runtime autonomy"
    }
  ]
}
```

### 10.3 Judge Result Schema

```json
{
  "judge_result_id": "judge_001",
  "task_id": "task_014",
  "artifact_id": "artifact:core_runtime_design_v1_1",
  "verdict": "pass",
  "confidence": 0.88,
  "findings": [],
  "required_fixes": [],
  "evidence_refs": ["evidence:heading_scan", "evidence:line_count"],
  "can_advance_state": true
}
```

### 10.4 独立性要求

Judge 不应与执行该任务的 Worker 共享完整思考上下文。Judge 只读取：

- 任务要求。
- Artifact。
- Evidence。
- 验收标准。
- 必要项目背景。

Judge 不读取 Worker 的私有推理过程，避免被执行者叙述影响。

### 10.5 失败判定

Judge 返回失败时必须提供：

- 失败项。
- 证据引用。
- 最小修复建议。
- 是否可自主修复。
- 是否需要 Human Gate。

---

## 11. Human Gate Protocol

Human Gate 是自治系统的安全阀，不是普通确认弹窗。

### 11.1 Gate 类型

| Gate Type | 触发场景 |
| --- | --- |
| `approval` | 高风险动作需要授权 |
| `decision` | 多个方案需要用户选择 |
| `clarification` | 需求歧义阻塞进展 |
| `resource` | 缺少凭据、账号、环境或数据 |
| `exception` | 连续失败超过策略阈值 |
| `acceptance` | 最终验收 |

### 11.2 Gate Request Schema

```json
{
  "gate_id": "gate_001",
  "project_id": "proj_001",
  "task_id": "task_021",
  "type": "decision",
  "severity": "high",
  "title": "Choose deployment target",
  "context_summary": "The implementation is verified locally, but deployment requires a target environment.",
  "attempts_so_far": [
    "checked repository configuration",
    "searched for existing deployment settings"
  ],
  "options": [
    {
      "id": "vercel",
      "label": "Deploy to Vercel",
      "risk": "medium",
      "cost": "low",
      "recommended": true
    },
    {
      "id": "skip_deploy",
      "label": "Skip deployment",
      "risk": "low",
      "cost": "none",
      "recommended": false
    }
  ],
  "default_if_timeout": "pause_project",
  "expires_at": "2026-08-12T18:00:00+08:00"
}
```

### 11.3 Gate 状态

```text
OPEN
  -> PRESENTED
  -> ANSWERED
  -> APPLIED
  -> CLOSED
```

异常状态：

```text
EXPIRED
CANCELLED
SUPERSEDED
```

### 11.4 Gate 设计原则

Human Gate 必须一次只问必要问题，并提供可执行选项。Gate 文案必须包含：

- 当前发生了什么。
- 系统已经尝试了什么。
- 为什么不能继续自主推进。
- 用户需要决定什么。
- 推荐选项和风险。
- 不回应时的默认处理。

### 11.5 Gate 后续动作

用户回答后，Control Plane 生成 `human_gate.answered` 事件，再由 Autonomy Engine 转换为具体 DAG patch 或 state transition。

---

## 12. Event Bus

Event Bus 是运行时的审计骨架。所有重要行为都必须事件化。

### 12.1 事件类别

```text
project.*
task.*
agent.*
artifact.*
evidence.*
judge.*
policy.*
budget.*
human_gate.*
sandbox.*
recovery.*
```

### 12.2 Event Envelope

```json
{
  "event_id": "evt_001",
  "event_type": "task.completed",
  "project_id": "proj_001",
  "task_id": "task_014",
  "agent_id": "agent_2026_001",
  "timestamp": "2026-08-12T10:00:00+08:00",
  "causation_id": "evt_000",
  "correlation_id": "corr_001",
  "payload": {},
  "schema_version": "1.0"
}
```

### 12.3 投递语义

V1.1 推荐采用：

- At-least-once delivery。
- Event idempotency key。
- Append-only event log。
- Consumer checkpoint。
- Dead letter queue。

所有状态更新逻辑必须能够处理重复事件。

### 12.4 关键事件

| Event | 含义 |
| --- | --- |
| `project.state_transition.requested` | 请求状态转移 |
| `project.state_transition.applied` | 状态转移已应用 |
| `task.ready` | 任务可调度 |
| `task.assigned` | 任务已分配 |
| `task.completed` | Agent 声称完成 |
| `task.verified` | 任务通过验证 |
| `agent.created` | Agent 创建 |
| `agent.failed` | Agent 失败 |
| `artifact.created` | Artifact 生成 |
| `evidence.recorded` | Evidence 记录 |
| `judge.completed` | Judge 完成 |
| `human_gate.opened` | Gate 打开 |
| `budget.threshold_crossed` | 预算超过阈值 |
| `recovery.started` | 恢复流程开始 |

---

## 13. Agent-to-Agent Communication Protocol

Agent 之间不应自由私聊。所有 Agent-to-Agent 通信都必须经由 Control Plane 或 Event Bus，以便可审计、可限流、可恢复。

### 13.1 通信模式

| Pattern | 用途 |
| --- | --- |
| `delegate` | Planner 或 Control Plane 委派任务 |
| `request_context` | Agent 请求更多上下文 |
| `request_review` | Worker 请求 Reviewer 或 Judge |
| `publish_artifact` | Agent 发布产物 |
| `publish_finding` | Reviewer 发布发现 |
| `handoff` | 一个 Agent 把工作交给另一个 Agent |

### 13.2 Message Schema

```json
{
  "message_id": "msg_001",
  "project_id": "proj_001",
  "from_agent": "agent_planner_001",
  "to": {
    "type": "role",
    "value": "worker"
  },
  "intent": "delegate",
  "task_id": "task_014",
  "content": {
    "summary": "Write the V1.1 runtime design document.",
    "required_outputs": ["markdown_document"]
  },
  "context_refs": ["artifact:v1_architecture_doc"],
  "reply_policy": {
    "required": true,
    "timeout_seconds": 1800
  }
}
```

### 13.3 通信约束

- Agent 不直接发送不可审计消息。
- 大内容通过 Artifact 引用传递，不塞进消息体。
- 请求更多权限必须转为 Policy Check。
- 请求用户输入必须转为 Human Gate。
- 所有 handoff 必须携带当前状态、已尝试动作和未解决问题。

---

## 14. Artifact / Evidence Schema

Artifact 是产物，Evidence 是证明。两者不能混为一谈。

### 14.1 Artifact Schema

```json
{
  "artifact_id": "artifact:core_runtime_design_v1_1",
  "project_id": "proj_001",
  "task_id": "task_014",
  "kind": "document",
  "uri": "file://docs/Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.1.md",
  "mime_type": "text/markdown",
  "created_by": "agent_2026_001",
  "created_at": "2026-08-12T10:00:00+08:00",
  "content_hash": "sha256:...",
  "metadata": {
    "version": "V1.1",
    "language": "zh-CN"
  }
}
```

### 14.2 Evidence Schema

```json
{
  "evidence_id": "evidence:heading_scan",
  "project_id": "proj_001",
  "task_id": "task_014",
  "artifact_id": "artifact:core_runtime_design_v1_1",
  "kind": "command_output",
  "producer": "verification_engine",
  "command": "rg -n \"^#{1,3} \" docs/Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.1.md",
  "result": "pass",
  "summary": "Required protocol headings are present.",
  "raw_ref": "log://verification/heading_scan_001",
  "created_at": "2026-08-12T10:00:00+08:00"
}
```

### 14.3 Evidence 等级

| Level | 含义 | 示例 |
| --- | --- | --- |
| `E0` | Agent self-report | 自述完成 |
| `E1` | Static file evidence | 文件存在、diff |
| `E2` | Command evidence | 测试、构建、扫描输出 |
| `E3` | Runtime evidence | 运行截图、日志、API 响应 |
| `E4` | Independent judge evidence | 独立审查通过 |
| `E5` | Human acceptance | 用户验收 |

任务通过至少需要 E1，代码交付通常需要 E2 或 E3，高风险任务需要 E4 或 E5。

---

## 15. Docker Sandbox Protocol

Docker Sandbox Protocol 定义 Agent 执行命令、测试、构建和危险操作时的隔离边界。

### 15.1 Sandbox Profile

```json
{
  "sandbox_profile_id": "sandbox_docs_light",
  "network": "disabled",
  "filesystem": {
    "read": ["project_root"],
    "write": ["project_root/docs"]
  },
  "env": {
    "allowed": [],
    "blocked": ["*_TOKEN", "*_SECRET", "*_KEY"]
  },
  "resources": {
    "cpu": "1",
    "memory_mb": 1024,
    "timeout_seconds": 600
  },
  "allowed_commands": ["rg", "sed", "wc"]
}
```

### 15.2 Sandbox 事件

```text
sandbox.created
sandbox.command.started
sandbox.command.completed
sandbox.command.failed
sandbox.policy_violation
sandbox.destroyed
```

### 15.3 危险动作处理

以下操作必须被 sandbox policy 拦截或升级为 Human Gate：

- 删除大量文件。
- 修改系统路径。
- 访问外部网络。
- 读取敏感环境变量。
- 运行未知安装脚本。
- 写入生产配置。

### 15.4 结果提取

Sandbox 执行结束后只能提取：

- Exit code。
- stdout/stderr。
- 指定 Artifact。
- 资源使用摘要。
- Policy violation 记录。

---

## 16. Token / Cost Budget

Budget 是自治系统的刹车和方向盘。没有预算模型，自治系统会在失败循环中无限消耗资源。

### 16.1 Budget 类型

| Budget | 含义 |
| --- | --- |
| `token_budget` | LLM token 上限 |
| `tool_budget` | 工具调用次数上限 |
| `wall_time_budget` | 总运行时间上限 |
| `agent_run_budget` | Agent 实例数量上限 |
| `retry_budget` | 重试次数上限 |
| `external_cost_budget` | 外部付费服务上限 |

### 16.2 Budget Ledger

```json
{
  "project_id": "proj_001",
  "scope": "task_014",
  "allocated": {
    "tokens": 80000,
    "agent_runs": 2,
    "wall_time_minutes": 60
  },
  "used": {
    "tokens": 42000,
    "agent_runs": 1,
    "wall_time_minutes": 18
  },
  "thresholds": {
    "warn_at": 0.75,
    "gate_at": 0.95,
    "hard_stop_at": 1.0
  }
}
```

### 16.3 预算策略

- 到达 75%：降低并行度，优先验证关键任务。
- 到达 95%：进入 Human Gate 或请求扩大预算。
- 到达 100%：停止新任务，只允许生成总结和恢复建议。

### 16.4 成本感知调度

Autonomy Engine 在选择任务时必须考虑成本收益：

```text
expected_value = progress_gain * confidence / estimated_cost
```

低价值、高成本、低可逆性的动作应被延后或 Gate。

---

## 17. Failure Recovery

Failure Recovery 让系统可以从失败中继续，而不是从头再来。

### 17.1 失败类型

| Failure | 示例 | 默认处理 |
| --- | --- | --- |
| `agent_failure` | Agent 崩溃、超时 | retry 或 replace agent |
| `tool_failure` | 命令失败、工具不可用 | change tool 或 create repair |
| `verification_failure` | 测试失败 | repair task |
| `policy_failure` | 权限不足 | human gate |
| `budget_failure` | 预算耗尽 | pause 或 gate |
| `state_corruption` | 状态不一致 | recovery checkpoint |
| `sandbox_violation` | 越权访问 | quarantine agent |

### 17.2 Checkpoint

Checkpoint 必须包含：

- Project State。
- Task DAG snapshot。
- Running agent registry。
- Artifact manifest。
- Evidence index。
- Budget ledger。
- Event cursor。
- Open Human Gates。

### 17.3 Recovery 流程

```text
detect_failure
  -> freeze_related_tasks
  -> record_failure_event
  -> classify_failure
  -> load_last_checkpoint
  -> reconcile_event_log
  -> decide_recovery_action
  -> resume_or_gate
```

### 17.4 Agent Quarantine

当 Agent 触发 sandbox violation、重复产出不可信结果或越权请求时，Control Plane 应将其标记为 `QUARANTINED`。隔离后：

- 停止其工具权限。
- 保留日志和 Artifact。
- 触发 Judge 或 Recovery Agent 审查产物。
- 重新分配任务给新 Agent。

---

## 18. Main Hermes 与 Control Plane API

Main Hermes 是面向用户的智能界面，Control Plane 是权威运行时。二者必须通过明确 API 通信。

### 18.1 设计原则

- Main Hermes 可以解释、总结、建议，但不能直接改 Project State。
- Control Plane 返回结构化状态，Main Hermes 负责转成人类可读表达。
- 所有用户决策必须通过 Human Gate API 进入 Control Plane。
- 所有任务调度必须通过 Task API。

### 18.2 Project API

```http
POST /projects
GET /projects/{project_id}
POST /projects/{project_id}/state-transition-requests
POST /projects/{project_id}/pause
POST /projects/{project_id}/resume
```

创建项目请求：

```json
{
  "goal": "Create Hermes runtime design V1.1 under docs.",
  "constraints": ["markdown", "zh-CN", "do_not_commit"],
  "autonomy_level": "A3"
}
```

### 18.3 Task API

```http
GET /projects/{project_id}/tasks
POST /projects/{project_id}/tasks
PATCH /projects/{project_id}/tasks/{task_id}
POST /projects/{project_id}/tasks/{task_id}/schedule
POST /projects/{project_id}/tasks/{task_id}/cancel
```

### 18.4 Agent API

```http
POST /agents
GET /agents/{agent_id}
POST /agents/{agent_id}/cancel
POST /agents/{agent_id}/quarantine
GET /agents/{agent_id}/report
```

### 18.5 Artifact and Evidence API

```http
POST /artifacts
GET /artifacts/{artifact_id}
POST /evidence
GET /evidence/{evidence_id}
GET /projects/{project_id}/evidence
```

### 18.6 Judge API

```http
POST /judge-runs
GET /judge-runs/{judge_run_id}
POST /judge-runs/{judge_run_id}/cancel
```

Judge 请求：

```json
{
  "task_id": "task_014",
  "artifact_refs": ["artifact:core_runtime_design_v1_1"],
  "criteria": ["all_required_runtime_protocols_are_defined"],
  "judge_type": "llm_judge",
  "independence": "no_worker_private_context"
}
```

### 18.7 Human Gate API

```http
GET /projects/{project_id}/human-gates
POST /human-gates
GET /human-gates/{gate_id}
POST /human-gates/{gate_id}/answer
POST /human-gates/{gate_id}/cancel
```

Human Gate 回答：

```json
{
  "gate_id": "gate_001",
  "selected_option": "vercel",
  "freeform_note": "Use the staging project first.",
  "answered_by": "user"
}
```

### 18.8 Event API

```http
GET /projects/{project_id}/events
POST /events
GET /events/stream?project_id={project_id}
```

---

## 19. 核心执行序列

### 19.1 从目标到计划

```text
User Goal
  -> Main Hermes intake
  -> Control Plane creates project
  -> Project State: INTAKE
  -> Discovery Agent reads context
  -> Planner creates Task DAG
  -> Policy checks DAG
  -> Project State: PLANNING or DESIGNING
```

### 19.2 从任务到验证

```text
Task READY
  -> Control Plane schedules Worker
  -> Agent Lifecycle runs
  -> Artifact created
  -> Evidence recorded
  -> Judge evaluates
  -> Task PASSED or repair task created
```

### 19.3 从失败到恢复

```text
Failure event
  -> Feedback classified
  -> Autonomy Engine selects recovery action
  -> Policy and budget checks
  -> Retry / repair / replan / human gate
  -> Evidence updated
```

### 19.4 从验证到交付

```text
All critical tasks PASSED
  -> Project State: VERIFYING
  -> Final Judge
  -> Packaging
  -> Delivery summary
  -> Human acceptance or automatic acceptance
```

---

## 20. V1.1 MVP 边界

V1.1 MVP 应实现以下最小闭环。

### 20.1 必须实现

- Project State Machine。
- Task DAG 基础模型。
- Agent Lifecycle Registry。
- Autonomy Engine 的事件驱动调度循环。
- Autonomy Policy 基础 allow/deny/gate。
- Feedback Loop 到 repair task。
- Judge Protocol 基础版。
- Human Gate Protocol 基础版。
- Artifact / Evidence Registry。
- Budget Ledger 基础版。

### 20.2 可以简化

- Event Bus 可先用 append-only JSONL 或 SQLite event log。
- Docker Sandbox 可先映射到当前 Hermes sandbox 能力。
- LLM Judge 可先使用固定 prompt 和结构化输出。
- API 可先以内嵌服务或本地 RPC 实现，不必立刻拆微服务。

### 20.3 暂缓实现

- A5 生产自治。
- 多租户隔离。
- 跨项目 Agent 市场。
- 复杂计费系统。
- 自动公开发布。
- 长周期自演进策略。

---

## 21. 第一阶段实现建议

推荐按以下顺序实现。

1. 定义 Project、Task、AgentRun、Artifact、Evidence、JudgeResult、HumanGate 的数据模型。
2. 实现 append-only Event Log。
3. 实现 Project State Machine 和状态转移 guard。
4. 实现 Task DAG 调度器。
5. 实现 Agent Lifecycle Registry。
6. 实现基础 Verification Plan 和 Judge Result。
7. 实现 Feedback 到 Repair Task 的自动闭环。
8. 实现 Human Gate 队列和回答应用。
9. 接入 Budget Ledger。
10. 最后再封装 Main Hermes 与 Control Plane API。

第一阶段完成后，系统应该能够支持：

```text
用户提出目标
  -> 系统生成 DAG
  -> 并行调度 Agent
  -> 收集 Artifact 和 Evidence
  -> 独立 Judge
  -> 自动修复失败
  -> 必要时 Gate
  -> 交付总结
```

---

## 22. 总结

V1.1 的重点不是再证明 Autonomous Software Factory 值得做，而是把它变成一个可以实现、可以测试、可以恢复、可以审计的运行时系统。

Hermes 底层已经具备 Subagent 隔离、并行委派、工具、Skills、Memory 和 Sandbox 等积木。V1.1 要设计的是这些积木上方的控制系统：

```text
Project State Machine
  + Task DAG
  + Agent Lifecycle
  + Autonomy Engine
  + Autonomy Policy
  + Feedback Loop
  + Judge / Verification
  + Human Gate
  + Event Bus
  + Evidence
  + Sandbox
  + Budget
  + Recovery
```

最终目标是让 Hermes 从“能完成一次任务的 Agent”升级为“能持续推进软件项目的自治软件工厂”。
