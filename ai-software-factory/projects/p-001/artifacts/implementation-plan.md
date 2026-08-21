# 实施计划（Implementation Plan）— p-001 Todo SaaS

## 里程碑
| M | 目标 | 完成标准 |
|---|---|---|
| M1 | 后端（FastAPI + SQLite）：认证 + Todo CRUD | pytest 全绿，API 文档可访问 |
| M2 | 前端（React + Vite）：登录/注册/待办页 | npm build 通过 |
| M3 | 集成 + Review + Gate | 冒烟通过，Review approve |
| M4（Phase 7） | PostgreSQL + Docker 部署 | docker compose up 后全流程可用 |

## 任务拆解（DAG：t-001 → t-002 → t-003/t-004 → t-005/t-006）
| 任务 | 依赖 | 角色 | 验收 | 状态 |
|---|---|---|---|---|
| t-001 后端骨架 + 配置 | - | backend | app 可启动，/health 200 | pending |
| t-002 认证（注册/登录 + JWT） | t-001 | backend | US-001/002 通过测试 | pending |
| t-003 Todo CRUD API | t-002 | backend | US-003 通过测试 | pending |
| t-004 后端测试套件 | t-002, t-003 | qa | pytest 全绿（含 401/404 边界） | pending |
| t-005 前端骨架 + 登录注册页 | t-002 | frontend | npm build 通过 | pending |
| t-006 前端待办页 + API 集成 | t-005 | frontend | 构建通过，联调冒烟 | pending |
| t-007 代码 Review | t-003, t-006 | review | approve 或 request-changes | pending |

## 阶段预算（预算账本，memory/budget.json 维护）
| 阶段 | 预算 | 实际 |
|---|---|---|
| planning | $1 | 待记账 |
| development | $10 | 待记账 |
| testing | $4 | 待记账 |
| security | $2 | 待记账 |
| release | $1 | 待记账 |

## 风险清单
| 风险 | 影响 | 缓解 |
|---|---|---|
| Python 3.9 系统环境缺依赖 | 高 | 用 venv 隔离，requirements.txt 锁定 |
| SQLite → PostgreSQL 切换 | 中 | SQLAlchemy 方言无关写法 + Phase 7 迁移脚本 |
| 前端联调跨域 | 中 | CORS 白名单 + 本地代理 |
