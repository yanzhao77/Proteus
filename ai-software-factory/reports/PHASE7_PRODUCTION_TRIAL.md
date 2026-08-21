# Phase 7 报告 — 生产试运行（React + FastAPI + PostgreSQL + Docker）

> 日期：2026-08-21 · 状态：**DELIVERED**（rev 18）· 项目 p-001 真实可运行

## 验收矩阵（规格书 §37）
| 交付物 | 状态 | 证据 |
|---|---|---|
| 源码 | ✅ | workspace/backend + frontend（独立 git 仓库，8 次提交） |
| Dockerfile | ✅ | backend/Dockerfile（python:3.11-slim 多阶段非 root）、frontend/Dockerfile（node→nginx） |
| docker-compose.yml | ✅ | db(PG16) + api + web，健康检查齐备 |
| README.md | ✅ | 快速开始/本地开发/API 摘要 |
| API 文档 | ✅ | api-spec.yaml（OpenAPI 3.0.3）+ 运行中 /docs |
| DB Schema | ✅ | database-schema.sql（PG 方言 + 索引/外键） |
| 测试报告 | ✅ | test-gate.md（pytest 63 passed） |
| 安全报告 | ✅ | security-report.md（25 项检查，PASS，0 高/中危） |
| 构建报告 | ✅ | build-report.md（10 项清单全部 [x]） |
| 发布说明 | ✅ | release-notes.md（0.1.0，含部署/回滚指引） |
| **可真实运行** | ✅ | docker compose up：注册/登录/建待办(due_date)/列表/Web 页面/代理/鉴权全部通过；db 重启数据持久化验证 |

## 生产试运行暴露并修复的问题（Evidence over claims 的终极验证）
1. **PERM-01**：子代理 write 工具产出 600 权限源码 → 容器非 root 无法读取 → chmod 规范化 + 重建镜像
2. **PG-01**：`done` 列 `server_default=text("0")` 在 PostgreSQL 报 DatatypeMismatch（SQLite 不报）→ 改 Python 侧 default=False（方言无关红线被实测捕获，SQLite 63 测试仍全绿）
3. **INFRA-01**：Docker Hub 直连不可达（auth.docker.io 超时）→ 经 dockerproxy.net 镜像源拉取基础镜像并重打标签（postgres/python/node/nginx）
4. **INFRA-02**：外部 git 操作（GitHub Desktop 自动 stash）卷走未提交子代理产物 → 从 stash 外科恢复 + 即时提交（教训：产物必须逐阶段提交）

## 运行拓扑
```
browser → web(nginx:8080, SPA + /api/ 同源代理) → api(FastAPI:8000, JWT) → db(PostgreSQL 16)
```
- 前端构建时 VITE_API_BASE_URL="" → 同源代理免 CORS
- api 健康检查 python urllib；db 健康检查 pg_isready
- 数据卷 db-data 持久化（重启验证 PASS）
