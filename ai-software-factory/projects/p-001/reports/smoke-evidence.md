# Phase 7 生产冒烟证据（docker compose）

日期: 2026-08-21 · 环境: Docker Desktop 29.6.2（基础镜像经 dockerproxy 镜像源拉取，Docker Hub 直连不可用）

| 检查 | 结果 |
|---|---|
| docker compose build（api/web） | PASS（p-001-api / p-001-web 镜像） |
| db healthcheck（pg_isready） | PASS（Healthy） |
| api healthcheck（python urllib） | PASS（Healthy） |
| GET /health | 200 {"status":"ok","database":"ok"} |
| POST /api/v1/auth/register | 201 + access_token |
| POST /api/v1/auth/login（正确凭据） | 200 + token |
| POST /api/v1/auth/login（错误密码） | 401 |
| 未认证 GET /todos | 401 |
| POST /todos（含 due_date） | 201 {"id":1,...,"due_date":"2026-09-01"} |
| GET /todos | 200 仅本人数据 |
| web 页面 http://localhost:8080/ | 200 |
| web→api 同源代理 /api/v1/todos | 200 |
| db+api 重启后数据持久化 | PASS（todo 仍在，卷持久化） |
| PG 建表确认 | PASS（users/todos 两张表） |

发现并修复的问题（生产试运行暴露）:
- PERM-01: 源码 600 权限导致容器非 root 无法读取 → chmod a+r + 重建
- PG-01: done 列 server_default=text("0") 在 PG 报 DatatypeMismatch → 改 Python 侧 default=False（方言无关红线违反被实测捕获）
