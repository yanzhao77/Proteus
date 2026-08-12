# Hermes Autonomous Software Factory

## 核心运行时详细设计书 V1.2 — Autonomous Decision & Execution Protocol

**文档版本：** V1.2  
**基线版本：** V1.1  
**文档状态：** Implementation Specification  
**项目名称：** Hermes Autonomous Software Factory  
**项目简称：** HASF  
**所属项目：** Proteus / Hermes  
**主题：** 将 V1.1 的 Agent 驱动运行时收敛为事件驱动、证据驱动、策略与资源约束的自治决策与执行运行时  
**目标读者：** Control Plane、Agent Runtime、Verification、Sandbox、数据平台与安全治理实现者  
**规范词：** “必须 / MUST”“不得 / MUST NOT”“应该 / SHOULD”“可以 / MAY”具有协议约束含义

---

## 1. 文档目标与范围

V1.2 不推翻 V1.1。V1.1 已建立的 Control Plane、Project State Machine、Task DAG、Agent Lifecycle、Event Bus、Policy、Budget、Verification / Judge、Feedback、Human Gate、Sandbox、Artifact / Evidence 与 Failure Recovery 继续作为运行时基线。

V1.2 的目标是将职责过重的 `Autonomy Engine` 收敛成一条可解释、可审计、可恢复的自治决策链，并将 Agent 从长期存在的组织角色改为按能力动态创建的执行资源：

```text
Event
  -> Situation Analyzer
  -> [Diagnosis Engine, when failure is present]
  -> Action Planner
  -> Policy Engine
  -> Risk Engine
  -> Budget Engine
  -> Action Selection
  -> Execution Scheduler
  -> Hermes Worker
  -> Artifact / Evidence
  -> Verification / Judge
  -> PASS / FAIL
  -> Structured Feedback
  -> Event Bus
  -> Situation Analyzer
```

本规范定义组件边界、状态所有权、输入输出 Schema、事件语义、幂等与并发规则、失败恢复方式、API 边界及 MVP 实现顺序。下列内容不在 V1.2 范围内：生产级 A5 自治、多租户计费、跨项目 Worker 市场、强制 Kubernetes 部署、自动公开发布和运行时自修改策略。

### 1.1 设计目标

- **自治性：** 无需每轮人工 prompt 即可持续 `Execute -> Verify -> Diagnose -> Repair -> Verify`。
- **安全性：** 任何 Action 均不能绕过 Policy、Risk、Budget、Sandbox 或必要的 Human Gate。
- **可恢复性：** 支持 Retry、Repair、Rollback、Replan、Resume，且不丢失因果链。
- **可解释性：** 每个重大 Decision 可回答 Why、What、Who、Evidence、Cost 与 Risk。
- **资源效率：** 用结构化事件和 Artifact 引用替代自由 Agent 对话。
- **状态一致性：** `Agent != State Authority`。
- **验证独立性：** `Worker != Judge`，只有 Verification Engine 可产生正式 PASS / FAIL。

### 1.2 非目标

- 不增加固定部门式 Agent 层级。
- 不让 Main Hermes 承担实际任务执行。
- 不把 Human Gate 变成每个开发阶段的必经审批。
- 不为了分布式而拆分大量微服务。
- 不把 Kubernetes 设为 MVP 强依赖。

---

## 2. V1.1 → V1.2 架构演进

V1.2 保留 V1.1 的运行时骨架，改变的是自治决策链的职责边界和 Agent 供给方式。

| 主题 | V1.1 | V1.2 | 兼容策略 |
| --- | --- | --- | --- |
| 自治决策 | 单体 Autonomy Engine 观察、分类、评分 | Situation、Planner、Policy、Risk、Budget、Selection 分层 | 旧入口可作为 facade，内部按新链路执行 |
| Agent 模型 | role/profile 容易映射为长期角色 | capability-driven 动态 Worker | 保留 `role=worker/judge` 字段，废弃固定部门语义 |
| 工作模型 | Task DAG 是权威执行结构 | Task DAG 保留；Work Graph 提供完整溯源 | DAG 成为 Work Graph 的 Task 子图 |
| 失败处理 | Feedback 可直接创建 repair task | 失败先 Diagnosis，再规划候选 Action | 旧 repair 事件转换为待诊断 Situation |
| Policy | allow / deny / gate，且评分写入 Policy Log | Policy 仅判定是否允许；Selection 独立选优 | 旧日志迁移到 Decision Log + Policy Decision Log |
| Budget | Token / Cost 为主 | 多维 Resource Accounting | 旧账本字段直接映射，新维度默认 0 / unbounded |
| 调度 | DAG 调度器选择 Agent Profile | Execution Scheduler 匹配 Capability 和 Worker | 旧 profile 转成 capability set |
| 验证 | Judge 负责独立验证 | Verification Engine 是唯一正式裁判 | 旧 `judge.completed` 兼容映射到 `verification.completed` |
| 升级路径 | 固定 N 次后 Gate | L0-L6 情境化升级，不要求逐级经过 | N 作为单策略上限，不再作为唯一升级逻辑 |

### 2.1 单体 Autonomy Engine 拆分

> **[V1.1 → V1.2 ARCHITECTURE CHANGE]**

**原设计：** Autonomy Engine 同时完成 Situation 分类、可用 Action 识别、评分、Policy Check、Budget Check 与执行。  
**修改原因：** 观察、规划、授权和选优混在同一组件中，难以测试决策边界，也容易让 Policy 变成业务决策器。  
**新设计：** Autonomy Engine 成为逻辑域名 / facade，其内部由 Situation Analyzer、Diagnosis Engine、Action Planner、Policy Engine、Risk Engine、Budget Engine、Action Selection 与 Execution Scheduler 组成。  
**收益：** 每一步都有稳定输入输出、独立审计记录和可替换实现。  
**现有影响：** 保留 V1.1 `observe -> ... -> execute` 外部行为；内部事件、存储和测试拆分。

### 2.2 Policy 与 Action Selection 分离

> **[V1.1 → V1.2 ARCHITECTURE CHANGE]**

**原设计：** 行动评分写入 Policy Decision Log，Policy 既像授权器又像决策器。  
**修改原因：** “允许做”不等于“应该做”；二者混合会使安全规则被效用评分稀释。  
**新设计：** Policy 仅返回 `ALLOW | DENY | REQUIRE_HUMAN` 及约束；Action Selection 对通过过滤的 Action 评分并选择。  
**收益：** 硬约束和优化目标分离，Policy 可确定性测试。  
**现有影响：** 新增 Decision Log；Policy Decision Log 只记录授权结果。

### 2.3 固定 Agent Role 收敛为动态 Worker

> **[V1.1 → V1.2 ARCHITECTURE CHANGE]**

**原设计：** V1.1 定义 planner、worker、specialist、reviewer、recovery_agent 等角色，容易进一步固化为长期“部门”。  
**修改原因：** 长驻专业 Agent 增加上下文同步、空闲成本和 A2A 沟通复杂度。  
**新设计：** Main Hermes、Control Plane、Verification / Judge、Human Gate 保留为系统角色；实际工作由按 `required_capabilities` 动态创建的 Hermes Worker 完成。  
**收益：** 能力按任务组合，Worker 完成后休眠、回收或销毁。  
**现有影响：** `AgentProfile` 迁移为 `WorkerTemplate + CapabilityDescriptor`；不要求删除已有 Agent Registry。

### 2.4 Task DAG 扩展为 Work Graph

> **[V1.1 → V1.2 ARCHITECTURE CHANGE]**

**原设计：** Task DAG 记录任务依赖和调度状态，但 Artifact、Evidence、Decision、Verification 等依赖外部 Registry 串联。  
**修改原因：** 单独查多个 Registry 才能回答“哪个证据导致哪次修复”。  
**新设计：** Task DAG 继续是可执行工作的无环子图；Work Graph 以类型化边连接 Project、Task、AgentRun、Artifact、Evidence、Decision、HumanGate、Resource、Verification 与 Feedback。  
**收益：** 统一因果追踪和影响分析，同时不牺牲 DAG 调度效率。  
**现有影响：** 原 Task API 保持兼容；新增 Graph 查询和边写入事务。

### 2.5 失败先诊断再修复

> **[V1.1 → V1.2 ARCHITECTURE CHANGE]**

**原设计：** Verification failure 可直接创建 repair task。  
**修改原因：** Verification 只证明失败发生，不天然知道根因；直接修复容易重复试错。  
**新设计：** FAIL 先生成结构化 Feedback 和 failure Situation；Diagnosis Engine 输出 Root Cause（允许为 null），Planner 再生成 diagnose / repair / rollback / replan 等候选 Action。  
**收益：** 将症状与根因分离，提升修复成功率和证据质量。  
**现有影响：** `create_repair_task` 仍可用，但必须引用 Diagnosis；只有低风险且根因高置信时可跳过额外诊断执行。

### 2.6 Budget 升级为 Resource Accounting

> **[V1.1 → V1.2 ARCHITECTURE CHANGE]**

**原设计：** 预算主要覆盖 token、工具调用、wall time、Agent run、retry 与外部成本。  
**修改原因：** CPU、GPU、容器、浏览器、存储、外部 API 和 Human Attention 也会成为自治瓶颈。  
**新设计：** Budget Engine 管理多维 allocation、reservation、consumption、release 和 threshold。  
**收益：** 调度前可原子预留资源，失败后可准确核销，避免并发超卖。  
**现有影响：** 原 Budget Ledger 保留并扩展维度。

### 2.7 Agent 通信改为 Collaboration Task

> **[V1.1 → V1.2 ARCHITECTURE CHANGE]**

