# Hermes Runtime 开发搭建操作手册（Developer & Operations Guide）

> 本手册面向要把 Hermes Runtime（Proteus 仓库）**从零搭起来并开始开发**的工程师。
> 覆盖：环境准备 → 安装 → 数据库 → 迁移 → 测试 → 启动服务 → 单节点部署 → 开发流程 → 故障排查。
> 所有命令都在 macOS / Linux（以及 WSL2 的 Windows）上验证过；命令中统一使用仓库内的
> `hermes-runtime/.venv/bin/python`，如使用系统 Python 请自行替换。

---

## 0. 三条快速路径（先看这个）

| 目标 | 最短路径 | 需要什么 |
| --- | --- | --- |
| 只做纯领域开发 / 改 domain 规则 | git clone + venv + 跑 no-DB 测试 | 只要 Python，不需要数据库 |
| 完整本地集成开发（迁移、并发、权限） | 第 3~7 节 | Python + Docker（起一个 PostgreSQL 容器） |
| 单节点产品部署 | 第 9 节 | Docker + Compose（PG/MinIO/Vault/OTLP 全套） |

如果你只是想把代码跑起来看 API 和测试，按顺序走 第 1 → 2 → 3 → 4 → 7.2 → 8.1 即可。

---

## 1. 项目是什么（30 秒速览）

Hermes Runtime 是一个"自主软件工厂"的权威控制平面实现：Agent/Worker 可以提出执行意图，
但只有 Control Plane 能提交权威状态；所有状态变更必须有证据、命令必须幂等、事件可重放、
失败进入诊断/修复/重规划闭环。

核心链路：

```text
Event → Situation → Diagnosis → CandidateAction → Policy/Risk → Budget/ActionScore
      → DecisionRecord + Reservation → ExecutionRequest → Queue/Lease/Fencing
      → Worker + Sandbox → Artifact + Evidence → 独立 Verification → Feedback → Event
```

代码按 authority boundary 组织（不是按技术框架）：

```text
hermes-runtime/
├── migrations/            # 22 个版本化 PostgreSQL schema + 权限边界（0001..0022）
├── src/hermes_runtime/
│   ├── domain/            # 纯领域规则、状态机、枚举（禁止 import 任何 DB/Web 框架）
│   ├── application/       # 用例、命令、ports、authority 编排
│   └── infrastructure/    # PostgreSQL adapters、FastAPI、Docker/S3/Vault/OTLP adapters
├── tests/                 # 单元 + PG 集成 + 权限 + 架构边界测试（497 个）
├── scripts/               # 辅助脚本（如 P5 UI 截图）
└── requirements.txt       # 全部第三方依赖（pinned）
```

阶段状态：P0（权威骨架）→ P1（自治决策链）→ P2（执行权威链）→ P3（运维治理 runtime）
→ P4（产品化边界）→ P5（单节点可部署产品，已含真实外部 smoke 证据）全部完成。
详见 [Hermes_P5_COMPLETION_SUMMARY.md](Hermes_P5_COMPLETION_SUMMARY.md)。

---

## 2. 环境要求

| 项 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | macOS / Linux / Windows (WSL2) | 未在原生 Windows 验证，建议 WSL2 |
| Python | 3.9+（推荐 3.11） | 代码保持 3.9 兼容；Dockerfile 用 3.11 |
| PostgreSQL | 14+（14 或 16 均可） | 仅集成测试需要；生产/Compose 用 16 |
| Docker | 可选但强烈推荐 | 一键起 PG、跑外部适配器测试、Compose 部署 |
| 磁盘 | 仓库 <100MB；Docker 镜像另计 | |
| 内存 | 2GB+；跑全部外部容器建议 4GB+ | |

> Docker 不是必须的：没有 Docker 也能做纯领域开发（第 7.1/7.2 节），
> 只是跑不了 PostgreSQL 集成测试与外部适配器测试。

