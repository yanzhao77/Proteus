<div align="center">

# Proteus

### An autonomous software factory with explicit authority, durable recovery, and evidence-backed delivery.

把一个想法推进为可审阅的计划、受控的执行，以及由独立验证和证据支撑的软件交付。

[![License](https://img.shields.io/badge/license-Apache--2.0-2ea44f.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776ab.svg)](hermes-runtime/requirements.txt)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-14%2B-4169e1.svg)](docs/DEVELOPER_GUIDE.md)
[![Frontend](https://img.shields.io/badge/React-TypeScript-149eca.svg)](frontend/README.md)

[快速开始](#快速开始) · [系统如何工作](#系统如何工作) · [交付状态](#交付状态) · [架构边界](#架构边界) · [文档导航](#文档导航)

</div>

---

## Proteus 是什么

Proteus 是 **Hermes Autonomous Software Factory** 的产品与核心运行时仓库。它解决的不是“让 Agent 多生成一些代码”，而是如何把规划、执行、验证和恢复组织成一条可靠的软件生产线。

在 Proteus 中，Agent 可以提出意图，Worker 可以执行任务，但只有 Control Plane 能提交权威状态。任务是否完成不由 Worker 自述决定，而由独立 Verification、Artifact hash 和 Evidence 共同证明。失败也不是流程终点：它会进入诊断、恢复和重新规划闭环。

| 原则 | Proteus 的保证 |
| --- | --- |
| **Authority first** | 所有状态变更通过带版本、身份、原因和幂等键的语义命令完成。 |
| **Evidence over claims** | Worker 不能宣布自己成功；最终结论必须绑定独立验证和可追溯证据。 |
| **Autonomous by default** | 系统持续观察、诊断、规划、执行和验证，人类只在风险与例外处介入。 |
| **Fail closed** | 身份、权限、版本、配置或来源事实不完整时，系统拒绝推进而不是猜测。 |
| **Recovery is a protocol** | Receipt、Outbox、Lease、Fencing、Checkpoint 和 Reconcile 让崩溃恢复可证明。 |
| **One source of truth** | UI、模型、Worker、Verifier 和遥测都不能成为第二套 Project/Task authority。 |

## 系统如何工作

Proteus 将“进入工厂”和“在工厂中执行”分成两条清晰衔接的链路：

```mermaid
flowchart LR
    I["Human idea"] --> D["E1 EntryDraft"]
    D --> U["E2 Understanding"]
    U --> M["E3 Proposal + Master Plan"]
    M --> A["E4 Explicit approval"]
    A --> B["Durable Approval Bridge"]
    B --> P["Project + Task DAG + Verification Plans"]

    P --> S["Situation + Diagnosis"]
    S --> C["Candidate actions"]
    C --> R["Policy + Risk + Budget"]
    R --> Q["Decision + Reservation"]
    Q --> X["ExecutionRequest"]
    X --> L["Queue + Lease + Fencing"]
    L --> W["Worker + Sandbox"]
    W --> V["Independent Verification"]
    V --> E["Artifact + Evidence"]
    V -. "failure feedback" .-> S
```

批准之前，Entry 只能产生版本化的 Draft、Understanding、Proposal 和 Master Plan。只有 E4 Approval Bridge 可以调用既有 Control Plane 命令，将获批计划确定性地物化为 Project、Task Graph 和 Verification Plan。它采用 receipt-first、确定性 child command ID 和可重启 reconcile，避免重复 Project 或部分失败后的原始回滚。

## 交付状态

### Production Entry

| 阶段 | 状态 | 已交付能力 |
| --- | --- | --- |
| **E1 · EntryDraft** | **PASS** | creator-scoped Draft、不可变 revision、版本并发与幂等命令。 |
| **E2 · Understanding** | **PASS** | typed clarification、assumption、source freshness 与领域校验。 |
| **E2.x · Producer Integration** | **PASS — NON-PRODUCTION** | server-side OpenAI-compatible producer；受控 live smoke 与 same-key replay 已验证。 |
| **E3 · Proposal / Master Plan** | **PASS / COMPLETE** | 确定性 Proposal、Master Plan、hash、revision 与 creator isolation。 |
| **E4 · Approval Bridge** | **PASS / COMPLETE** | receipt-first durable saga，经既有 Control Plane ports 幂等物化。 |
| **E5–E7 · Product Experience** | **PASS / COMPLETE** | Source-derived Product API/read model、production-real-API Factory Home resume、read-only Live Production snapshot/live-feed。 |
| **E8 · Production Entry Trial** | **PASS / COMPLETE** | 同一项目的真实 E4→P6→E7 纵向验收已合并；E9–E11 Global Product Workspace 正在独立交付。 |

### Control Plane

| 阶段 | 状态 | 核心范围 |
| --- | --- | --- |
| **P0** | **COMPLETE** | Project/Task authority、DAG、Verification、Event/Outbox 与命令幂等。 |
| **P1** | **COMPLETE** | Situation、Diagnosis、Planning、Policy、Risk、Budget、Selection 与 Reservation。 |
| **P2** | **COMPLETE** | Execution admission、Queue、Scheduler、Lease、Fencing、Worker 与 result admission。 |
| **P3** | **COMPLETE** | Human Gate、Checkpoint/Replay/Reconcile、Quarantine、Evidence invalidation 与 Docker execution。 |
| **P4** | **COMPLETE** | Product API、Artifact/Secret/Retention、Observability 与产品化安全边界。 |
| **P5** | **COMPLETE** | FastAPI、OIDC、runtime supervisor、S3/Vault/OTLP adapters 与单节点部署。 |
| **P6** | **COMPLETE / REVALIDATED** | Autonomous trial通过；Recovery runtime least-privilege gate已关闭。 |

最新封存的 E8 验收包括：fresh migration **0001 → 0032 PASS**、E8 same-project vertical trial **1/1 PASS**、最终 Full Runtime **705 run / 12 skipped / 0 failures in 429.306 seconds**、frontend **40 PASS / production build PASS / oxlint 0 warnings**，以及 manifest **180 non-self entries / 0 mismatch**。README 只提供概览；当前状态、测试数字和文件哈希的权威来源是 [E2.x/P6 Baseline Manifest](docs/PROTEUS_E2X_P6_BASELINE_MANIFEST.md)。

## 快速开始

完整环境、迁移、服务和故障排查说明见 [开发搭建操作手册](docs/DEVELOPER_GUIDE.md)。下面是最短的本地开发路径。

### 环境要求

- Python 3.9+
- PostgreSQL 14+（authority、并发与权限测试需要）
- Docker（推荐，用于 disposable PostgreSQL 和外部适配器）
- Node.js 与 pnpm（Factory Home frontend需要）

### 1. 运行后端测试

```bash
cd hermes-runtime
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# 无数据库发现：PostgreSQL测试会明确 skipped
PYTHONPATH=src python -m unittest discover -s tests
```

没有数据库的 skipped 不能作为 PostgreSQL authority、并发或权限验收证据。完整回归需要真实 PostgreSQL：

```bash
docker run --rm --name hermes-dev-postgres \
  -e POSTGRES_PASSWORD=hermes \
  -e POSTGRES_DB=hermes_test \
  -p 55432:5432 \
  -d postgres:16-alpine

HERMES_TEST_DATABASE_URL='postgresql://postgres:hermes@127.0.0.1:55432/hermes_test' \
  PYTHONPATH=src python -m unittest discover -s tests
```

### 2. 应用迁移并启动 API

```bash
cd hermes-runtime

HERMES_DATABASE_URL='postgresql://postgres:hermes@127.0.0.1:55432/hermes_test' \
  PYTHONPATH=src python -m hermes_runtime.migration_bootstrap

HERMES_DATABASE_URL='postgresql://postgres:hermes@127.0.0.1:55432/hermes_test' \
  PYTHONPATH=src python -m uvicorn hermes_runtime.api_main:app \
  --host 127.0.0.1 --port 8000 --reload
```

服务端未配置数据库或 OIDC verifier 时，受保护的 Product API capability会保持 fail closed。不要用浏览器 actor header、fixture identity或inline secret绕过该边界。

### 3. 启动 Factory Home

```bash
cd frontend
pnpm install
pnpm dev
```

Vite默认将Product API请求代理到 `http://127.0.0.1:8000`。纯视觉开发可显式运行 `VITE_PROTEUS_DEMO=true pnpm dev`；该模式带有醒目的 Demo标识，不能作为真实 authority evidence。

Frontend验证：

```bash
pnpm test
pnpm build
pnpm lint
```

## 核心能力

| 能力域 | 已实现的关键机制 |
| --- | --- |
| **Authority** | typed semantic commands、expected version、idempotency、CommandReceipt、least-privilege roles。 |
| **Graph** | Project-scoped DAG、cycle rejection、graph version、authority-derived READY。 |
| **Delivery** | immutable Event Log、transactional Outbox、relay lease、DLQ、redrive、Inbox checkpoint。 |
| **Decision** | bounded context、deterministic diagnosis/planning、Policy/Risk、Budget、ActionScore、DecisionRecord。 |
| **Execution** | frozen capability/context/sandbox、ExecutionRequest、Queue、Lease、Fencing、AgentRun。 |
| **Verification** | independent Worker/Verifier identity、Verification Plan、Artifact hash、Evidence validity。 |
| **Recovery** | checkpoint、shadow replay、reconcile findings、bounded retry、feedback/replan、Human Gate。 |
| **Product** | FastAPI、OIDC、creator-scoped Entry、Factory Home shell、S3/Vault/OTLP-compatible adapters。 |

## 架构边界

Proteus 有意保持窄而严格：

- PostgreSQL 是当前权威状态和并发协调点；Kafka、Redis 和 Kubernetes 不是现有运行时前提。
- 系统采用 authoritative state + immutable event log + transactional outbox，而不是 full event sourcing。
- 投递是 at-least-once；业务效果通过 receipt、inbox和idempotency收敛。
- Worker提交CompletionClaim，不提交Task PASS；Verifier产生Verdict，不直接修改Task。
- Human Gate decision是输入事实，Project resume仍需独立的受控应用命令。
- Entry Approval Bridge只调用既有Project/Graph/Verification commands，不直接写child authority tables。
- Metrics、traces、模型输出和UI projection只能解释事实，不能授权状态迁移。
- Secret以server-side handle或file boundary传递，不进入浏览器、日志、receipt或文档。

代码依赖方向同样是单向的：

```text
frontend/                  Product API consumer; no runtime authority
        ↓
FastAPI transport          Parsing, OIDC verification, safe envelopes
        ↓
application/               Use cases, semantic commands, ports, orchestration
        ↓
domain/                    Pure invariants and state machines
        ↑
infrastructure/            PostgreSQL and external adapter implementations
```

## 仓库结构

```text
Proteus/
├── frontend/                    # React + TypeScript Factory Home
├── hermes-runtime/
│   ├── migrations/              # 版本化PostgreSQL schema与权限边界
│   ├── src/hermes_runtime/
│   │   ├── domain/              # 纯领域规则与状态机
│   │   ├── application/         # 用例、commands、ports与编排
│   │   ├── infrastructure/      # PostgreSQL、FastAPI及外部adapters
│   │   └── trial/               # 受控P6 autonomous acceptance harness
│   ├── tests/                   # domain、PostgreSQL、权限与边界测试
│   └── requirements.txt         # pinned Python dependencies
├── deploy/                      # 单节点部署基线与runbook
├── examples/golden-todo/        # P6真实软件交付验收fixture
├── docs/
│   ├── adr/                     # Architecture Decision Records
│   ├── specs/                   # 规范性协议与conformance要求
│   └── evidence/                # 封存验收证据
├── ARCHITECTURE_DECISIONS.md    # authority order与ADR索引
└── README.md
```

代码按 **authority boundary** 而不是框架组织。`domain` 不依赖数据库或Web框架；`application` 定义用例和ports；`infrastructure` 实现事务、权限与外部连接。

## 文档导航

### 从这里开始

| 文档 | 用途 |
| --- | --- |
| [开发搭建操作手册](docs/DEVELOPER_GUIDE.md) | 环境、迁移、测试、服务、部署和故障排查。 |
| [Hermes Runtime README](hermes-runtime/README.md) | 核心运行时模块、命令和测试边界。 |
| [Factory Home README](frontend/README.md) | 前端adapter、Demo隔离和本地运行方式。 |
| [Architecture Decision Index](ARCHITECTURE_DECISIONS.md) | 文档authority order、ADR状态和待决问题。 |

### 架构与规范

| 文档 | 用途 |
| --- | --- |
| [Autonomous Software Factory Architecture](docs/Hermes_Autonomous_Software_Factory_Architecture_V1.0.md) | 产品愿景、系统全景与长期能力模型。 |
| [Core Runtime Design V1.2](docs/Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.2.md) | 核心运行时设计与invariants。 |
| [Runtime Normative Specification](docs/specs/Hermes_Runtime_Normative_Spec_V1.0.md) | authority、ownership、阶段与traceability规范。 |
| [Command & Event Protocol](docs/specs/Hermes_Command_Event_Protocol_V1.0.md) | 命令事务、事件、Outbox、投递与恢复。 |
| [Execution Lease Protocol](docs/specs/Hermes_Execution_Lease_Protocol_V1.0.md) | Lease、Fencing、result admission与accounting。 |
| [P4 Productization Specification](docs/specs/Hermes_P4_Productization_Normative_Spec_V1.0.md) | API、identity、Artifact、Secret、Retention和Observability。 |
| [P5 Deployable Product Specification](docs/specs/Hermes_P5_Deployable_Product_Normative_Spec_V1.0.md) | 单节点产品拓扑、服务和运维边界。 |

### Production Entry

| 文档 | 用途 |
| --- | --- |
| [Production Entry Implementation Plan](docs/PROTEUS_PRODUCTION_ENTRY_IMPLEMENTATION_PLAN_V1.md) | E0–E8路线、authority边界和验收标准。 |
| [E1 Delivery](docs/E1_ENTRY_DRAFT_CORE_DELIVERY_REPORT.md) | EntryDraft authority交付。 |
| [E2 Delivery](docs/E2_ENTRY_UNDERSTANDING_DELIVERY_REPORT.md) | Understanding、clarification和assumption交付。 |
| [E2.x Producer Delivery](docs/E2X_PRODUCER_INTEGRATION_DELIVERY_REPORT.md) | Provider adapter、provenance和内部验收。 |
| [E2.x Live Smoke](docs/E2X_LIVE_PROVIDER_SMOKE_DELIVERY_REPORT.md) | 受控non-production live验证。 |
| [E3 Delivery](docs/E3_PROPOSAL_MASTER_PLAN_DELIVERY_REPORT.md) | Proposal与Master Plan交付。 |
| [E4 Delivery](docs/E4_APPROVAL_BRIDGE_DELIVERY_REPORT.md) | Durable Approval Bridge及crash/reconcile证据。 |

### 验收与证据

| 文档 | 用途 |
| --- | --- |
| [Current Verification Baseline](docs/PROTEUS_E2X_P6_BASELINE_MANIFEST.md) | 当前测试统计、最终状态和non-self SHA inventory。 |
| [P0 Acceptance Matrix](docs/P0_ACCEPTANCE_MATRIX.md) | P0 authority骨架验收。 |
| [P1 Acceptance Matrix](docs/P1_ACTION_SELECTION_ACCEPTANCE_MATRIX.md) | P1决策链与资源预留验收。 |
| [P2 Acceptance Matrix](docs/P2_EXECUTION_ACCEPTANCE_MATRIX.md) | P2 execution admission、lease和worker验收。 |
| [P4 Acceptance Matrix](docs/P4_PRODUCTIZATION_ACCEPTANCE_MATRIX.md) | P4产品化边界验收。 |
| [P5 Acceptance Matrix](docs/P5_DEPLOYABLE_PRODUCT_ACCEPTANCE_MATRIX.md) | P5单节点产品验收。 |

当文档发生冲突时，遵循 [Architecture Decision Index](ARCHITECTURE_DECISIONS.md) 中定义的authority order，而不是依据文件名、日期或版本号自行推断。

## License

Proteus 使用 [Apache License 2.0](LICENSE)。