**原设计：** V1.1 允许经 Control Plane 审计的 `handoff`、`request_review` 等 Agent 间消息。  
**修改原因：** 即使可审计，面向 Agent 的自由消息仍可能演化为多轮聊天。  
**新设计：** Agent 只向 Control Plane 发布 Result、Finding、ContextRequest；需要另一能力时创建有目标、预算、截止条件的 Collaboration Task。  
**收益：** 协作成为可调度工作而非无界对话。  
**现有影响：** 旧 Message Envelope 仅作为兼容输入，落库前转换为 Event 或 Collaboration Task。

---

## 3. Core Runtime Principles

1. **Control Plane 是唯一编排与项目状态权威。**
2. **Autonomous-First。** 只在不可逆授权、缺失外部资源、业务取舍或自治策略耗尽时进入 Human Gate。
3. **Event-Driven。** 重要输入、状态变化、决策、执行和验证均产生不可变事件。
4. **Evidence-Driven。** 声明不是证据；关键状态转移必须引用 Evidence。
5. **Worker != Judge。** Worker 的 self-report 只能形成 `completion_claim`。
6. **Planner != Policy。** Planner 枚举可行方案；Policy 判断许可。
7. **Risk != Authorization。** Risk 量化风险；Policy / Human Gate 作授权决定。
8. **Budget != Business Strategy。** Budget 只判断资源是否足够。
9. **Dynamic Workers。** Agent 是按能力创建的短生命周期执行资源。
10. **No Direct A2A。** Agent 默认不能相互寻址或建立会话。
11. **Least Context / Least Privilege。** 每个 Worker 只获得任务所需上下文、工具和文件权限。
12. **Recover by Replay。** 权威快照加 append-only Event Log 可以恢复运行时。

---

## 4. Control Plane

Control Plane 持有权威状态并协调自治链。MVP 可实现为单体进程中的模块，不要求微服务。

### 4.1 逻辑组件

- Project Manager：项目创建、暂停、恢复、取消和终态管理。
- State Machine：验证并提交状态转移。
- Work Graph Store：维护 Task DAG 与跨实体关系。
- Event Bus / Event Log：投递、回放、审计、消费者 checkpoint。
- Autonomy System：分析、规划、约束、选优和产生 Execution Intent。
- Execution Scheduler：能力匹配、队列、租约、并发和资源预留。
- Registry：Worker Template、Capability、Artifact、Evidence、Verification 等索引。
- Recovery Controller：checkpoint、replay、reconcile、quarantine。

### 4.2 核心架构图

```text
                         +--------------+
                         |     USER     |
                         +------+-------+
                                |
                                v
                       +-----------------+
                       |   Main Hermes   |
                       | User Interface  |
                       +--------+--------+
                                |
                                v
+---------------------------------------------------------+
|                    CONTROL PLANE                        |
|                                                         |
| Project Manager                                         |
| State Machine                                           |
| Work Graph                                              |
| Event Bus                                               |
|                                                         |
|                 AUTONOMY SYSTEM                         |
| +-----------------------------------------------------+ |
| | Situation Analyzer                                  | |
| | Action Planner                                      | |
| | Policy Engine                                       | |
| | Risk Engine                                         | |
| | Budget Engine                                       | |
| | Action Selection                                    | |
| | Execution Scheduler                                 | |
| +-----------------------------------------------------+ |
|                                                         |
+------------------------+--------------------------------+
                         |
             +-----------+--------------+
             v           v              v
       Agent Runtime  Verification   Human Gate
             |           |              |
             v           v              v
       Hermes Worker    Judge       User Decision
             |
             v
       Execution Plane
             |
       +-----+-----+
       v     v     v
     Docker  VM    K8s
```

说明：K8s 是可选 Execution Adapter，不是 MVP 强依赖。Human Gate 与 Main Hermes 分离；Main Hermes 只能展示 Gate 和提交用户选择，不能代表用户批准。

### 4.3 命令提交事务

每个改变权威状态的 Command 必须在一个逻辑事务中：

```text
validate expected_version
  -> evaluate guard
  -> write state / graph mutation
  -> append outbox event
  -> commit
  -> asynchronously publish outbox
```

Command 必须包含 `command_id`、`idempotency_key`、`expected_version`、`actor` 和 `reason`。版本冲突返回 `409 VERSION_CONFLICT`，调用方重新读取后再规划，不得盲目覆盖。

### 4.4 Control Plane 不负责

- 不直接编写代码或文档。
- 不将 LLM 自述作为完成证据。
- 不执行需要 Sandbox 的工具命令。
- 不代替 Human Gate 作必须由人类完成的授权。

---

## 5. Project State Machine

V1.2 保留 V1.1 状态集：

```text
CREATED -> INTAKE -> DISCOVERY -> PLANNING -> DESIGNING
        -> IMPLEMENTING -> VERIFYING -> HARDENING
        -> PACKAGING -> DELIVERING -> ACCEPTED
```

等待 / 异常状态：

```text
WAITING_FOR_HUMAN  WAITING_FOR_RESOURCE  PAUSED  BLOCKED
RECOVERING  FAILED  CANCELLED
```

### 5.1 状态转移约束

每个状态转移必须满足：

- `guard_result = PASS`；
- 引用足够 Evidence；
- 相关 Policy Decision 为 ALLOW；
- Budget 没有 hard stop；
- 若需要 Human Gate，Gate 已 ANSWERED 且 Decision 已 APPLIED；
- `expected_project_version` 与当前版本一致。

Agent 只能提交 `StateTransitionCandidate`：

```json
{
  "candidate_id": "stc_01J001",
  "project_id": "proj_001",
  "from_state": "IMPLEMENTING",
  "to_state": "VERIFYING",
  "proposed_by_run_id": "run_001",
  "reason": "implementation artifacts were produced",
  "evidence_refs": ["evd_manifest_001"],
  "expected_project_version": 17
}
```

Control Plane 重新计算 guard，不能信任 Candidate 中的判断。

### 5.2 Task 与 Project 状态关系

- `task.completed` 仅代表 Worker 声称结束，不推进 Project。
- `verification.completed(status=PASS)` 才允许 Task 进入 `PASSED`。
- 所有关键 Task 为 `PASSED` 且无阻断 Gate，项目才可离开 `VERIFYING`。
- 任一 CRITICAL FAIL 可触发项目进入 `HARDENING`、`RECOVERING` 或 `WAITING_FOR_HUMAN`，由 Decision 决定。

### 5.3 状态写入权限

| Actor | 提议 | 提交 Project State | 提交 Task State |
| --- | --- | --- | --- |
| Hermes Worker | 是 | 否 | 否 |
| Verification Engine | 产生 verdict | 否 | 否 |
| Main Hermes | 是 | 否 | 否 |
| Human Gate | 产生人类 Decision | 否 | 否 |
| Control Plane | 是 | 是 | 是 |
| Recovery Controller | 仅恢复命令 | 经 guard | 经 guard |

---

## 6. Work Graph / Task DAG

### 6.1 双层模型

Task DAG 是 Work Graph 中由 `Task` 节点和 `DEPENDS_ON` 边构成的无环子图，继续承担可运行性计算。Work Graph 是可包含反馈环的溯源图，不要求整体无环。

节点类型至少包括：

```text
Project  Task  AgentRun  Artifact  Evidence  Decision
HumanGate  Resource  Verification  Feedback
```

核心关系：

```text
Project -CONTAINS-> Task
Task -DEPENDS_ON-> Task
Task -EXECUTED_BY-> AgentRun
AgentRun -PRODUCED-> Artifact
Artifact -VERIFIED_BY-> Verification
Verification -PRODUCED-> Evidence
Verification -EMITTED-> Feedback
Feedback -INFORMED-> Decision
Decision -CREATED-> Task
Decision -OPENED-> HumanGate
AgentRun -CONSUMED-> Resource
```

### 6.2 Task Schema

V1.2 显式继承 V1.1 的 Task 类型：`research | design | implementation | verification | review | repair | packaging | human_gate`，并新增 `diagnosis | collaboration | rollback`。`human_gate` Task 只表示 Control Plane 正在等待独立 Gate，不把 Human Gate 实现成 Worker。

Task 状态继续使用：

```text
NEW  READY  ASSIGNED  RUNNING  WAITING  VERIFYING  PASSED
FAILED  RETRYING  BLOCKED  CANCELLED  SUPERSEDED
```

为消除 Worker 完成与正式通过的歧义，V1.2 在 `RUNNING` 与 `VERIFYING` 之间增加可选状态 `COMPLETION_CLAIMED`。兼容实现可不持久化该状态，但必须发布 `task.completion_claimed`，且绝不能把它映射为 `PASSED`。

```json
{
  "task_id": "task_102",
  "project_id": "proj_001",
  "type": "repair",
  "title": "Repair connection pool exhaustion",
  "state": "READY",
  "priority": 80,
  "dependencies": ["task_101"],
  "required_capabilities": [
    {"name": "database-debugging", "min_level": 3},
    {"name": "backend-code-editing", "min_level": 2}
  ],
  "inputs": {
    "artifact_refs": ["art_service_008"],
    "evidence_refs": ["evd_test_019"],
    "diagnosis_ref": "diag_004"
  },
  "expected_outputs": ["source_patch", "change_summary"],
  "acceptance_criteria": ["integration_suite_passes", "no_pool_leak"],
  "verification_plan_ref": "vplan_102",
  "risk_hint": "MEDIUM",
  "budget_scope_id": "budget_task_102",
  "attempt": 1,
  "version": 3
}
```

### 6.3 DAG 改写

任何动态拆分、合并、替换或追加 Task 均须经过：