---

## 3. 获取代码

```bash
git clone https://github.com/yanzhao77/Proteus.git
cd Proteus
```

确认关键目录存在：

```bash
ls hermes-runtime/migrations | head -3   # 0001_p0_completion_verification.sql ...
ls hermes-runtime/migrations | wc -l     # 22
ls hermes-runtime/src/hermes_runtime/domain | head
```

---

## 4. 安装 Python 环境

### 4.1 创建虚拟环境

```bash
cd Proteus/hermes-runtime
python3 -m venv .venv
source .venv/bin/activate        # Windows (WSL2) 同样适用
```

> 仓库自带的 .venv 若与你的系统 Python 不匹配，建议删除重建：
> rm -rf hermes-runtime/.venv 后重新执行上面命令。

### 4.2 安装依赖

```bash
pip install -r requirements.txt
```

依赖清单（全部 pinned）：

```text
psycopg[binary]==3.2.13     # PostgreSQL 驱动（Psycopg 3）
fastapi==0.115.6            # P5 API 传输层
pydantic==2.10.4
uvicorn==0.32.1             # ASGI 服务器
httpx==0.28.1               # API 测试 / OTLP 导出
PyJWT[crypto]==2.10.1       # OIDC JWT 验证
cryptography==44.0.0
jinja2==3.1.6               # Human Gate UI 渲染
boto3==1.35.99              # S3-compatible Artifact 适配器
hvac==2.3.0                 # Vault KV-v2 Secret 适配器
```

### 4.3 验证安装

```bash
python -c "import psycopg, fastapi, pydantic, uvicorn, httpx, jwt, cryptography, jinja2, boto3, hvac; print('all deps OK')"
```

### 4.4 （可选）Playwright，用于重新生成 P5 UI 截图证据

```bash
pip install playwright
# 需要本机装有 Google Chrome（脚本使用 channel="chrome"，不下载浏览器）
```



---

## 5. 启动 PostgreSQL

### 方式 A：Docker 一次性容器（推荐，开发用）

```bash
docker run --rm --name hermes-dev-postgres -e POSTGRES_PASSWORD=hermes -e POSTGRES_DB=hermes_test -p 55432:5432 -d postgres:16-alpine
```

- 端口 55432 是仓库约定，避免与本机 5432 冲突（README/CI 均使用它）。
- 换 PostgreSQL 14：把镜像改成 postgres:14-alpine（同一套迁移在 14/16 上都验证过）。
- 停止并删除容器：docker rm -f hermes-dev-postgres。

验证连接：

```bash
docker exec hermes-dev-postgres pg_isready -U postgres -d hermes_test
# 输出: /var/run/postgresql:5432 - accepting connections
```

### 方式 B：本地 PostgreSQL（Homebrew / apt / 其他）

```bash
# macOS Homebrew 示例
brew install postgresql@16
brew services start postgresql@16
createdb hermes_test
psql -d hermes_test -c "ALTER USER postgres WITH PASSWORD 'hermes';"
```

> 无论哪种方式，只要最终有一个可连接的 DSN 即可：
> postgresql://postgres:hermes@127.0.0.1:55432/hermes_test

### 方式 C：完整 Compose 环境（PG + MinIO + Vault + OTLP，见第 9 节）

---

## 6. 运行数据库迁移

### 6.1 一键执行全部迁移（推荐）

```bash
cd Proteus/hermes-runtime
HERMES_DATABASE_URL='postgresql://postgres:hermes@127.0.0.1:55432/hermes_test' PYTHONPATH=src .venv/bin/python -m hermes_runtime.migration_bootstrap
```

