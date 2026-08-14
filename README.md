<div align="center">

# Proteus

**Autonomous software factory infrastructure, built around explicit authority, verifiable evidence, and recoverable execution.**

把一个想法持续推进为可验证、可交付的软件项目。默认自主运行，人类按风险介入，所有关键结论都有证据支撑。

[架构设计](docs/Hermes_Autonomous_Software_Factory_Architecture_V1.0.md) · [Runtime V1.2](docs/Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.2.md) · [规范](docs/specs/Hermes_Runtime_Normative_Spec_V1.0.md) · [P4 产品化规范](docs/specs/Hermes_P4_Productization_Normative_Spec_V1.0.md) · [P5 单节点产品规范](docs/specs/Hermes_P5_Deployable_Product_Normative_Spec_V1.0.md) · [架构决策](ARCHITECTURE_DECISIONS.md) · [P0 验收](docs/P0_ACCEPTANCE_MATRIX.md) · [P1 验收](docs/P1_ACTION_SELECTION_ACCEPTANCE_MATRIX.md) · [P2 验收](docs/P2_EXECUTION_ACCEPTANCE_MATRIX.md) · [P4 验收](docs/P4_PRODUCTIZATION_ACCEPTANCE_MATRIX.md) · [P5 验收](docs/P5_DEPLOYABLE_PRODUCT_ACCEPTANCE_MATRIX.md)

</div>

---

## Proteus 是什么

Proteus 是 **Hermes Autonomous Software Factory** 的设计与核心运行时仓库。它关注的不是“让 Agent 多写一点代码”，而是如何把多个不可靠、可重试的执行单元组织成一个可靠的软件交付系统：

- **Autonomous First**：系统持续观察、诊断、规划、执行和验证，而不是等待人工逐步驱动。
- **Human-on-the-Loop**：人类处理高风险决策和例外，不成为正常流程的串行瓶颈。
- **Evidence Driven**：任务完成、状态流转和最终交付都必须绑定可追溯证据。
- **Deterministic Control Plane**：Agent 可以提出意图，但只有控制平面能够提交权威状态。
- **Failure Is Feedback**：失败进入诊断、修复和重规划闭环，而不是直接终止流程。
- **Everything Is Recoverable**：命令幂等、事件可重放、投递可恢复，进程崩溃不应破坏业务事实。

当前仓库已经完成 **P0 权威骨架**、**P1 自治决策链**、**P2 执行权威链**、**P3 运维治理 runtime**，以及 **P4 产品化边界**；**P5 单节点可部署产品基线**正在补齐生产网络服务、常驻 runtime supervisor、生产 OIDC/Human Gate UI、S3/Vault/OTLP-compatible adapters 和部署运维基线。P4/P5 都不会新增绕过 Control Plane 的状态写入路径。Python/PostgreSQL 实现可以把权威 Event 依次转换为 Situation、Diagnosis、CandidateAction、PolicyDecision、RiskAssessment 和带 ResourceReservation 的 DecisionRecord，再冻结 Capability/Context/Sandbox，创建并排队 ExecutionRequest，由 Scheduler 原子获取 Lease、Fencing Token 和执行锁；P3 runtime 已覆盖 Human Gate/Waiting/Resume、Checkpoint/Replay/Reconcile、Quarantine/Evidence invalidation、immutable Decision Explain/Audit/Trace、第一个真实 Docker execution target，以及跨切片 E2E hardening。

## 核心闭环

```mermaid
flowchart LR
    E["Authoritative Event"] --> S["Situation"]
    S --> D["Diagnosis"]
    D --> P["Candidate Actions"]
    P --> C["Policy + Risk"]
    C --> B["Budget + ActionScore"]
    B --> R["DecisionRecord + Reservation"]
    R --> X["ExecutionRequest"]
    X --> L["Queue + Lease + Fencing"]
    L -. "P2-4" .-> W["Worker + Sandbox"]
    W -.-> A["Artifact + Evidence"]
    A -.-> V["Independent Verification"]
    V -. "FAIL feedback" .-> E
```

实线部分已经覆盖 P0、P1、P2 以及 P3-1/P3-2/P3-3/P3-4/P3-5 的数据库 authority slices；生产 UI、IdP 和云集成仍不属于当前 runtime。贯穿整个运行时的核心边界是：**Worker 不能宣布自己成功，Verifier 不能直接改写任务状态，Policy/Risk/Score/Explain/Docker Adapter 不能互相越权，Agent 也不能绕过 Control Plane 写入权威事实。**