```text
work_graph.patch.proposed
  -> validate DAG acyclic
  -> validate task schema
  -> Policy check
  -> optimistic version check
  -> atomic patch
  -> work_graph.patch.applied | work_graph.patch.rejected
```

Patch 必须带 `reason`、`decision_id`、`base_graph_version` 和 `operations[]`。同一 `idempotency_key` 重放不得创建重复 Task。

### 6.4 可运行性

Task 仅在以下条件同时成立时进入 READY：依赖 Task 全部 PASSED；无未决阻断 Gate；输入 Artifact 可读；Verification Plan 已定义；所需 Capability 有可用 Worker Template；预算可预留；Policy 未禁止。

---

## 7. Event Model

Event Bus 是控制循环的触发器和审计骨架。Event 是已经发生的事实，不表达命令。

### 7.1 Event Envelope V1.2

```json
{
  "event_id": "evt_01J001",
  "event_type": "verification.completed",
  "schema_version": "1.2",
  "occurred_at": "2026-08-12T10:00:00.000Z",
  "recorded_at": "2026-08-12T10:00:00.031Z",
  "producer": {
    "type": "verification_engine",
    "id": "verifier_01"
  },
  "project_id": "proj_001",
  "task_id": "task_102",
  "run_id": "run_008",
  "correlation_id": "corr_task_102_attempt_1",
  "causation_id": "evt_verification_requested_01",
  "trace_id": "trace_01J001",
  "sequence": 184,
  "partition_key": "proj_001",
  "idempotency_key": "verification:ver_001:completed:v1",
  "classification": "internal",
  "payload": {
    "verification_id": "ver_001",
    "status": "FAIL",
    "severity": "HIGH",
    "evidence_refs": ["evd_test_019"]
  }
}
```

### 7.2 投递与顺序

- 至少一次投递；消费者必须幂等。
- 仅保证同一 `partition_key` 内的逻辑顺序。
- 每个消费者持久化 `(consumer_name, partition_key, sequence)` checkpoint。
- Schema 使用向后兼容演进；消费者忽略未知字段，不忽略未知关键状态值。
- 处理失败超过策略阈值进入 DLQ，并发出 `event.delivery.dead_lettered`。
- 权威状态与事件通过 transactional outbox 一致提交。

### 7.3 关键事件目录

| Domain | Events |
| --- | --- |
| Project | `project.created`, `project.state_transition.requested/applied/rejected`, `project.paused/resumed` |
| Work | `task.ready/leased/started/completion_claimed/passed/failed`, `work_graph.patch.*` |
| Situation | `situation.detected/updated/superseded` |
| Diagnosis | `diagnosis.requested/completed/inconclusive` |
| Decision | `action.candidates_planned`, `policy.evaluated`, `risk.assessed`, `budget.reserved/rejected`, `action.selected/rejected` |
| Execution | `execution.queued/leased/started/completed/failed/cancelled`, `agent_run.*` |
| Evidence | `artifact.registered`, `evidence.recorded/invalidated` |
| Verification | `verification.requested/started/completed`, `feedback.created` |
| Gate | `human_gate.opened/presented/answered/applied/expired` |
| Recovery | `checkpoint.created`, `recovery.started/reconciled/completed/failed` |

### 7.4 事件触发自治轮次

并非所有事件都需要重新规划。Situation Analyzer 订阅白名单事件；heartbeat、metric sample 等高频事件先聚合。相同 `correlation_id + situation fingerprint` 在 debounce window 内合并，避免事件风暴产生重复决策。

---

## 8. Situation Analyzer

Situation Analyzer 回答“现在发生了什么”，不决定下一步。

### 8.1 输入

- 触发 Event；
- Project / Task 当前快照；
- Agent Result、Verification Result 和 Evidence；
- Budget / Policy 最近结果；
- 相关历史 Decision、Attempt、Failure；
- Work Graph 邻接上下文。

输入通过 `AnalysisContext` 固定到事件 sequence，保证可复现。历史上下文按 correlation、affected component 和时间窗检索，不允许无限注入项目全量记录。

### 8.2 Situation Schema

```json
{
  "situation_id": "sit_001",
  "project_id": "proj_001",
  "type": "verification_failed",
  "status": "OPEN",
  "trigger_event_id": "evt_01J001",
  "task_id": "task_102",
  "failure_type": "integration_test_failure",
  "severity": "HIGH",
  "affected_artifact_refs": ["art_service_008"],
  "affected_components": ["user-service"],
  "available_context_refs": ["evd_test_019", "run_008"],
  "constraints": ["no_production_access"],
  "history_summary": {
    "attempts": 2,
    "strategies_tried": ["increase_timeout"],
    "previous_situation_refs": ["sit_000"]
  },
  "confidence": 0.96,
  "fingerprint": "sha256:...",
  "observed_at_sequence": 184,
  "created_at": "2026-08-12T10:00:00.050Z"
}
```

### 8.3 分类规则

优先使用确定性规则识别 `work_available`、`verification_failed`、`agent_stalled`、`budget_pressure`、`policy_blocked`、`resource_missing`、`state_conflict`。语义分类可使用 LLM，但输出必须通过 Schema 校验并记录模型 / prompt 版本。

同一事实不得同时创建多个活跃等价 Situation。fingerprint 由 `type + task + affected components + causal failure` 计算；新证据更新 Situation version，重大语义变化创建新 Situation 并 supersede 旧记录。

### 8.4 边界

Situation Analyzer 不生成 Action、不授权、不评分、不调度 Worker，也不修改 Project State。

---

## 9. Diagnosis Engine

Diagnosis Engine 在失败、异常、回归、性能劣化或根因未知时回答“为什么失败”。

### 9.1 能力

- Failure Classification；
- Root Cause Analysis；
- Affected Component Detection；
- Failure Correlation；
- Historical Failure Matching；
- 提出用于提高根因置信度的 Evidence Request。

### 9.2 Diagnosis Schema

```json
{
  "diagnosis_id": "diag_004",
  "situation_id": "sit_001",
  "failure_type": "integration_failure",
  "root_cause": "database_connection_pool_exhaustion",
  "confidence": 0.87,
  "affected_components": ["user-service", "database"],
  "supporting_evidence_refs": ["evd_test_019", "evd_metric_004"],
  "contradicting_evidence_refs": [],
  "hypotheses": [
    {
      "description": "connections are not released on timeout",
      "confidence": 0.78,
      "test_action_hint": "run_deeper_test"
    }
  ],
  "root_cause_status": "PROBABLE",
  "recommended_evidence_requests": [],
  "diagnostic_method": "rule_plus_llm",
  "created_at": "2026-08-12T10:01:00.000Z"
}
```

`root_cause_status` 为 `CONFIRMED | PROBABLE | UNKNOWN`。允许 `root_cause = null`；不得为满足 Schema 而臆造根因。

### 9.3 诊断策略

1. 规范化 Verification Finding 和运行日志。
2. 关联同一 trace、artifact version 和 affected component 的历史失败。
3. 应用确定性故障规则。
4. 必要时生成假设和证据缺口。
5. 当证据不足时输出 `UNKNOWN`，让 Planner 考虑 `diagnose` 或 `run_deeper_test`。

Diagnosis 本身不修改 Artifact。若需要运行命令或采集新数据，它只提出 Action 候选线索，由 Planner、Policy、Risk、Budget 和 Scheduler 处理。

---

## 10. Action Planner

Action Planner 回答“有哪些可行行动”，不决定最终行动。

### 10.1 Action 类型

```text
retry  diagnose  repair  switch_strategy  switch_agent
expert_review  run_deeper_test  replan  rollback
schedule_ready_task  request_resource  pause  human_gate
```

Action 类型是可扩展 Registry；每种类型声明所需 capability、输入、预期输出、可逆性和估算器。

### 10.2 CandidateAction Schema

```json
{
  "action_id": "act_001",
  "situation_id": "sit_001",
  "type": "diagnose",
  "reason": "root cause is not confirmed",
  "target_refs": ["task_102", "art_service_008"],
  "required_capabilities": ["database-debugging"],
  "parameters": {
    "scope": ["user-service", "database"],
    "read_only": true
  },
  "expected_outputs": ["diagnosis", "evidence"],
  "preconditions": ["artifact_available"],
  "estimated_resources": {
    "llm_tokens": 12000,
    "execution_time_seconds": 900,
    "docker_runtime_seconds": 600,
    "external_api_calls": 0
  },
  "planner_confidence": 0.84,
  "created_by": "action_planner:v1.2.0"
}
```

同一 Situation 默认生成 2-5 个有实质差异的候选；若只有一个合法方案，可以只生成一个并记录原因。`human_gate` 不是默认兜底，必须指出不可自主消除的决策或授权缺口。

### 10.3 规划约束

- Planner 可以参考 Policy 能力声明以避免明显无效候选，但不能假定授权结果。
- Planner 不读取隐藏 Secret，只能知道 Secret 是否可用。
- Planner 不创建 Worker，不预留资源，不写 Task State。
- 候选必须说明预期进展或 Evidence Gain；无进展且无证据增益的 Action 无效。

---

## 11. Policy Engine

Policy Engine 只回答“这个 Action 是否允许执行”。

### 11.1 决策值

- `ALLOW`：在返回 constraints 内允许。
- `DENY`：禁止，不能通过评分或预算覆盖。
- `REQUIRE_HUMAN`：只有绑定的 Human Gate 授权后才能继续。

### 11.2 PolicyDecision Schema