- 入口会按文件名顺序（0001→0022）执行 migrations/*.sql，可重复执行（全部 IF NOT EXISTS）。
- 每条 SQL 文件独立事务，中途失败会回滚该文件。

### 6.2 验证迁移结果

```bash
docker exec hermes-dev-postgres psql -U postgres -d hermes_test -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
# 约 140+ 张表（具体数量以你的库为准）

docker exec hermes-dev-postgres psql -U postgres -d hermes_test -c "SELECT rolname FROM pg_roles WHERE rolname LIKE 'hermes%' ORDER BY 1;" | head
# hermes_authority_owner, hermes_control_plane_runtime, hermes_worker_runtime, ...
```

迁移完成后你会看到三类对象：

- 表：权威状态表（projects、tasks、execution_requests …）、事件表（event_log、outbox_messages、command_receipts）、不可变快照表（decision_records、execution_results …）
- 角色：52 个 hermes_* NOLOGIN 能力角色（hermes_control_plane_runtime、hermes_worker_runtime、hermes_selection_runtime …）
- 函数：142 个 hermes_* 守卫函数（SECURITY DEFINER，search_path=pg_catalog）

> 迁移约定（ADR-0019）：只用原生 SQL 文件 + Psycopg 3，不用 ORM/Alembic。
> 迁移编号必须连续（当前 0001–0022）；新迁移请用下一个编号，并保持连续性检查。

### 6.3 常见错误

| 错误 | 原因 | 解决 |
| --- | --- | --- |
| RuntimeError: HERMES_DATABASE_URL_REQUIRED | 没设置 DSN | 设置 HERMES_DATABASE_URL（或 HERMES_DATABASE_URL_FILE） |
| psycopg.OperationalError: connection refused | PG 没启动 / 端口不对 | 检查容器状态与端口 |
| server_version_num < 140000 | PG 版本低于 14 | 换 PG 14/16 镜像 |

---

## 7. 运行测试

测试全部使用标准库 unittest（无 pytest）。目录下共 497 个测试，按是否连数据库分为三层：

| 层 | 需要 | 数量 | 典型文件 |
| --- | --- | --- | --- |
| 纯领域单元测试 | 无 | ~199 | test_*_domain.py |
| PostgreSQL 集成/并发/权限 | PG 14+ | ~291 | test_*_postgres.py / test_*_permissions.py |
| 外部适配器集成 | MinIO/Vault/OTLP 容器 | 7 | test_s3_artifact_integration.py 等 |

### 7.1 纯领域测试（不需要数据库，最快）

```bash
cd Proteus/hermes-runtime
PYTHONPATH=src .venv/bin/python -m unittest tests.test_domain_authority -v
```

跑 README 推荐的核心领域集：

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_domain_authority tests.test_graph_domain tests.test_project_domain tests.test_resource_accounting_domain tests.test_situation_domain tests.test_diagnosis_domain tests.test_planner_domain tests.test_policy_domain tests.test_risk_domain tests.test_selection_domain tests.test_architecture_boundaries -v
```

### 7.2 no-DB 全量发现（含跳过）

```bash
cd Proteus/hermes-runtime
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

预期输出（2026-08-17 验证）：

```text
Ran 497 tests in 0.6s
OK (skipped=298)
```

为什么跳过 298 个：未设置 HERMES_TEST_DATABASE_URL 时，PG 集成测试通过
@unittest.skipUnless 跳过。这是设计行为，且跳过不计为验收证据（详见 ADR-0020
Implementation note：直接运行单个 postgres 测试模块会 fail closed 报错）。

### 7.3 PostgreSQL 集成测试（完整回归）

```bash
cd Proteus/hermes-runtime
HERMES_TEST_DATABASE_URL='postgresql://postgres:hermes@127.0.0.1:55432/hermes_test' PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

预期输出（本机实测）：

```text
Ran 497 tests in 186s
OK (skipped=12)
```

- skipped=12 = 5（其他环境相关）+ 7（外部适配器测试未设 env）。
- 设置了外部适配器 env 后为 skipped=5（与 P5 摘要记录一致）。
- 全程约 3 分钟，覆盖迁移、并发、故障注入、权限、不可变记录等。

### 7.4 外部适配器集成测试（真实 MinIO / Vault / OTLP Collector）

先起三个容器（命令与 CI external-adapters job 一致）：

```bash
docker run -d --name hermes-ci-minio -e MINIO_ROOT_USER=hermesminio -e MINIO_ROOT_PASSWORD=hermesminio-secret -p 19000:9000 minio/minio@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e server /data
docker run -d --name hermes-ci-vault --cap-add IPC_LOCK -e VAULT_DEV_ROOT_TOKEN_ID=hermes-vault-dev-token -p 18200:8200 hashicorp/vault:1.17
docker run -d --name hermes-ci-otel -p 14318:4318 otel/opentelemetry-collector:0.104.0
```

> 注意：MinIO 使用 digest 固定镜像（之前引用的 RELEASE tag 在 Docker Hub 不存在），不要改回 tag。

跑测试：

```bash
cd Proteus/hermes-runtime
HERMES_TEST_S3_URL=http://127.0.0.1:19000 HERMES_TEST_S3_ACCESS_KEY=hermesminio HERMES_TEST_S3_SECRET_KEY=hermesminio-secret HERMES_TEST_VAULT_URL=http://127.0.0.1:18200 HERMES_TEST_VAULT_TOKEN=hermes-vault-dev-token HERMES_TEST_OTLP_ENDPOINT=http://127.0.0.1:14318/v1/traces PYTHONPATH=src .venv/bin/python -m unittest tests.test_s3_artifact_integration tests.test_vault_secret_integration tests.test_otlp_collector_integration -v
```

预期：7 个测试全 PASS（S3×4、Vault×1、OTLP×2）。Vault 测试可能打印 hvac 的
DeprecationWarning，无碍。

用完后清理：

```bash
docker rm -f hermes-ci-minio hermes-ci-vault hermes-ci-otel
```

### 7.5 单模块 / 聚焦测试

```bash
cd Proteus/hermes-runtime
PYTHONPATH=src .venv/bin/python -m unittest tests.test_selection_domain -v
PYTHONPATH=src .venv/bin/python -m unittest tests.test_fastapi_service_host tests.test_oidc_and_human_gate_ui -v
```

### 7.6 测试约定（开发时必须遵守）

- 命名：领域 test_*_domain.py、PG test_*_postgres.py、权限 test_*_permissions.py、架构 test_architecture_boundaries.py、P5 test_*_product*。
- 跳过/模拟不算验收证据：验收矩阵只认真实 PG、真实 Docker、真实外部容器跑出来的 PASS。
- 并发/故障注入测试必须用独立数据库连接 + 确定性屏障（见 Conformance Spec）。
- domain 层禁止 import fastapi/uvicorn/psycopg/boto3/jwt 等（有 test_architecture_boundaries 把关）。
- 每改一个 authority 行为，至少补：纯领域测试 + PG 集成/并发测试 + 权限测试。



---

## 8. 启动运行时服务

### 8.1 API（FastAPI）

```bash
cd Proteus/hermes-runtime
HERMES_CORS_ORIGINS="" HERMES_DATABASE_URL='postgresql://postgres:hermes@127.0.0.1:55432/hermes_test' PYTHONPATH=src .venv/bin/python -m uvicorn hermes_runtime.api_main:app --host 0.0.0.0 --port 8080 --reload
```

- --reload 开发热重载；生产不要加。
- 未设置 HERMES_DATABASE_URL 也能启动，但 /readyz 会报 database: NOT_READY。

路由清单（全部为 allowlisted 语义路由，无通用 PATCH/状态编辑）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /livez | 存活探针 |
| GET | /readyz | 就绪探针（DB/迁移/依赖/supervisor） |
| GET | /projects/{project_id}/status | 项目状态只读模型 |
| GET | /decisions/{decision_id}/explain | 决策 Explain |
| GET | /human-gates/{gate_request_id} | Gate 详情 |
| POST | /human-gates/{gate_request_id}/decisions | 提交 Gate 决策（需 Idempotency-Key + JSON） |
| GET | /projects/{project_id}/reconcile-findings | Reconcile 发现 |
| GET | /docker-processes/{process_id}/observations | Docker 进程观测 |
| GET | /ui/human-gates、/ui/human-gates/{id} | Human Gate UI（HTML） |

实测输出示例：

```bash
curl -s http://127.0.0.1:8080/livez
# {"status":"LIVE"}

curl -s http://127.0.0.1:8080/readyz
# {"ready":true,"database":"READY","migrations":"COMPATIBLE","dependencies":"READY","supervisor":"READY"}

curl -s http://127.0.0.1:8080/projects/proj-1/status
# {"data":{"project_id":"proj-1","state_summary":"UNAVAILABLE_UNTIL_CONFIGURED"},"error":null,"request_id":"req-missing"}

# 缺少 Idempotency-Key 会被拒绝（幂等约束）
curl -s -X POST -H "Content-Type: application/json" -d '{"command_id":"c1","expected_version":0,"actor":{"type":"user","id":"u1"},"reason":"t","decision":"APPROVE"}' http://127.0.0.1:8080/human-gates/g-1/decisions
# {"detail":"API_IDEMPOTENCY_KEY_MISSING"}
```

> 注意：默认 api_main 使用 EmptyReadModel + RejectingGateway（无真实数据源时返回
> UNAVAILABLE_UNTIL_CONFIGURED / REJECTED）。要让 API 真正读写权威状态，需要把真实
> store/facade 注入 create_app()（参考 infrastructure/fastapi_app.py 与
> application/product_api.py）——这是产品集成层的职责，P5 只保证传输边界。

### 8.2 Runtime Supervisor（常驻服务循环）

```bash
cd Proteus/hermes-runtime
HERMES_DATABASE_URL='postgresql://postgres:hermes@127.0.0.1:55432/hermes_test' HERMES_SERVICE_BATCH_SIZE=100 HERMES_SERVICE_POLL_SECONDS=1.0 PYTHONPATH=src .venv/bin/python -m hermes_runtime.supervisor_main
```

- 负责 5 个有界循环角色：relay、consumer-checkpoint、scheduler-lease、docker-worker、reconcile。
- 当前实现为循环框架 + 占位 handler（真正的循环体需注入数据库适配器；多实例安全靠
  PG lease/fencing/idempotency，不靠进程内锁——这是设计声明，不是缺陷）。
- 环境变量：HERMES_SERVICE_BATCH_SIZE（默认 100）、HERMES_SERVICE_POLL_SECONDS（默认 1.0）。

### 8.3 Outbox Relay（一次性批次发布）

```bash
cd Proteus/hermes-runtime
HERMES_DATABASE_URL='postgresql://postgres:hermes@127.0.0.1:55432/hermes_test' PYTHONPATH=src .venv/bin/python -m hermes_runtime.relay_once --owner relay-1 --batch-size 100 --lease-seconds 30 --max-attempts 5
```

- 只跑一个批次（PENDING → LEASED → PUBLISHED 状态机 + DLQ），不是常驻进程。
- 参数：--owner（必填，租约持有者标识）、--batch-size（100）、--lease-seconds（30）、--max-attempts（5）。

### 8.4 停止服务

```bash
# 前台运行的服务：Ctrl+C
# 后台/测试容器：
docker rm -f hermes-dev-postgres hermes-ci-minio hermes-ci-vault hermes-ci-otel 2>/dev/null
```

---

## 9. 单节点产品部署（Docker Compose）

拓扑：postgres（权威） + migration-bootstrap（一次性） + api + runtime-supervisor
+ minio + vault + otel-collector。

### 9.1 创建 secret 文件（Compose 引用，必须 operator 自建，不入 Git）

```bash
cd Proteus/deploy/p5
mkdir -p secrets
echo 'change-me-bootstrap-password' > secrets/postgres_bootstrap_password.txt
echo 'postgresql://hermes_bootstrap:change-me-bootstrap-password@postgres:5432/hermes' > secrets/hermes_database_url.txt
echo 'hermesminio' > secrets/minio_root_user.txt
echo 'change-me-minio-password' > secrets/minio_root_password.txt
echo 'change-me-vault-dev-token' > secrets/vault_dev_token.txt
chmod 600 secrets/*
```

> 生产环境请使用真正的密钥管理系统生成并注入这些值；不要提交任何真实凭据。

### 9.2 构建并启动

```bash
cd Proteus/deploy/p5
docker compose up -d --build
```

- postgres 健康后，migration-bootstrap 一次性跑完 22 个迁移并退出；
- 然后 api 与 runtime-supervisor 启动。

### 9.3 验证部署

```bash
docker compose ps
# NAME                    STATUS
# p5-api-1                 Up
# p5-runtime-supervisor-1  Up
# p5-postgres-1            Up (healthy)
# p5-migration-bootstrap-1 Exited (0)

curl -s http://127.0.0.1:8080/livez
# {"status":"LIVE"}
curl -s http://127.0.0.1:8080/readyz
# {"ready":true,"database":"READY",...}
```

### 9.4 常用运维命令

```bash
docker compose logs -f api
docker compose logs migration-bootstrap
docker compose restart api
docker compose down
docker compose down -v        # 停止并删除卷（数据全清，慎用）
```

备份/恢复/回滚/密钥轮换：见 [P5_SINGLE_NODE_RUNBOOK.md](operations/P5_SINGLE_NODE_RUNBOOK.md)
（权威表用 PG 原生逻辑备份；恢复先库后对象再验 hash；不回滚权威 schema、不手改权威表）。

---

## 10. 配置参考

### 10.1 运行时环境变量

| 变量 | 服务 | 用途 |
| --- | --- | --- |
| HERMES_DATABASE_URL | api / supervisor / migration / relay | PostgreSQL DSN |
| HERMES_DATABASE_URL_FILE | api / supervisor / migration | 存有 DSN 的 secret 文件路径（Compose 默认） |
| HERMES_CORS_ORIGINS | api | 允许的 CORS 源，逗号分隔（空 = 无） |
| HERMES_SERVICE_BATCH_SIZE | supervisor | 每循环批次大小（默认 100） |
| HERMES_SERVICE_POLL_SECONDS | supervisor | 循环轮询间隔（默认 1.0） |

env_or_file 语义：HERMES_X 优先，否则读 HERMES_X_FILE 指向的文件内容（自动 strip）。

### 10.2 测试环境变量

| 变量 | 用途 |
| --- | --- |
| HERMES_TEST_DATABASE_URL | PG 集成测试 DSN（不设置则 PG 测试跳过） |
| HERMES_TEST_S3_URL / HERMES_TEST_S3_ACCESS_KEY / HERMES_TEST_S3_SECRET_KEY | MinIO 集成测试 |
| HERMES_TEST_VAULT_URL / HERMES_TEST_VAULT_TOKEN | Vault 集成测试 |
| HERMES_TEST_OTLP_ENDPOINT | OTLP Collector 集成测试 |

### 10.3 端口

| 服务 | 容器端口 | 默认宿主端口 |
| --- | --- | --- |
| postgres | 5432 | 5432（开发容器用 55432） |
| api | 8080 | 8080 |
| minio | 9000 | 9000（CI/测试用 19000） |
| vault | 8200 | 8200（CI/测试用 18200） |
| otel-collector | 4318 | 4318（CI/测试用 14318） |



---

## 11. 开发指南

### 11.1 Authority Boundary（写代码前必读）

| 层 | 职责 | 禁止 |
| --- | --- | --- |
| domain/ | 纯规则、状态机、枚举、校验 | import DB/Web/Docker/LLM 客户端；做任何 I/O |
| application/ | 用例/命令编排、ports 接口 | 直接写 SQL、直接依赖具体 adapter |
| infrastructure/ | PG 事务、权限、Docker/S3/Vault/OTLP 实现 | 绕过 domain 规则；暴露未受控写路径 |

核心权威边界（体现在代码与测试中）：

- Worker 不能宣布自己成功，Verification 是唯一 PASS/FAIL 生产者；
- Verifier 不能改 Task 状态，只有 Control Plane 命令能提交状态迁移；
- 所有权威写操作走守卫 SQL 函数（SECURITY DEFINER、hermes_* 前缀、NOLOGIN owner），
  运行时角色只有执行权没有直接表写权；
- 命令必须携带 command_id / idempotency_key / expected_version / actor / reason；
- 状态变更、Event Log、Outbox、CommandReceipt 同一本地事务提交；
- 任何"缺失"都必须 fail closed（缺 Policy、缺 Evidence、缺 Gate 事实 → 拒绝，绝不隐式放行）。

规范命令名 → SQL 守卫函数映射见 [hermes-runtime/README.md](../hermes-runtime/README.md) 附录。

### 11.2 开发一个新能力 / 切片的标准流程

按 ADR 与验收矩阵的惯例，新切片按这个顺序落地：

1. 写 ADR + 规范 + 验收矩阵行（状态先 SPECIFIED / PLANNED）：
   - 新增 docs/adr/ADR-00XX-<slug>.md（编号连续），并更新 ARCHITECTURE_DECISIONS.md 索引。
2. 写迁移 migrations/00XX_<slug>.sql：
   - 创建 NOLOGIN owner/runtime 角色；表；SECURITY DEFINER 守卫函数（search_path=pg_catalog）；
   - REVOKE ALL ON ... FROM PUBLIC；只给 runtime 角色 EXECUTE；
   - 需要的话加 deferred 约束 / 触发器保证不变量。
3. 实现 domain（纯规则 + 状态机 + 校验 + 错误码），配 test_*_domain.py。
4. 实现 application（命令/用例 + port 接口 + 幂等/expected_version 校验），配应用层测试。
5. 实现 infrastructure（PostgreSQL adapter + 事务 + 权限断言），配 test_*_postgres.py（并发/故障注入）与 test_*_permissions.py（角色权限）。
6. 跑全量验证：no-DB（497 应只增不减跳过数不变）→ PG16 完整回归 →（如涉及外部适配器）外部容器测试；compileall + git diff --check。
7. 更新验收矩阵状态为 PASS 并附证据（测试名/迁移名/命令输出），写完成摘要。

### 11.3 写测试的要点

- 领域测试：构造输入 → 断言状态机结果/错误码，不碰 DB。
- PG 测试：setUpClass 里按序应用全部迁移（见现有 test_*_postgres.py 开头），
  用两个独立连接做并发断言，用事务回滚保证隔离。
- 权限测试：以 hermes_xxx_runtime 角色连接，断言只能执行守卫函数、不能直写表。
- 架构边界测试：test_architecture_boundaries.py 用 AST/字符串扫描保证 domain 无框架 import、
  不存在通用状态修改器。
- 验收矩阵词汇：SPECIFIED（仅契约）/ PLANNED（后续切片）/ PASS（实现+证据）/
  PARTIAL（子集）/ BLOCKED（外部阻塞）。跳过/模拟永远不写 PASS。

### 11.4 常用开发命令速查

```bash
cd Proteus/hermes-runtime
export PYTHONPATH=src

# 快速回归（无 DB）
.venv/bin/python -m unittest discover -s tests 2>&1 | tail -3

# 单测 + 语法 + 空白检查
.venv/bin/python -m unittest tests.test_selection_domain -v
PYTHONPYCACHEPREFIX=/tmp/hermes-pyc .venv/bin/python -m compileall -q src tests
git -C .. diff --check

# PG 回归（需要容器在跑）
HERMES_TEST_DATABASE_URL='postgresql://postgres:hermes@127.0.0.1:55432/hermes_test' .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3

# 起 API
HERMES_DATABASE_URL='postgresql://postgres:hermes@127.0.0.1:55432/hermes_test' .venv/bin/python -m uvicorn hermes_runtime.api_main:app --port 8080 --reload
```

### 11.5 文档规范

- 文档冲突时按 ARCHITECTURE_DECISIONS.md 的 authority order 裁决
  （V1.2 Invariants → 规范 → V1.2 其他设计 → V1.0 → ACCEPTED ADR → 矩阵 → 摘要）。
- 新机制先在 ADR 记录决策，再写代码；改机制先改文档再改代码。

---

## 12. 常见问题排查（FAQ）

| 症状 | 原因 | 解决 |
| --- | --- | --- |
| docker: Cannot connect to the Docker daemon | Docker 没启动 | 启动 Docker Desktop / systemctl start docker |
| failed to build: failed to update builder last activity time ... operation not permitted | Docker Desktop buildx 缓存目录权限问题（macOS） | chmod u+rwx ~/.docker/buildx/activity，或用 DOCKER_BUILDKIT=0 docker build ... |
| 测试几乎全部 s（skipped） | 没设 HERMES_TEST_DATABASE_URL | 按 7.3 设置 DSN（跳过不算验收证据） |
| ModuleNotFoundError: No module named 'hermes_runtime' | 没设 PYTHONPATH=src 或不在 hermes-runtime 目录 | cd hermes-runtime && export PYTHONPATH=src |
| ModuleNotFoundError: No module named 'psycopg' | 依赖没装 | pip install -r requirements.txt |
| psycopg.OperationalError: connection refused | PG 容器没起 / 端口不对 | docker ps 检查；确认 55432 映射 |
| RuntimeError: HERMES_DATABASE_URL_REQUIRED | migration_bootstrap 缺 DSN | 设置 HERMES_DATABASE_URL（或 _FILE） |
| compileall ... PermissionError .../Library/Caches/... | macOS pycache 缓存目录权限 | PYTHONPYCACHEPREFIX=/tmp/hermes-pyc python -m compileall -q src tests |
| 外部适配器测试跳过（7 个） | 容器没起或 env 没设 | 按 7.4 起容器 + 设 HERMES_TEST_* env |
| /readyz 返回 database: NOT_READY | API 进程没配 DB | 启动时设置 HERMES_DATABASE_URL |
| API POST 返回 API_IDEMPOTENCY_KEY_MISSING | 幂等约束（设计如此） | 带 Idempotency-Key header 重试 |
| docker run minio/minio:RELEASE... 拉不到镜像 | 该 tag 在 Docker Hub 不存在 | 用 compose/CI 里 digest 固定版本 |

---

## 13. 参考资料

| 文档 | 内容 |
| --- | --- |
| README.md | 项目总览、能力表、快速开始 |
| hermes-runtime/README.md | 运行时权威边界、命令↔函数映射、测试说明 |
| ARCHITECTURE_DECISIONS.md | ADR 索引 + authority order（冲突裁决） |
| docs/specs/ | 8 份规范性协议（Command/Event、Lease、P2/P3/P4/P5、Conformance） |
| docs/adr/ | 72 份架构决策记录 |
| P5_SINGLE_NODE_RUNBOOK.md | 生产运维：备份/恢复/回滚/轮换/应急 |
| Hermes_P5_COMPLETION_SUMMARY.md | P5 完成范围与验证证据 |

---

*手册基于 2026-08-17 master（P5 外部验收完成）实测编写；命令输出均为本机复现结果。*