## 当前实现

| 能力 | 当前状态 | 关键保证 |
| --- | --- | --- |
| Completion / Verification | 已实现 | Artifact hash 精确绑定；Worker 与 Verifier 的 run/context 相互独立 |
| Task 与 Project authority | 已实现 | 语义命令、版本检查、fail-closed guard、受控状态迁移 |
| Work Graph / Task DAG | 已实现 | 依赖边无环；项目级 graph version；READY 权威计算 |
| Event Log / Outbox | 已实现 | 状态、事件、Outbox 和 CommandReceipt 在同一本地事务提交 |
| Event delivery | 已实现 | relay lease、重试、DLQ、授权 redrive、至少一次投递 |
| Idempotent consumer | 已实现 | Inbox 去重、partition-local 连续 checkpoint、gap parking/drain |
| Resource Accounting | P1 已完成 | 十二维整数资源、原子预留、Usage、Settlement、threshold 与 Budget Fact |
| Situation / Diagnosis | P1 已完成 | sequence-bounded AnalysisContext、确定性分类、指纹去重与证据约束诊断 |
| Candidate Action Planner | P1 已完成 | 版本化 Registry、确定性候选生成、ResourceEstimate 与权威状态隔离 |
| Policy / Risk | P1 已完成 | DENY/REQUIRE_HUMAN fail-closed；Risk 只评估风险，不授予权限 |
| Action Selection | P1 已完成 | 预算可行性、确定性评分、冲突过滤、不可变 DecisionRecord |
| Selection / Reservation bridge | P1 已完成 | SelectedAction、Reservation、Event、Outbox、Receipt 同事务提交 |
| Capability / Context / Sandbox | P2-1 已完成 | 版本化 WorkerTemplate、确定性匹配、不可变 Context Bundle、fail-closed SandboxProfile 编译 |
| ExecutionRequest / Queue | P2-2 已完成 | admission fail-closed、P1 Reservation 单次交接、冻结输入、同事务 Queue/Event/Outbox/Receipt |
| Scheduler / Lease / Fencing | P2-3 已完成 | PostgreSQL 原子 claim、单调 token、续租/过期接管/重排队、执行锁与权限隔离 |
| Worker lifecycle / Result admission | P2 已完成 | AgentRun、current-token candidate/result、minimal quarantine、settlement；真实 Docker target 由 P3-5 承接 |
| Human Gate / Waiting / Resume | P3-1 已完成 | Gate Request/Decision/Application 分离；ResumeContext 当前 guard 重检 |
| Checkpoint / Replay / Reconcile | P3-2 已完成 | replay shadow generation、checkpoint/reconcile finding/plan、无 authority fold/patch |
| Quarantine / Evidence invalidation | P3-3 已完成 | append-only review/adoption/redrive；Evidence invalidation 不删证据、不改 VerificationResult、阻断 stale Gate resume |
| Decision Explain / Audit / Trace | P3-4 已完成 | immutable snapshot/ref graph、缺链显式 MISSING、授权查询、audit trace 与脱敏 |
| Production Docker execution | P3-5 已完成 | Docker target 1.0、非 root/只读 rootfs/deny network、fencing labels、artifact/output/usage、side-effect receipts |
| P3 E2E hardening | P3-6 已完成 | Human Gate、Docker、side-effect、Quarantine、Evidence、Replay/Reconcile、Explain 端到端权限边界 |
| P4 Productization Contract | P4-0 已完成 | Public API、Human Gate identity、Artifact/Secret/Retention、Observability/export 产品边界；无新增 core authority |
| P4 Public API boundary | P4-1 已完成 | stdlib in-process facade；只允许语义查询/命令 wrapper，拒绝 generic PATCH/status/Event/SQL |
| P4 Human Gate product boundary | P4-2 已完成 | local/test identity assertion；Gate 展示与 Decision 提交分离，不能直接 Project resume |
| P4 Artifact/Secret/Retention | P4-3 已完成 | content-addressed local artifact store；secret handle-only；retention tombstone 与 active dependency guard |
| P4 Observability/export | P4-4 已完成 | OpenTelemetry-compatible local envelope；redaction；MISSING links；metrics/traces 不授权 |
| P4 E2E hardening | P4-5 已完成 | API、Gate、Artifact、Secret、Retention、Observability 跨边界回归 |
| P5 Deployable Product Contract | P5-0 已完成 | 单节点 topology、FastAPI、supervisor、OIDC/UI、S3/Vault/OTLP、deployment/ops 边界规范 |
| Web API / external broker | 未实现 | FastAPI、Kafka、Redis、Kubernetes 均不是当前运行时能力 |