```json
{
  "policy_decision_id": "pol_001",
  "action_id": "act_001",
  "result": "ALLOW",
  "matched_rules": ["project.read_only_diagnostics"],
  "reasons": ["diagnostic access is limited to sandbox artifacts"],
  "constraints": [
    {"type": "network", "value": "disabled"},
    {"type": "filesystem_write", "value": "none"},
    {"type": "max_risk_level", "value": "MEDIUM"}
  ],
  "policy_bundle_version": "policy-2026-08-12.1",
  "input_hash": "sha256:...",
  "evaluated_at": "2026-08-12T10:01:01.000Z"
}
```

### 11.3 规则层级

```text
System Policy
  -> Project Policy
  -> User Policy
  -> Task Policy
  -> Tool / Sandbox Policy
  -> Runtime Emergency Policy
```

更高优先级的 DENY 不可被低优先级 ALLOW 覆盖；Emergency Policy 可以冻结 Action。Production deploy、生产删除、未授权 Secret、越权路径、绕过 Sandbox 等应默认 DENY 或 REQUIRE_HUMAN。

### 11.4 与 Risk 的关系

执行顺序固定为 `Policy -> Risk -> Budget`。Policy 在不知道本次 Risk 分数时，根据 Action 类型、目标环境、自治等级和授权范围返回许可结果及风险边界，例如 `max_risk_level=MEDIUM`、`required_mitigations=[staging_dry_run]`。Risk Engine 随后只计算实际风险；Action Selection 将 RiskAssessment 与这些 Policy constraints 做确定性比较。

因此，`ALLOW` 的准确语义是“若后续风险和其他约束均满足，则允许”，不是无条件执行许可。Risk 高于 Policy 边界时，候选因 `POLICY_RISK_CONSTRAINT_UNSATISFIED` 被过滤；需要放宽边界时只能创建 Human Gate，并在用户授权后产生新的 PolicyDecision。Risk 分数永远不能覆盖 DENY，Action Selection 也不能修改 Policy 边界。

---

## 12. Risk Engine

Risk Engine 评估“执行该 Action 可能造成多大影响”，不负责最终授权。

### 12.1 风险因素

- 源代码、配置或数据库修改；
- 数据删除或迁移；
- 生产 / 客户环境访问；
- 外部网络与第三方 API；
- Secret、凭据、权限提升；
- 可逆性和 rollback 可用性；
- blast radius、数据敏感度、供应链来源；
- Worker / tool 历史可信度。

### 12.2 RiskAssessment Schema

```json
{
  "risk_assessment_id": "risk_001",
  "action_id": "act_002",
  "risk_level": "HIGH",
  "risk_score": 0.82,
  "reasons": [
    "modifies database schema",
    "rollback has not been verified"
  ],
  "factors": {
    "environment": 0.7,
    "data_impact": 0.8,
    "irreversibility": 0.9,
    "privilege": 0.6,
    "blast_radius": 0.8
  },
  "required_mitigations": ["verified_backup", "staging_dry_run"],
  "residual_risk_score": 0.48,
  "model_version": "risk-rules-1.2.0"
}
```

等级映射默认可配置：`LOW [0,0.25)`、`MEDIUM [0.25,0.55)`、`HIGH [0.55,0.8)`、`CRITICAL [0.8,1]`。项目可收紧阈值，不得在无审计的情况下放宽系统底线。

### 12.3 风险过滤

“risk filter”不是 Risk Engine 自行授权，而是 Action Selection 对 `RiskAssessment` 与 `PolicyDecision.constraints` 的机械校验。CRITICAL 通常超过系统 Policy 边界并转为 DENY 或 Human Gate 候选；HIGH 必须在已有 Policy 边界内且 mitigation 全部可满足；LOW / MEDIUM 仍受路径、工具、预算和 Sandbox 约束。Risk Engine 不输出 `ALLOW`、`DENY` 或 `REQUIRE_HUMAN`。

---

## 13. Budget / Resource Accounting

Budget Engine 回答“是否有足够资源继续”，不决定业务策略。

### 13.1 资源维度

```text
llm_tokens  llm_cost  agent_runs  retry_count  execution_time
cpu_time  gpu_time  docker_runtime  browser_runtime
external_api_calls  storage_bytes  human_attention
```

单位必须固定：token、货币最小单位、count、milliseconds、byte。货币带 `currency`，不同币种不得直接合并。

### 13.2 ResourceAccount Schema

```json
{
  "budget_scope_id": "budget_task_102",
  "project_id": "proj_001",
  "scope": {"type": "task", "id": "task_102"},
  "limits": {
    "llm_tokens": 80000,
    "llm_cost_minor": 5000,
    "agent_runs": 4,
    "retry_count": 5,
    "execution_time_ms": 3600000,
    "cpu_time_ms": 1800000,
    "gpu_time_ms": 600000,
    "docker_runtime_ms": 2400000,
    "browser_runtime_ms": 600000,
    "external_api_calls": 100,
    "storage_bytes": 1073741824,
    "human_attention_requests": 1
  },
  "consumed": {
    "llm_tokens": 22400,
    "llm_cost_minor": 1280,
    "agent_runs": 2,
    "retry_count": 2,
    "execution_time_ms": 1260000
  },
  "reserved": {
    "llm_tokens": 12000,
    "agent_runs": 1,
    "execution_time_ms": 900000
  },
  "thresholds": {"warn": 0.75, "gate": 0.95, "hard_stop": 1.0},
  "currency": "USD",
  "version": 9
}
```

### 13.3 Reservation Protocol

```text
estimate(action)
  -> reserve atomically(expected_budget_version)
  -> execute
  -> settle(actual usage)
  -> release unused reservation
```

Reservation 失败的候选标记为 `BUDGET_INFEASIBLE`，可由 Planner 生成更便宜的替代方案。达到 warn 阈值时减少并行度并优先高 Evidence Gain；gate 阈值可请求预算扩展；hard stop 停止新执行，只允许取消、核销、checkpoint、总结和恢复规划。

### 13.4 Human Attention

Human Gate 本身消耗 `human_attention_requests`。这用于抑制无意义提问，不得用于跳过安全上必须的人类授权；安全 Gate 即使预算耗尽也要创建，但项目保持暂停。

---

## 14. Action Selection

Action Selection 从满足 Policy、Risk 约束和 Budget 可行性的候选中选择一个或一组不冲突 Action。

### 14.1 处理管线

```text
candidate actions
  -> policy filter
  -> risk assessment + policy risk gate
  -> budget feasibility filter
  -> score
  -> conflict / concurrency check
  -> select action
```

### 14.2 ActionScore

```json
{
  "action_id": "act_001",
  "score": 0.84,
  "dimensions": {
    "expected_progress": 0.91,
    "confidence": 0.82,
    "evidence_gain": 0.88,
    "reversibility": 0.95,
    "risk": 0.10,
    "cost": 0.20,
    "time": 0.18,
    "historical_success": 0.73
  },
  "weight_profile_id": "default-recovery-v3",
  "score_explanation": [
    "high evidence gain",
    "read-only and reversible"
  ]
}
```

默认形式可沿用 V1.1 weighted score，但权重必须来自版本化配置：

```text
score = sum(positive_dimension * positive_weight)
      - sum(negative_dimension * negative_weight)
```

所有维度规范化到 `[0,1]`；缺失值必须用 profile 声明的保守默认值，不能静默当作 0。权重、归一化器、tie-breaker 与输入快照 hash 必须写入 Decision Record。

### 14.3 Decision Record

```json
{
  "decision_id": "dec_001",
  "situation_id": "sit_001",
  "candidate_action_refs": ["act_001", "act_002", "act_003"],
  "eligible_action_refs": ["act_001", "act_003"],
  "selected_action_refs": ["act_001"],
  "rejections": [
    {"action_id": "act_002", "reason": "POLICY_REQUIRE_HUMAN"}
  ],
  "score_refs": ["score_act_001", "score_act_003"],
  "weight_profile_id": "default-recovery-v3",
  "decision_reason": "highest expected evidence-adjusted progress",
  "input_sequence": 184,
  "created_at": "2026-08-12T10:01:02.000Z"
}
```

### 14.4 确定性与并行选择

相同输入快照、配置版本和随机种子应产生相同排序。只有目标与写集合互不冲突、预算均已预留且并发策略允许时，才可选择多个 Action。并列时依次选择更低风险、更高可逆性、更低成本、稳定 action_id。

---

## 15. Execution Scheduler

Scheduler 将已选 Action 转换为实际 ExecutionRequest，不进行业务推理。

### 15.1 职责

```text
Capability Matching  Worker Selection  Spawn  Queue  Priority
Concurrency  Retry Scheduling  Resource Allocation  Cancellation
Lease / Heartbeat  Worker Pool Reuse
```

### 15.2 调度流程

```text
Selected Action
  -> derive required capabilities
  -> query Agent Registry
  -> filter by trust / availability / sandbox support
  -> rank Worker Templates
  -> reserve resources
  -> create ExecutionRequest
  -> lease to dynamic Hermes Worker
  -> monitor heartbeat and deadline
```

### 15.3 ExecutionRequest Schema

```json
{
  "execution_request_id": "exec_001",
  "decision_id": "dec_001",
  "action_id": "act_001",
  "task_id": "task_102",
  "required_capabilities": [
    {"name": "database-debugging", "min_level": 3}
  ],
  "context_bundle_ref": "ctx_001",
  "sandbox_profile_ref": "sandbox_diag_ro",
  "policy_constraints_ref": "pol_001",
  "resource_reservation_ref": "resv_001",
  "priority": 80,
  "not_before": "2026-08-12T10:01:02.000Z",
  "deadline": "2026-08-12T10:16:02.000Z",
  "max_attempts": 1,
  "idempotency_key": "dec_001:act_001:attempt_1"
}
```

