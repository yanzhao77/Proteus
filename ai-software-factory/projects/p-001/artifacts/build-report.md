# p-001 构建报告（Build Report）— Phase 7 生产试运行

> 生成者：AI Software Factory · devops 角色（Phase 7）
> 状态：**文件已产出并通过静态校验；镜像构建与容器启动由 Factory Manager 实跑（下方「待实跑回填」）**

## 1. 产物文件清单

| 文件 | 作用 |
|---|---|
| `workspace/backend/Dockerfile` | api 镜像：python:3.11-slim 多阶段（venv 构建 → 精简运行时），`libpq5`，非 root `appuser`(1000)，`uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| `workspace/frontend/Dockerfile` | web 镜像：node:20-alpine `npm ci` + `npm run build` → nginx:1.27-alpine 托管 `dist/` |
| `workspace/frontend/nginx.conf` | SPA fallback + `/api/`、`/health` 反向代理到 `api:8000`（含 X-Forwarded-* 头） |
| `workspace/docker-compose.yml` | db + api + web 三服务编排；`name: p-001` |
| `workspace/.env.example` | compose 环境模板（SECRET_KEY / POSTGRES_PASSWORD 占位，生产替换） |
| `artifacts/deployment-manifest.yaml` | 部署清单：服务/镜像/端口/卷/env/健康检查 + 部署与回滚指引 |
| 本文件 | 构建命令、产物、校验要点 |

未改动任何 `backend/app/**` 与 `frontend/src/**` 代码。

## 2. 构建命令（Manager 执行）

```bash
cd ai-software-factory/projects/p-001/workspace
cp .env.example .env                      # 生产：填入真实 SECRET_KEY/POSTGRES_PASSWORD
docker compose build                      # 构建 p-001-api / p-001-web
docker compose up -d                      # 启动 db → api → web（含健康依赖）
docker compose ps                         # 三服务均为 healthy
docker compose logs -f api                # 观察启动日志（lifespan init_db 建表）
```

## 3. 构建产物（镜像名）

| 镜像 | 来源 | 说明 |
|---|---|---|
| `p-001-api:latest` | `backend/Dockerfile` 构建 | FastAPI + uvicorn |
| `p-001-web:latest` | `frontend/Dockerfile` 构建 | nginx 静态托管 + 代理 |
| `postgres:16-alpine` | 仓库拉取 | 不构建 |

（compose `name: p-001` → 构建镜像自动命名为 `p-001-api` / `p-001-web`。）

## 4. 关键决策

1. **api 镜像多阶段**：builder 阶段建 venv 装依赖（依赖全部有 wheel，无需编译工具链）；runtime 阶段仅拷贝 venv + 代码，`libpq5` 作为防御性运行时库（psycopg[binary] 自带 libpq），非 root 用户运行。
2. **api 健康检查用 python urllib**（slim 无 curl）：`python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"`；`/health` 即使 DB 降级也返回 200，故该检查验证进程 + HTTP 可达性，DB 连通由 db 的 `pg_isready` + 启动时 `init_db()` 兜底。
3. **CORS_ORIGINS 为逗号分隔字符串**（模板曾用 JSON 数组）：`app/config.py` 按逗号 split，JSON 数组会被当单个 origin，已纠正为 `http://localhost:8080,http://localhost:5173`。
4. **前端走同源代理（生产免 CORS）**：`src/api.js` 用 `VITE_API_BASE_URL ?? 'http://localhost:8000'`；前端 Dockerfile 提供 `ARG VITE_API_BASE_URL=""` 构建时置空 → fetch 相对路径 `/api/v1/*` → nginx 代理到 api。直连 8000 的 dev 模式由 CORS_ORIGINS 覆盖。
5. **DATABASE_URL 用 psycopg 3 驱动**：`postgresql+psycopg://`（requirements 为 `psycopg[binary]`；`.env.example` 注释中的 psycopg2 为遗留文档错误，未沿用）。
6. **表结构自举**：api 启动 lifespan 自动 `init_db()`（create_all），首启即建表；Alembic 尚未引入（架构遗留项，见 manifest hardening_todo）。
7. **secret 无硬编码**：compose 全部 `${VAR:-dev占位}` + 注释生产替换；`SECRET_KEY` 应用层无默认值，缺失即拒绝启动。

## 5. 校验要点（待 Manager 实跑后回填状态）

| # | 校验项 | 命令/期望 | 状态 |
|---|---|---|---|
| 1 | backend 镜像构建 | `docker compose build api` 成功 | ☐ 待实跑 |
| 2 | frontend 镜像构建 | `docker compose build web` 成功 | ☐ 待实跑 |
| 3 | 服务健康 | `docker compose ps` 三服务 healthy | ☐ 待实跑 |
| 4 | API 健康 | `curl http://localhost:8000/health` → `{"status":"ok","database":"ok"}` | ☐ 待实跑 |
| 5 | 代理路径 | `curl http://localhost:8080/api/v1/todos` 未带 token → 401 | ☐ 待实跑 |
| 6 | SPA 回退 | `curl http://localhost:8080/todo` 返回 index.html（200） | ☐ 待实跑 |
| 7 | 业务冒烟 | 浏览器 localhost:8080：注册→登录→建/改/删待办 | ☐ 待实跑 |
| 8 | 数据持久化 | `docker compose restart db` 后数据仍在 | ☐ 待实跑 |
| 9 | 表结构 | `docker compose exec db psql -U app -d app -c '\dt'` 见 users/todos | ☐ 待实跑 |
| 10 | 单元回归 | `docker compose exec api python -m pytest -q`（conftest 用独立 SQLite，容器内可跑） | ☐ 待实跑 |

回填格式示例：`☑ 2024-… 通过` / `☒ 失败原因`。

## 6. 已知风险提示

- `SECRET_KEY` 更换 → 全部 JWT 失效（用户重新登录）。
- 无 Alembic：表结构变更无迁移路径，上线前必须引入。
- `POSTGRES_PASSWORD` 若含 URL 保留字符，需在 `DATABASE_URL` 中 URL 编码。
- 首次 `docker compose up` 需拉取 postgres:16-alpine 基础镜像（网络依赖）。