P0、P1 和 P2 的需求、实现与测试映射分别见 [P0 Acceptance Matrix](docs/P0_ACCEPTANCE_MATRIX.md)、各项 [P1 Acceptance Matrix](docs/P1_ACTION_SELECTION_ACCEPTANCE_MATRIX.md) 和 [P2 Execution Acceptance Matrix](docs/P2_EXECUTION_ACCEPTANCE_MATRIX.md)。更精确的 authority 和非目标边界见 [hermes-runtime/README.md](hermes-runtime/README.md)。

## 快速开始

### 环境要求

- Python 3.9+
- PostgreSQL 14+（仅集成测试需要）
- Docker（可选，用于启动一次性测试数据库）

### 运行纯领域测试

领域测试不需要数据库，也不需要安装第三方依赖：

```bash
cd hermes-runtime
PYTHONPATH=src python3 -m unittest \
  tests.test_domain_authority \
  tests.test_graph_domain \
  tests.test_project_domain \
  tests.test_resource_accounting_domain \
  tests.test_situation_domain \
  tests.test_diagnosis_domain \
  tests.test_planner_domain \
  tests.test_policy_domain \
  tests.test_risk_domain \
  tests.test_selection_domain \
  tests.test_architecture_boundaries -v
```

### 运行完整集成测试

启动一个本地 PostgreSQL：

```bash
docker run --rm --name hermes-runtime-postgres \
  -e POSTGRES_PASSWORD=hermes \
  -e POSTGRES_DB=hermes_test \
  -p 55432:5432 \
  -d postgres:16-alpine
```

安装依赖并执行测试：

```bash
cd hermes-runtime
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt

HERMES_TEST_DATABASE_URL='postgresql://postgres:hermes@127.0.0.1:55432/hermes_test' \
  PYTHONPATH=src python3 -m unittest discover -s tests -v
```

如果没有显式设置 `HERMES_TEST_DATABASE_URL`，测试发现仍可运行，但 PostgreSQL 集成测试会被跳过；SQLite 或 mock 不被视为 PostgreSQL authority/concurrency 语义的有效证明。

当前 P0-P3-6 回归基线在 P3-4/P3-5/P3-6 阶段新增 Explain/Audit/Trace、Docker execution 与 E2E hardening 测试；最终精确数字见本分支 P3-6 commit 和 PR 验证记录。阶段验收不能把跳过的数据库、Docker、并发或权限测试计为通过。

### 执行一次 Outbox Relay

```bash
cd hermes-runtime
HERMES_DATABASE_URL='postgresql://user:password@host:5432/database' \
  PYTHONPATH=src python3 -m hermes_runtime.relay_once \
  --owner relay-1 \
  --batch-size 100
```

当前 runner 只执行一个批次，使用 PostgreSQL 本地 durable publisher；仓库暂未包含常驻后台循环或外部消息代理。

## 代码结构

```text
Proteus/
├── hermes-runtime/
│   ├── migrations/             # 版本化 PostgreSQL schema 与权限边界
│   ├── src/hermes_runtime/
│   │   ├── domain/             # 纯领域规则与状态机
│   │   ├── application/        # 命令、用例、ports 与 authority 编排
│   │   └── infrastructure/     # PostgreSQL adapters 与 delivery 实现
│   └── tests/                  # 领域、集成、权限与架构边界测试
├── docs/
│   ├── adr/                    # 单项 Architecture Decision Records
│   ├── specs/                  # 规范性协议与一致性测试要求
│   └── ...                     # 总体架构、runtime 设计与验收矩阵
├── py/                         # 独立的 Python 算法示例
├── ARCHITECTURE_DECISIONS.md   # ADR 导航及 authority order
└── README.md
```

代码按 **authority boundary** 而不是技术框架组织。纯领域层不得依赖数据库或 Web 框架；application 层定义用例与 port；infrastructure 层负责 PostgreSQL 事务、权限和投递细节。

## 文档地图