### 15.4 租约与并发

- Worker 通过原子 lease 获得请求；lease 带 owner、expiry 和 fencing token。
- 过期请求可重新入队；旧 Worker 的晚到写入因 fencing token 失效而拒绝。
- 同一 Task 的写 Action 默认串行；只读诊断可并行。
- 并发锁按 `project/path/component/resource` 声明，不依赖 Worker 自觉。
- Retry Scheduling 只重试执行层瞬态错误；业务失败回到 Situation / Planner。

### 15.5 Scheduler 边界

Scheduler 不判断修复策略、不改变候选参数、不产生 PASS / FAIL、不绕过预算创建 Worker。

---

## 16. Agent Runtime

Agent Runtime 创建、隔离、运行和终止 Hermes Worker，并把结构化结果交回 Control Plane。

### 16.1 Agent Registry

Registry 存储能力而非部门：

```json
{
  "worker_template_id": "worker_backend_diag_v2",
  "capabilities": [
    {"name": "database-debugging", "level": 4},
    {"name": "log-analysis", "level": 4}
  ],
  "supported_tools": ["shell_readonly", "sql_explain"],
  "supported_sandboxes": ["docker", "local_restricted"],
  "trust_tier": "standard",
  "cost_profile": "medium",
  "context_limit": 200000,
  "status": "AVAILABLE",
  "success_metrics": {
    "sample_size": 42,
    "verified_success_rate": 0.81
  }
}
```

历史成功率只能作为 Selection / Scheduler 的一个信号，样本量不足必须降低权重，不得形成永久垄断。

### 16.2 Context Bundle

Context Builder 只提供 Task、Situation、Diagnosis、相关 Artifact / Evidence、约束、验收标准和允许工具。大内容使用 immutable ref；Secret 仅以能力句柄提供，不进入 prompt 或 Event。

### 16.3 Worker 输出

```json
{
  "run_id": "run_009",
  "execution_request_id": "exec_001",
  "status": "COMPLETED",
  "completion_claim": "diagnosis evidence collected",
  "artifact_refs": ["art_diag_bundle_001"],
  "evidence_candidate_refs": ["evd_log_020"],
  "findings": [
    {
      "type": "connection_leak",
      "summary": "timeout path does not release connection"
    }
  ],
  "resource_usage_ref": "usage_run_009",
  "open_issues": [],
  "state_transition_candidates": []
}
```

Worker 的 `status=COMPLETED` 只表示执行协议结束，不表示 Task PASSED。

---

## 17. Hermes Worker Lifecycle

```text
REQUESTED -> CREATED -> CONTEXT_PREPARED -> LEASED -> RUNNING
          -> REPORTING -> COMPLETED -> SLEEPING | POOLED | DESTROYED
```

异常状态：

```text
WAITING_FOR_TOOL  RETRYING  TIMED_OUT  CANCELLED  FAILED  QUARANTINED
```

### 17.1 生命周期协议

1. **Create：** Scheduler 选择 Worker Template，Agent Runtime 创建隔离实例。
2. **Context Prepare：** 校验 context refs、policy constraints、sandbox profile 和 fencing token。
3. **Lease：** Worker 接受有时限的单个 ExecutionRequest。
4. **Run：** 只使用允许工具；周期性 heartbeat；记录 usage。
5. **Report：** 发布 Artifact、Evidence Candidate、Finding 和 Completion Claim。
6. **Finalize：** 释放 lease 和未用 reservation；根据复用策略销毁、休眠或回池。

### 17.2 重用条件

Worker Pool 仅复用干净运行环境。包含 Secret、生产访问、未清理工作树、Policy violation 或不可证明隔离状态的 Worker 必须销毁。上下文记忆默认不跨 Task 保留；可复用知识必须先转成经审查的 Artifact / Memory Record。

### 17.3 取消与超时

取消先发 cooperative cancel，超时后由 Execution Adapter 强制终止。晚到 Artifact 可以隔离保存用于审计，但不得自动连接到当前 Task version。

---

## 18. Agent Communication Protocol

### 18.1 默认路径

```text
Agent A
  -> Result / Finding / ContextRequest
  -> Control Plane / Event Bus
  -> Situation / Decision / Scheduler
  -> Agent B
```

禁止默认 `Agent A -> Agent B`，禁止共享私有会话、直接工具通道或相互修改 workspace 状态。

### 18.2 Collaboration Task

当一个 Worker 确实需要另一种能力时，提交 `CollaborationRequest`：

```json
{
  "collaboration_request_id": "collab_req_001",
  "origin_run_id": "run_009",
  "parent_task_id": "task_102",
  "objective": "review database pool diagnosis",
  "required_capabilities": ["database-performance-review"],
  "input_refs": ["art_diag_bundle_001", "evd_log_020"],
  "expected_outputs": ["structured_finding"],
  "budget_hint": {"llm_tokens": 10000, "agent_runs": 1},
  "deadline_seconds": 900
}
```

Control Plane 将其转为候选 Action；经完整决策链后才创建 `type=collaboration` 的 Task。协作 Worker 返回结构化 Artifact / Finding，不直接回复源 Worker。Control Plane 决定是否重启或继续源 Task。

### 18.3 通信限制

- 消息体只放摘要和 immutable refs。
- Agent 不能按名字选择另一个 Agent，只能声明 capability。
- 无预算、无截止、无期望产物的协作请求必须拒绝。
- 请求权限转为 Policy evaluation；请求用户转为 Human Gate candidate。
- 消息轮数不作为协作模型；每次后续工作都是新的 Task / Run。

---

## 19. Verification / Judge

Verification Engine 是唯一可以产生正式 PASS / FAIL 的组件。

### 19.1 验证类型

```text
Build  Unit  Integration  E2E  API  Security  Performance
Stress  Chaos  UI  Accessibility  Deployment  Smoke
Static Contract  Semantic Judge
```

### 19.2 Verification Plan

```json
{
  "verification_plan_id": "vplan_102",
  "task_id": "task_102",
  "artifact_selectors": ["source_patch", "test_report"],
  "checks": [
    {
      "check_id": "integration_suite",
      "type": "integration_test",
      "runner_profile": "test_backend_v3",
      "required": true,
      "timeout_seconds": 1200,
      "pass_condition": "exit_code == 0",
      "evidence_level": "E2"
    },
    {
      "check_id": "pool_leak_metric",
      "type": "performance_test",
      "required": true,
      "pass_condition": "open_connections_after_test <= baseline + 2",
      "evidence_level": "E3"
    }
  ],
  "aggregation_rule": "all_required_pass",
  "independence": "worker_context_excluded",
  "version": 2
}
```

没有 Verification Plan 的 Task 只能进入 `COMPLETION_CLAIMED`，不能 PASSED。

### 19.3 VerificationResult

```json
{
  "verification_id": "ver_001",
  "plan_id": "vplan_102",
  "task_id": "task_102",
  "artifact_refs": ["art_patch_010"],
  "status": "FAIL",
  "severity": "HIGH",
  "check_results": [
    {
      "check_id": "integration_suite",
      "status": "FAIL",
      "finding_codes": ["POOL_EXHAUSTION"]
    }
  ],
  "evidence_refs": ["evd_test_019", "evd_runtime_021"],
  "verifier": {"type": "deterministic", "id": "test_runner_03"},
  "artifact_content_hashes": ["sha256:..."],
  "started_at": "2026-08-12T10:10:00.000Z",
  "completed_at": "2026-08-12T10:14:00.000Z"
}
```

状态只有 `PASS | FAIL | INCONCLUSIVE | ERROR | CANCELLED`。`INCONCLUSIVE` 表示证据不足；`ERROR` 表示验证器自身失败。二者都不能推进 Task 为 PASSED，并进入新的 Situation。

### 19.4 独立性

- Judge 不读取 Worker 私有推理，只读取 Task、Artifact、Evidence、标准和必要背景。
- 语义 Judge 输出必须经过 Schema 校验，并记录模型、prompt、temperature 和输入 hash。
- 高风险 Action 的实现 Worker 与 Judge 不得是同一 AgentRun。
- Verification 使用 Artifact content hash 固定被测版本；Artifact 更新后旧 PASS 不可沿用。

### 19.5 核心自治闭环

```text
GOAL
  |
  v
PLAN
  |
  v
EXECUTE
  |
  v
VERIFY
  |
  +----------------+
  |                |
 PASS             FAIL
  |                |
  v                v
NEXT TASK       DIAGNOSE
                   |
                   v
               PLAN ACTION
                   |
            +------+------+
            v             v
        AUTONOMOUS      HUMAN
            |             |
            +------+------+
                   v
                EXECUTE
                   |
                   +-----------> VERIFY
```

---

## 20. Evidence Model

Artifact 是产物，Evidence 是关于行为或质量的可验证记录。Artifact 自身不能证明正确。

### 20.1 Artifact Schema

```json
{
  "artifact_id": "art_patch_010",
  "project_id": "proj_001",
  "task_id": "task_102",
  "run_id": "run_010",
  "kind": "source_patch",
  "uri": "artifact://proj_001/art_patch_010",
  "mime_type": "text/x-diff",
  "content_hash": "sha256:...",
  "size_bytes": 4812,
  "created_by": "run_010",
  "created_at": "2026-08-12T10:08:00.000Z",
  "provenance": {
    "input_artifact_refs": ["art_service_008"],
    "tool_versions": ["git:2.x"]
  },
  "retention_class": "project"
}
```

### 20.2 Evidence Schema

