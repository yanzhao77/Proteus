<div align="center">

# Proteus

**Autonomous software factory infrastructure, built around explicit authority, verifiable evidence, and recoverable execution.**

把一个想法持续推进为可验证、可交付的软件项目。默认自主运行，人类按风险介入，所有关键结论都有证据支撑。

[架构设计](docs/Hermes_Autonomous_Software_Factory_Architecture_V1.0.md) · [Runtime V1.2](docs/Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.2.md) · [规范](docs/specs/Hermes_Runtime_Normative_Spec_V1.0.md) · [架构决策](ARCHITECTURE_DECISIONS.md) · [P0 验收矩阵](docs/P0_ACCEPTANCE_MATRIX.md)

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

当前仓库处于 **核心运行时 P0 纵向切片** 阶段：架构与协议已经形成体系，Python/PostgreSQL 实现覆盖了关键 authority、verification、work graph 和 event delivery 路径；它还不是一个可直接部署的完整自主软件工厂。

## 核心闭环

```mermaid
flowchart LR
    I["Idea / Goal"] --> CP["Control Plane"]
    CP --> WG["Work Graph"]
    WG --> W["Worker Run"]
    W --> A["Artifact + Completion Claim"]
    A --> V["Independent Verifier Run"]
    V --> E{"Evidence satisfies plan?"}
    E -->|Yes| S["Authoritative State Transition"]
    E -->|No| F["Feedback + Repair Task"]
    F --> WG
    S --> O["Event Log + Outbox"]
    O --> CP
    S --> D["Verified Delivery"]
```

这里最重要的边界是：**Worker 不能宣布自己成功，Verifier 不能直接改写任务状态，Agent 也不能绕过 Control Plane 写入权威事实。**

## 当前实现

| 能力 | 当前状态 | 关键保证 |
| --- | --- | --- |
| Completion / Verification | 已实现 | Artifact hash 精确绑定；Worker 与 Verifier 的 run/context 相互独立 |
| Task 与 Project authority | 已实现 | 语义命令、版本检查、fail-closed guard、受控状态迁移 |
| Work Graph / Task DAG | 已实现 | 依赖边无环；项目级 graph version；READY 权威计算 |
| Event Log / Outbox | 已实现 | 状态、事件、Outbox 和 CommandReceipt 在同一本地事务提交 |
| Event delivery | 已实现 | relay lease、重试、DLQ、授权 redrive、至少一次投递 |
| Idempotent consumer | 已实现 | Inbox 去重、partition-local 连续 checkpoint、gap parking/drain |
| Resource accounting | 基础切片 | 资源预留、结算及 PostgreSQL 持久化边界 |
| Web API / Scheduler / Agent adapter | 未实现 | 属于后续阶段，不应从当前 P0 能力推断 |
| Human Gate / Sandbox / external broker | 未实现 | 规范已定义部分边界，实现尚未纳入当前切片 |

完整的 P0 需求到实现与测试映射见 [P0 Acceptance Matrix](docs/P0_ACCEPTANCE_MATRIX.md)。更精确的 runtime 能力边界见 [hermes-runtime/README.md](hermes-runtime/README.md)。

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
  tests.test_architecture_boundaries -v
```

### 运行完整集成测试

启动一个本地 PostgreSQL：

```bash
docker run --rm --name hermes-p0-postgres \
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
| [Conformance Test Specification](docs/specs/Hermes_Conformance_Test_Spec_V1.0.md) | 一致性测试、故障注入与阶段门槛 |
| [Architecture Decision Index](ARCHITECTURE_DECISIONS.md) | 规范优先级、ADR 状态与待决问题 |

当文档之间出现冲突时，请遵循 [Architecture Decision Index](ARCHITECTURE_DECISIONS.md) 中定义的 authority order，而不是依据文件名或版本号自行推断。

## 设计边界

当前实现有意保持窄而严格：

- PostgreSQL 是 MVP 的权威状态与并发协调点；当前不引入 Kafka、Redis 或 Kubernetes。
- 系统使用 authoritative state + immutable event log + transactional outbox，不采用 full event sourcing。
- 投递语义是 at-least-once；业务 effect 依靠 inbox/idempotency 保证不重复。
- `supporting_refs` 只提供事实定位线索，不构成权限或状态迁移依据。
- 生产部署必须为 Control Plane、Relay、Consumer、Redrive、Worker 和只读访问使用不同登录身份，并只授予对应 capability role。

## License

本项目使用 [Apache License 2.0](LICENSE)。