| 文档 | 用途 |
| --- | --- |
| [Autonomous Software Factory Architecture V1.0](docs/Hermes_Autonomous_Software_Factory_Architecture_V1.0.md) | 产品愿景、系统全景、自治闭环与长期能力模型 |
| [Core Runtime Design V1.2](docs/Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.2.md) | 当前核心运行时的详细设计与 invariants |
| [Runtime Normative Specification](docs/specs/Hermes_Runtime_Normative_Spec_V1.0.md) | authority、ownership、阶段和 traceability 的规范来源 |
| [Command & Event Protocol](docs/specs/Hermes_Command_Event_Protocol_V1.0.md) | 命令事务、事件、Outbox、投递与恢复协议 |
| [Execution Lease Protocol](docs/specs/Hermes_Execution_Lease_Protocol_V1.0.md) | lease、fencing、result admission 与 accounting 交互 |
| [P2 Execution Admission Specification](docs/specs/Hermes_P2_Execution_Admission_Normative_Spec_V1.0.md) | P2 admission、Reservation handoff、Queue、Lease、Worker 与 P2/P3 责任边界 |
| [Conformance Test Specification](docs/specs/Hermes_Conformance_Test_Spec_V1.0.md) | 一致性测试、故障注入与阶段门槛 |
| [P0 Acceptance Matrix](docs/P0_ACCEPTANCE_MATRIX.md) | P0 权威骨架验收结果 |
| [P1 Resource Accounting](docs/P1_RESOURCE_ACCOUNTING_ACCEPTANCE_MATRIX.md) | P1 Slice 1 资源核算验收结果 |
| [P1 Situation Analyzer](docs/P1_SITUATION_ANALYZER_ACCEPTANCE_MATRIX.md) | P1 Slice 2 情境分析验收结果 |
| [P1 Diagnosis Engine](docs/P1_DIAGNOSIS_ENGINE_ACCEPTANCE_MATRIX.md) | P1 Slice 3 诊断引擎验收结果 |
| [P1 Candidate Action Planner](docs/P1_CANDIDATE_ACTION_PLANNER_ACCEPTANCE_MATRIX.md) | P1 Slice 4 候选行动规划验收结果 |
| [P1 Policy and Risk](docs/P1_POLICY_RISK_ACCEPTANCE_MATRIX.md) | P1 Slice 5 策略与风险验收结果 |
| [P1 Action Selection](docs/P1_ACTION_SELECTION_ACCEPTANCE_MATRIX.md) | P1 Slice 6 评分、选择、DecisionRecord 与预留验收结果 |
| [P2 Execution Acceptance Matrix](docs/P2_EXECUTION_ACCEPTANCE_MATRIX.md) | P2 Slice 1-4 的执行准备、调度、Worker/result admission 状态与证据 |
| [P4 Productization Specification](docs/specs/Hermes_P4_Productization_Normative_Spec_V1.0.md) | P4 API、Human Gate identity、Artifact/Secret/Retention 与 Observability 产品化边界 |
| [P4 Productization Acceptance Matrix](docs/P4_PRODUCTIZATION_ACCEPTANCE_MATRIX.md) | P4 产品化切片验收状态 |
| [P4 Completion Summary](docs/Hermes_P4_COMPLETION_SUMMARY.md) | P4 产品化完成范围、边界和验证摘要 |
| [P5 Deployable Product Specification](docs/specs/Hermes_P5_Deployable_Product_Normative_Spec_V1.0.md) | P5 单节点可部署产品、服务拓扑与运维边界 |
| [P5 Deployable Product Acceptance Matrix](docs/P5_DEPLOYABLE_PRODUCT_ACCEPTANCE_MATRIX.md) | P5 单节点产品化切片验收状态 |
| [Architecture Decision Index](ARCHITECTURE_DECISIONS.md) | 规范优先级、ADR 状态与待决问题 |

当文档之间出现冲突时，请遵循 [Architecture Decision Index](ARCHITECTURE_DECISIONS.md) 中定义的 authority order，而不是依据文件名或版本号自行推断。

## 设计边界

当前实现有意保持窄而严格：

- PostgreSQL 是 MVP 的权威状态与并发协调点；当前不引入 Kafka、Redis 或 Kubernetes。
- 系统使用 authoritative state + immutable event log + transactional outbox，不采用 full event sourcing。
- 投递语义是 at-least-once；业务 effect 依靠 inbox/idempotency 保证不重复。
- `supporting_refs` 只提供事实定位线索，不构成权限或状态迁移依据。
- SelectedAction 是已经预留资源的执行意图，不是 ExecutionRequest、Queue、Lease、Worker assignment 或 SandboxProfile。
- 生产部署必须为 Control Plane、Accounting、Situation、Diagnosis、Planner、Policy、Risk、Selection、Relay、Consumer、Redrive、Worker 和只读访问使用不同登录身份，并只授予对应 capability role。

## License

本项目使用 [Apache License 2.0](LICENSE)。