```json
{
  "evidence_id": "evd_test_019",
  "project_id": "proj_001",
  "task_id": "task_102",
  "verification_id": "ver_001",
  "artifact_refs": ["art_patch_010"],
  "kind": "test_report",
  "producer": "verification_engine:test_runner_03",
  "level": "E2",
  "result": "FAIL",
  "summary": "3 integration tests failed with pool exhaustion",
  "raw_ref": "artifact://proj_001/test-report-019.xml",
  "content_hash": "sha256:...",
  "captured_at": "2026-08-12T10:13:59.000Z",
  "integrity": {
    "signed": false,
    "immutable": true
  }
}
```

### 20.3 Evidence 等级

| Level | 含义 | 是否可单独判定代码通过 |
| --- | --- | --- |
| E0 | Worker self-report | 否 |
| E1 | 静态文件 / diff | 否 |
| E2 | 构建、测试、扫描命令 | 视 Verification Plan |
| E3 | 运行时日志、截图、API 响应、指标 | 视 Verification Plan |
| E4 | 独立专业 Judge | 可与其他检查聚合 |
| E5 | 人类验收 | 可用于 acceptance，不替代技术检查 |

Evidence 必须不可变；错误 Evidence 通过 `evidence.invalidated` 标记，不物理覆盖。任何引用失效 Evidence 的 Decision 都应触发重新评估。

---

## 21. Feedback Loop

Feedback 将 Verification、用户反馈、运行时错误和安全发现转换为自治链可消费的结构化事实。

### 21.1 Feedback Schema

```json
{
  "feedback_id": "fb_001",
  "project_id": "proj_001",
  "source": {"type": "verification", "id": "ver_001"},
  "failure_type": "integration_failure",
  "severity": "HIGH",
  "affected_task_id": "task_102",
  "affected_artifact_refs": ["art_patch_010"],
  "finding_codes": ["POOL_EXHAUSTION"],
  "root_cause": null,
  "evidence_refs": ["evd_test_019"],
  "recommended_actions": ["diagnose", "repair"],
  "created_at": "2026-08-12T10:14:01.000Z"
}
```

自然语言可以出现在 `summary`，但不能替代 failure_type、severity、target、evidence 和 recommended_actions 等结构字段。

### 21.2 Feedback 到下一轮

```text
Verification Result / Runtime Finding / Human Feedback
  -> normalize Feedback
  -> feedback.created Event
  -> Situation Analyzer
  -> Diagnosis if applicable
  -> Action Planner
  -> constraint filters + Selection
  -> Execution
  -> Verification
```

Feedback 本身不直接改 Task DAG 或 Project State。旧版 `recommended_action=create_repair_task` 仅作为 Planner hint。

### 21.3 去重与聚合

同一 artifact hash、check id、finding code 的重复 Feedback 在一个 Verification attempt 内去重。多个相关 Finding 可聚合为一个 Situation，但原始 Evidence 链必须保留。

---

## 22. Autonomous Escalation Ladder

```text
L0 Self Retry
  -> L1 Self Repair
  -> L2 Strategy Switch
  -> L3 Agent Switch
  -> L4 Expert Collaboration
  -> L5 Replan
  -> L6 Human Gate
```

### 22.1 语义

| Level | 适用情况 | 典型 Action |
| --- | --- | --- |
| L0 | 瞬态工具 / 网络 / runner 错误，业务输入未变 | retry |
| L1 | 局部、低风险、根因较明确 | repair |
| L2 | 当前策略无效但目标仍有效 | switch_strategy |
| L3 | Worker 能力不匹配或可信度下降 | switch_agent |
| L4 | 需要另一专业能力形成独立产物 | expert_review / collaboration task |
| L5 | 任务分解、架构或假设错误 | replan |
| L6 | 必须人类授权、选择、资源或自治穷尽 | human_gate |

### 22.2 非机械升级

Planner 根据 Situation 直接选择合理层级，不要求逐级经过。生产权限可直接 L6；架构假设错误可直接 L5；普通局部 Bug 可从 L1 开始。每个 `situation fingerprint + strategy` 有独立 attempt 上限，防止同策略换措辞后无限重试。

### 22.3 自治穷尽判定

满足任一条件可判定 exhaustion：所有允许且预算可行的候选均已失败；剩余候选都要求人类授权；继续执行的边际进展和 Evidence Gain 低于配置阈值；达到安全重试上限；缺少不可自主获取的资源或业务信息。

不得仅因单次失败或 Planner 置信度较低直接进入 L6；应先考虑只读诊断和低成本证据收集。

---

## 23. Human Gate Protocol

Human Gate 独立于 Main Hermes：

```text
Main Hermes
     |
     v
Control Plane
     |
     +-- Agent Runtime
     +-- Verification
     +-- Human Gate
```

Main Hermes 负责 Create Project、Query Project、Explain Status、Submit User Decision。Human Gate 负责 Decision、Authorization、Resource Request、Clarification 和 High Risk Intervention。

### 23.1 Gate 类型和状态

类型：`approval | decision | resource | clarification | exception | acceptance`。

```text
OPEN -> PRESENTED -> ANSWERED -> APPLIED -> CLOSED
                 \-> EXPIRED | CANCELLED | SUPERSEDED
```

### 23.2 HumanGate Schema

```json
{
  "gate_id": "gate_001",
  "project_id": "proj_001",
  "task_id": "task_102",
  "decision_id": "dec_007",
  "type": "decision",
  "severity": "HIGH",
  "title": "Choose a data migration strategy",
  "what_happened": "the verified schema change requires a migration policy",
  "attempts_so_far": [
    {"action": "staging_dry_run", "result": "PASS"},
    {"action": "rollback_test", "result": "PASS"}
  ],
  "why_autonomy_cannot_continue": "downtime versus dual-write is a business tradeoff",
  "remaining_options": [
    {
      "id": "A",
      "label": "scheduled downtime",
      "risk_level": "MEDIUM",
      "estimated_cost": {"human_attention_minutes": 10},
      "recommended": false
    },
    {
      "id": "B",
      "label": "dual-write migration",
      "risk_level": "LOW",
      "estimated_cost": {"execution_time_minutes": 90},
      "recommended": true
    }
  ],
  "recommended_option": "B",
  "question": "Which migration strategy is authorized?",
  "autonomy_exhaustion_reason": {
    "reason": "business_decision_required",
    "attempts": 7,
    "strategies_tried": 3,
    "agents_consulted": 2,
    "remaining_options": 2,
    "recommended_option": "B"
  },
  "resume_context_ref": "checkpoint_gate_001",
  "default_if_timeout": "pause_project",
  "expires_at": "2026-08-13T10:00:00.000Z"
}
```

### 23.3 回答与恢复

Gate Answer 必须包含 `selected_option` 或结构化 clarification、`answered_by`、时间和授权范围。Control Plane 校验 Gate version 和 expiry，写入 `human_gate.answered`，产生新的 Decision，再应用 graph patch / state transition。用户回答不能作为任意命令字符串直接执行。

`resume_context_ref` 必须解析到 checkpoint、open Situation、Decision、预算快照、相关 Artifact / Evidence 与下一条待执行 Command。Gate 关闭后可从该上下文恢复，不重新依赖 Main Hermes 的聊天历史。

---

## 24. Sandbox / Execution Plane

Execution Plane 通过 adapter 支持 Docker、受限本地进程、VM 和可选 K8s。MVP 首选本地受限进程或 Docker。

### 24.1 SandboxProfile

```json
{
  "sandbox_profile_id": "sandbox_repair_standard",
  "adapter": "docker",
  "image_ref": "hermes-worker@sha256:...",
  "network": {
    "mode": "deny_by_default",
    "allowed_hosts": []
  },
  "filesystem": {
    "read": ["workspace"],
    "write": ["workspace/src", "workspace/tests"],
    "deny": [".git/objects", "secrets"]
  },
  "secrets": [],
  "privilege": "unprivileged",
  "resources": {
    "cpu_millis": 1000,
    "memory_bytes": 2147483648,
    "pids": 128,
    "timeout_seconds": 1200
  },
  "allowed_tool_ids": ["shell_scoped", "test_runner"],
  "artifact_export_paths": ["reports", "patches"]
}
```

### 24.2 执行约束

- Policy constraints 编译进 SandboxProfile，Runtime 不能扩大权限。
- Secret 使用短期句柄注入，值不得写入 log、Event 或 Artifact。
- 命令、exit code、stdout/stderr ref、资源使用和 violation 都形成 Evidence 候选。
- 大规模删除、系统路径写入、生产访问、未知安装脚本和提权默认阻断。
- Artifact 只从声明的 export path 提取并计算 hash。

### 24.3 执行事件

```text
sandbox.created
sandbox.command.started/completed/failed
sandbox.policy_violation
sandbox.usage.sampled
sandbox.artifact.exported
sandbox.destroyed
```

Policy violation 立即撤销 lease、隔离 Worker，并触发 CRITICAL Situation；任何已产出 Artifact 在独立审查前不得进入验证通过路径。

---

## 25. Failure Recovery

### 25.1 Failure 分类

| Failure | 处理入口 |
| --- | --- |
| Agent crash / timeout | Scheduler 瞬态重试或新 Situation |
| Tool / adapter error | L0 retry、switch strategy |
| Verification FAIL | Feedback -> Diagnosis |
| Verification ERROR | verifier recovery，不归责 Artifact |
| Policy denied | 替代 Action 或 Gate |
| Budget exhausted | cheaper action、pause、Gate |
| State version conflict | reload + replan |
| State corruption | Recovery Controller |
| Sandbox violation | terminate + quarantine + security review |

### 25.2 Checkpoint Schema

```json
{
  "checkpoint_id": "chk_001",
  "project_id": "proj_001",
  "project_state": "HARDENING",
  "project_version": 18,
  "work_graph_snapshot_ref": "snapshot://graph/proj_001/v44",
  "event_cursor": {"partition_key": "proj_001", "sequence": 184},
  "active_situation_refs": ["sit_001"],
  "open_execution_refs": ["exec_001"],
  "artifact_manifest_ref": "artifact://manifest/018",
  "evidence_index_ref": "evidence://index/018",
  "budget_snapshot_ref": "budget://snapshot/009",
  "open_gate_refs": [],
  "created_at": "2026-08-12T10:15:00.000Z",
  "content_hash": "sha256:..."
}
```

### 25.3 恢复流程

```text
detect failure
  -> freeze affected write scopes
  -> checkpoint current durable state
  -> load last valid checkpoint
  -> replay events after cursor
  -> reconcile leases / reservations / artifacts
  -> detect orphan and late results
  -> emit recovery.reconciled
  -> Situation Analyzer decides resume / repair / rollback / replan / gate
```

恢复必须幂等。孤儿 lease 过期后回收；已执行但未核销的资源通过 usage record 结算；没有匹配 ExecutionRequest 和 fencing token 的晚到结果隔离保存。

### 25.4 Rollback

Rollback 也是 Action，必须经过 Policy、Risk、Budget 和 Verification。只有预先声明 rollback plan 且在目标环境验证过，才可提高 reversibility 分数；“可以 git revert”不能自动等同完整业务回滚。

---

## 26. Runtime Invariants

这些约束是运行时必须通过自动测试和生产监控持续验证的硬规则。

### Invariant 1 — Agent 不直接修改 Project State

```text
Agent Result
  -> State Transition Candidate
  -> Control Plane
  -> Policy / Guard / Version Check
  -> State Transition
```

数据库层仅允许 Control Plane service identity 写 Project / Task state 表。

### Invariant 2 — 只有 Verification Engine 产生正式 PASS / FAIL

Worker Completion Claim 不得写 `Task.state=PASSED`。每个 PASSED Task 必须引用一个对当前 Artifact hash 有效的 PASS Verification。

### Invariant 3 — 默认禁止 Direct A2A Communication

Agent credential 不具备其他 Agent 的寻址或发送权限。跨能力协作必须成为 Collaboration Task。

### Invariant 4 — 所有重要 State Transition 必须产生 Event

状态变更与 outbox event 原子提交；检测到无事件状态变化时进入 `RECOVERING`。

### Invariant 5 — 所有重要 Artifact 必须具备 Evidence

Artifact 可注册，但在 Evidence 未达到 Verification Plan 阈值前不能支持 PASSED 或交付状态转移。

### Invariant 6 — 所有 Human Gate 必须能恢复执行上下文

OPEN Gate 必须有有效 `resume_context_ref`；无法解析时 Gate 创建失败并暂停相关动作。

### Invariant 7 — 任何 Agent 都不能绕过 Policy Engine

每个 ExecutionRequest 必须引用与 Action、参数 hash 和当前 Policy bundle 匹配的 ALLOW Decision；Sandbox 再次执行约束。

### Invariant 8 — 任何资源消耗都进入 Resource Accounting

每个 AgentRun / SandboxRun 必须有 reservation 或明确的 emergency accounting record；未核销 run 不得正常关闭。

### Invariant 9 — Risk Engine 不授予权限

RiskAssessment 中不存在 allow 字段；最终执行必须引用 PolicyDecision。

### Invariant 10 — Decision 必须可追溯

每个执行 Action 都能追溯到 Situation、候选集合、Policy、Risk、Budget、ActionScore 和选优配置版本。

### Invariant 11 — Task DAG 始终无环

Work Graph 可以有反馈环，但任何 `DEPENDS_ON` patch 提交前必须通过 cycle check。

### Invariant 12 — 过期 Worker 不得提交权威结果

所有 run 写入校验 lease fencing token；晚到结果只进入隔离审计区。

### Invariant 13 — Human Gate 独立于 Main Hermes

Main Hermes token 不能创建授权结果，只能提交用户产生的 Gate Answer；审计记录必须保留用户主体。

### Invariant 14 — Worker 与 Judge 独立

同一高风险 Task 的实现 run_id 不能同时作为 Verification verifier identity。

---

## 27. Observability / Audit

### 27.1 可观测信号

- Metrics：Situation rate、decision latency、queue depth、lease timeout、verification pass rate、repair success、Gate rate、budget burn、DLQ depth。
- Logs：结构化日志包含 trace_id、project_id、task_id、run_id、decision_id；敏感值脱敏。
- Traces：从触发 Event 贯穿分析、规划、决策、执行和验证。
- Audit：Policy、Gate、状态转移、Secret 使用、生产访问和数据变更写不可变审计记录。

### 27.2 Decision Explain API 输出

每个 Decision 必须可生成：

```json
{
  "why": "root cause unknown; diagnosis had highest evidence gain",
  "what": "execute diagnose on task_102",
  "who": "worker selected by capability database-debugging",
  "evidence_refs": ["evd_test_019"],
  "estimated_cost": {"llm_tokens": 12000, "execution_time_seconds": 900},
  "risk": {"level": "LOW", "score": 0.1},
  "alternatives_rejected": [
    {"action": "repair", "reason": "insufficient root-cause confidence"}
  ]
}
```

### 27.3 SLO 建议

- Control Plane command durable commit p95 < 500 ms（不含 LLM）。
- Event-to-Situation p95 < 5 s（非批量事件）。
- 无孤儿 lease 超过 `2 * lease_ttl`。
- 100% PASSED Task 有有效 Verification 引用。
- 100% ExecutionRequest 有 PolicyDecision 和 ResourceReservation。
- 100% Human Gate 有 resume context。

### 27.4 审计保留

Event、Decision、Policy、Risk、Gate、Evidence 元数据和 state transition 按项目 retention policy 保留。Artifact 原文可按数据分类单独过期，但 hash、provenance 和删除记录保留。

---

## 28. Data Model

### 28.1 核心实体

| Entity | 主键 | 关键字段 | 并发控制 |
| --- | --- | --- | --- |
| Project | project_id | state, autonomy_level, policy_bundle | version |
| Task | task_id | state, dependencies, capabilities, verification_plan | version |
| WorkGraphEdge | edge_id | from, type, to, metadata | graph_version |
| Situation | situation_id | type, fingerprint, status, observed_sequence | version |
| Diagnosis | diagnosis_id | root_cause, confidence, evidence_refs | immutable |
| CandidateAction | action_id | type, parameters, resource estimate | immutable |
| PolicyDecision | policy_decision_id | result, constraints, bundle_version | immutable |
| RiskAssessment | risk_assessment_id | score, level, mitigations | immutable |
| ResourceAccount | budget_scope_id | limits, reserved, consumed | version |
| Decision | decision_id | candidates, selected, score config | immutable |
| ExecutionRequest | execution_request_id | action, lease, deadline | version |
| AgentRun | run_id | template, state, fencing_token, usage | version |
| Artifact | artifact_id | uri, hash, provenance | immutable |
| Evidence | evidence_id | kind, level, result, raw_ref | immutable + invalidation |
| Verification | verification_id | plan, artifact hashes, status | immutable |
| Feedback | feedback_id | failure, severity, evidence | immutable |
| HumanGate | gate_id | type, options, exhaustion, resume_context | version |
| Checkpoint | checkpoint_id | snapshot refs, event cursor, hash | immutable |

### 28.2 引用与删除

- 所有跨实体引用使用稳定 ID，不使用可变文件路径作为主引用。
- Artifact / Evidence 内容使用 content-addressed storage；元数据数据库保存 URI 与 hash。
- 已被 Decision、Verification 或 State Transition 引用的记录不可硬删除。
- 软删除必须产生 Event；受隐私规则要求删除原文时保留不可逆 hash 和删除证明。

### 28.3 一致性边界

单项目 state、Task DAG patch、预算 reservation 和 outbox 写入分别使用短事务。外部执行不持有数据库事务；通过 lease、expected_version 和幂等 key 协调。跨服务采用 saga / compensation，不依赖分布式事务。

### 28.4 建议存储

MVP 可使用 PostgreSQL 或 SQLite：关系表保存状态与 Registry，append-only 表保存 Event，文件系统 / 对象存储保存 Artifact。Work Graph 不要求图数据库；用 typed edge table 和索引即可。

---

## 29. API / Event Protocol

### 29.1 Main Hermes / Project API

```http
POST /v1/projects
GET  /v1/projects/{project_id}
POST /v1/projects/{project_id}:pause
POST /v1/projects/{project_id}:resume
GET  /v1/projects/{project_id}/explanation
```

Main Hermes 不调用内部 state update；pause / resume 产生 Command 并经 guard。

### 29.2 Work / Decision API

```http
GET  /v1/projects/{project_id}/tasks
GET  /v1/projects/{project_id}/work-graph
POST /internal/v1/situations:analyze
POST /internal/v1/diagnoses
POST /internal/v1/action-plans
POST /internal/v1/policy:evaluate
POST /internal/v1/risk:assess
POST /internal/v1/budgets:reserve
POST /internal/v1/actions:select
GET  /v1/decisions/{decision_id}/explanation
```

### 29.3 Execution / Verification API

```http
POST /internal/v1/executions
POST /internal/v1/executions/{id}:lease
POST /internal/v1/executions/{id}:heartbeat
POST /internal/v1/executions/{id}:complete
POST /internal/v1/executions/{id}:cancel
POST /internal/v1/verifications
GET  /v1/verifications/{verification_id}
POST /internal/v1/evidence
POST /internal/v1/artifacts
```

### 29.4 Human Gate API

```http
GET  /v1/projects/{project_id}/human-gates
GET  /v1/human-gates/{gate_id}
POST /v1/human-gates/{gate_id}:answer
POST /v1/human-gates/{gate_id}:cancel
```

回答示例：

```json
{
  "gate_version": 2,
  "selected_option": "B",
  "freeform_note": "run in staging first",
  "answered_by": {"type": "user", "id": "user_001"},
  "idempotency_key": "user_001:gate_001:answer_1"
}
```

### 29.5 通用 API 规则

- 所有写请求使用 `Idempotency-Key`。
- 可变资源使用 ETag / `expected_version`。
- 错误结构包含 `code`、`message`、`retryable`、`details`、`trace_id`。
- `202 Accepted` 表示命令已持久化，不表示 Action 或 Verification 成功。
- 外部 API 不暴露 Worker 私有 prompt、Secret 或内部 chain-of-thought。

### 29.6 核心 Event Payload

`action.selected`：

```json
{
  "decision_id": "dec_001",
  "situation_id": "sit_001",
  "selected_action_refs": ["act_001"],
  "policy_decision_refs": ["pol_001"],
  "risk_assessment_refs": ["risk_001"],
  "resource_reservation_refs": ["resv_001"],
  "score_refs": ["score_act_001"]
}
```

`feedback.created`：

```json
{
  "feedback_id": "fb_001",
  "source_verification_id": "ver_001",
  "failure_type": "integration_failure",
  "severity": "HIGH",
  "affected_task_id": "task_102",
  "evidence_refs": ["evd_test_019"]
}
```

### 29.7 端到端序列

```text
1. verification.completed(FAIL)
2. feedback.created
3. situation.detected
4. diagnosis.completed | diagnosis.inconclusive
5. action.candidates_planned
6. policy.evaluated + risk.assessed + budget.feasibility_checked
7. action.selected
8. execution.queued -> leased -> completed
9. artifact.registered + evidence.recorded
10. verification.requested -> completed
11a. PASS -> task.passed -> next task.ready
11b. FAIL -> feedback.created -> next autonomy round
```

---

## 30. MVP Implementation Plan

MVP 目标是先跑通单项目、单 Control Plane 实例、受限并发的完整自治闭环。

### P0 — 权威骨架与唯一裁判

1. 定义 Project、Task、AgentRun、Artifact、Evidence、Verification、Event 表及版本字段。
2. 实现 append-only Event Log、transactional outbox、幂等消费者。
3. 实现 Project State Machine guard 与 Agent 禁止写状态的数据库权限。
4. 实现 Task DAG、cycle check、READY 计算和基础 Work Graph edge。
5. 实现 Verification Plan / Result，强制只有 Verification 可产生 PASS / FAIL。

**P0 验收：** Worker 声称完成不会使 Task PASSED；重放事件不产生重复状态变化。

### P1 — 自治决策链

1. Situation Analyzer 确定性分类与 fingerprint 去重。
2. Diagnosis Engine 基础 failure rule + `root_cause=null` 协议。
3. Action Planner 候选 Registry。
4. Policy Engine `ALLOW | DENY | REQUIRE_HUMAN`。
5. Risk Engine 规则评分与 mitigation。
6. Resource Accounting、原子 reservation / settlement。
7. 可配置 ActionScore 和 Decision Record。

**P1 验收：** 每个 Selected Action 可完整解释候选、过滤、风险、预算和评分原因。

### P2 — 动态执行与反馈闭环

1. Capability Registry 和 Worker Template。
2. Execution Scheduler queue、lease、fencing token、取消与并发锁。
3. Context Bundle 与 SandboxProfile 编译。
4. Worker Result / Artifact / Evidence Candidate 接入。
5. Structured Feedback 到 Situation 的循环。
6. L0-L5 策略与 attempt ledger。

**P2 验收：** 在模拟集成测试失败下自动完成 `FAIL -> Diagnose -> Repair -> Verify -> PASS`，无需人工 prompt。

### P3 — Human Gate 与恢复

1. 独立 Human Gate Store / API 和 Main Hermes 展示适配器。
2. `autonomy_exhaustion_reason`、option、timeout、resume context。
3. Checkpoint、event replay、lease / reservation reconcile。
4. quarantine、late result、Evidence invalidation。
5. Decision Explain、metrics、trace 与 audit query。

**P3 验收：** 进程在 Gate 等待期间重启后可恢复；回答 Gate 后从同一 Situation 继续，不重做已验证工作。

### 30.1 MVP 技术边界

- 单进程模块化 Control Plane；不拆微服务。
- SQLite 可用于本地原型，PostgreSQL 用于并发部署。
- JSONL / DB outbox 可作为 Event Bus；不强制 Kafka。
- Docker 或当前受限 Sandbox；不强制 K8s。
- 规则优先，LLM 用于 Situation 语义归类、Diagnosis 和 Planner；所有输出结构化并可回放。

### 30.2 必测场景

1. 重复 Event 不重复建 Task。
2. 两个 Scheduler 竞争同一 lease 只有一个成功。
3. 旧 fencing token 的晚到 Result 被隔离。
4. Policy DENY 无法被高 ActionScore 覆盖。
5. Budget reservation 并发不超卖。
6. Worker self-report 不能让 Task PASSED。
7. Artifact hash 变化使旧 Verification 失效。
8. Work Graph 可有反馈环，Task DAG 不可有环。
9. 无 resume context 无法创建 Human Gate。
10. 失败策略耗尽后 Gate 包含全部 attempt 与剩余选项。

---

## 31. V1.2 → V1.3 Roadmap

V1.3 应建立在 V1.2 运行数据上，而不是提前扩大 Agent 数量。

- 基于 Decision / Outcome 的权重离线校准和反事实评估。
- Capability 成功率按任务类型、代码域和风险分层，避免全局平均误导。
- Diagnosis 的历史 failure embedding / case matching，但保留证据引用。
- 多项目 Resource Portfolio 与公平调度。
- Policy-as-code 仿真、变更 diff 和 shadow evaluation。
- 分布式 Scheduler 前先验证单体并发瓶颈；需要时再引入消息队列。
- 强化供应链证明、Artifact 签名和远程 attestation。
- 可选 VM / K8s adapter，不改变 Control Plane 协议。
- 人类决策质量反馈与 Gate 减量优化。
- 长周期项目的状态压缩、Evidence retention 和可验证 Memory。

V1.3 不应以“更多常驻 Agent”为成功指标。成功指标应是更高 verified progress、更低无效成本、更少不必要 Gate、更短恢复时间和更完整的 Decision trace。

---

## 附录 A：V1.1 → V1.2 变更说明汇总

### 新增组件

- Situation Analyzer：把 Event 和权威上下文规范化为 Situation。
- Diagnosis Engine：将失败症状转成证据支持的 Root Cause / Hypothesis。
- Action Planner：生成多个候选 Action。
- Risk Engine：独立评估风险和 mitigation。
- Action Selection：过滤后按版本化评分配置选优。
- Execution Scheduler：把 Action 映射为 capability、Worker、queue、lease 和资源。
- Work Graph：连接 Task、Run、Artifact、Evidence、Decision、Gate 和 Feedback。
- Resource Accounting：多维资源 reservation、settlement 和 threshold。

### 删除 / 合并 / 降级的组件语义

- 不删除 Autonomy Engine 名称，但将其降为自治系统 facade，不再是全能决策器。
- 不再把 Backend / Frontend / Testing / Security Hermes 作为长期部门；其知识转为 Capability 和 Worker Template。
- `planner`、`specialist`、`recovery_agent` 不再要求为常驻进程，其工作由 Action 类型和动态 Worker 表达。
- V1.1 Agent Message / handoff 降为兼容层；新协作必须创建 Collaboration Task。
- `judge.completed` 保留兼容消费，新生产者统一发布 `verification.completed`。
- Token / Cost Budget 合并进 Resource Accounting。
- V1.1 直接 Feedback -> Repair 路径改为 Feedback -> Situation -> Diagnosis -> Planner；高置信局部根因仍可快速选择 Repair。

### 保留且强化

- Main Hermes 继续是用户入口，但不是执行器或状态权威。
- Human Gate 继续独立于 Main Hermes，并新增自治穷尽说明与恢复上下文。
- Task DAG 继续作为调度权威子图。
- Event Bus、Sandbox、Artifact / Evidence、Failure Recovery 继续存在并补充幂等、hash、lease 和 replay 规则。
- 默认 Autonomous-First；Human Gate 只处理必须由人类完成的决策、授权、资源和澄清。

---

## 附录 B：架构一致性验收矩阵

| 维度 | 必须证明 | 验收证据 |
| --- | --- | --- |
| 自治性 | `Execute -> Verify -> Diagnose -> Repair -> Verify` 可闭环 | 端到端失败注入测试与事件 trace |
| 安全性 | Agent 无法绕过 Policy、Risk gate、Budget、Sandbox | DENY / exhaustion / violation 集成测试 |
| 可恢复性 | Retry、Repair、Rollback、Replan、Resume 可执行 | checkpoint replay 与进程重启测试 |
| 可解释性 | Decision 回答 Why / What / Who / Evidence / Cost / Risk | Decision Explain API 快照测试 |
| Token Efficiency | 无 Direct A2A，无无界协作 | capability task 审计与消息权限测试 |
| 状态一致性 | `Agent != State Authority` | 数据库权限与非法写入测试 |
| 验证独立性 | `Worker != Judge` | identity guard 与 Artifact hash 测试 |

只有上述矩阵全部满足，V1.2 Runtime 才能从“Agent 集群架构”被视为“Autonomous Software Engineering Runtime”。
