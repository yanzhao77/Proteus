# p-001 安全审计报告（Phase 7）

- **审计角色**：security（AI Software Factory 子代理）
- **审计日期**：2026-08-21
- **审计对象**：`projects/p-001/workspace/backend`（FastAPI + SQLAlchemy + JWT + bcrypt，pytest **63 passed**）、`projects/p-001/workspace/frontend`（React 18 + Vite，build 通过）、部署模板 `ai-software-factory/templates/deployment/`
- **参照契约**：`artifacts/api-spec.yaml`、`artifacts/architecture.md`；复评对象 `reports/review-report.md`（SEC-01~05）
- **方式**：只读代码审计 + 静态扫描（git 历史、grep）+ 本地测试复跑 + 依赖版本人工核对（npm audit 因本地 registry 镜像不可用改为人工核对）

---

## 1. 范围与方法

1. 通读后端全部源码：`core/security.py`、`core/deps.py`、`routers/auth.py`、`routers/todos.py`、`schemas/*`、`models/*`、`config.py`、`main.py`、`db.py`。
2. 通读前端：`src/api.js`、`src/App.jsx`、`src/AuthForm.jsx`、`src/TodoList.jsx`、`vite.config.js`。
3. 静态扫描：`grep` 全库 `eval/exec/subprocess/shell=True/pickle/dangerouslySetInnerHTML/innerHTML`；`git log --all -p` + `git ls-files` 抽查 secret 历史。
4. 测试复跑：`.venv/bin/python -m pytest -q` → **63 passed**。
5. 依赖核对：`requirements.txt`、`package-lock.json`（lockfileVersion 3）解析实际锁定版本，对照已知 CVE 通告人工标注。
6. 部署模板：`Dockerfile.api`、`Dockerfile.web`、`docker-compose.yml`、`nginx.conf`、`.env.example`（Phase 7 部署物，一并纳入）。

---

## 2. 发现表

| ID | 严重度 | 描述 | 位置 | 处置 |
|---|---|---|---|---|
| SEC-01 | 低 | 密码超过 bcrypt 72 字节上限会被静默截断，两段共享前 72 字节的不同密码可互相通过验证 | `schemas/auth.py:14-31` | **已修复**：UTF-8 字节级 field_validator（register+login），25 CJK 字符→422、24→201（`test_regressions.py` 覆盖） |
| SEC-02 | 低 | 登录时序侧信道：`user is None or not verify_password(...)` 短路，邮箱不存在时跳过 bcrypt（≈200ms 差距）→ 可枚举已注册邮箱 | `routers/auth.py:52` | **待办（接受）**：建议对不存在邮箱执行一次恒假 dummy verify 抹平时间差；Phase 7 加固清单 |
| SEC-03 | 低 | JWT 存 `localStorage`，无 HttpOnly cookie / CSP，一旦 XSS 即 token 泄露 | `frontend/src/api.js:5-17` | **接受**：单机开发场景可接受；前端无任何 `dangerouslySetInnerHTML/innerHTML/eval`（React 默认转义），XSS 面窄。生产建议 CSP + HttpOnly cookie |
| SEC-04 | 低 | 注册/登录无速率限制（暴力破解面） | `routers/auth.py` | **待办（接受）**：契约未要求；Phase 7 建议 nginx 层或 slowapi 限流 |
| SEC-05 | 低 | 伪造超长数字 `sub` 触发 `int()` 溢出 → 500 而非 401 | `core/security.py:52`、`core/deps.py:30-33` | **已修复**：decode 限 `sub` ≤19 位纯数字 + `try/except ValueError` 归入 401；回归测试 3 个恶意 sub 全 401 |
| SEC-06 | 低 | `docker-compose.yml` 中 `CORS_ORIGINS` 为 JSON 数组字符串 `'["http://…"]'`，与后端逗号分隔解析不兼容 → 解析出含引号/括号的无效 origin（CORS 静默失效）；且 `build.dockerfile: Dockerfile` 与实际模板文件名 `Dockerfile.api/web` 不符 | `templates/deployment/docker-compose.yml` | **待办**：devops 角色修复（改逗号分隔、改文件名），属配置缺陷非代码漏洞；生产经 nginx 同源代理可绕开 CORS |
| SEC-07 | 低 | Docker 非 root 未落实：`Dockerfile.api` 无 `USER`（root 运行）；compose 内硬编码 dev 凭据（`dev_only_change_me`/`app_dev_only`，已显式标注 dev_only 且 `.env.example` 警告必须替换）；nginx 仅 HTTP 无 TLS | `templates/deployment/*` | **待办**：加非 root USER；生产 secrets 走 env/docker secrets；HTTPS 由 nginx 层终止（架构 §5.7 已要求，模板未落地） |
| SEC-08 | 信息 | `python-jose==3.3.0` 存在已知算法混淆类 CVE（CVE-2024-33663/33664） | `requirements.txt:9` | **已缓解**：`jwt.decode` 显式固定 `algorithms=["HS256"]` 白名单，应用不涉及非对称密钥，实际不可利用；建议后续迁移 PyJWT |
| DEP-01 | 信息 | 后端部分依赖为范围锁定（sqlalchemy/pydantic `>=x,<y`），非精确 pin；`passlib 1.7.4` 已停止维护（无 CVE，维护风险） | `requirements.txt` | **接受**：范围有上界且核心安全件（jose/passlib/bcrypt/fastapi/uvicorn）均精确 pin；passlib 建议随 PyJWT 迁移一并替换 |
| DEP-02 | 信息 | 前端 lockfile 锁定 `vite 5.4.21`（已覆盖 2025 年全部 dev-server CVE：CVE-2025-30208/31125/31486/32395 等，均于 5.4.x 线修复）；`esbuild 0.21.5` 存在 dev 模式 CVE（CVE-2024-24790/CVE-2025-22871），仅影响 dev server，生产产物不受影响 | `package-lock.json` | **接受**：dev-only，生产为静态构建产物 |

---

## 3. 已执行检查清单

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| 1 | JWT 算法固定 HS256，decode 显式算法白名单 | **PASS** | `security.py:18,48`；防 alg=none / 算法混淆 |
| 2 | JWT 过期（exp）校验 | **PASS** | `security.py:36` 签发 exp，jose 默认校验；过期/无效 → 401 |
| 3 | JWT `sub` 仅数字且 ≤19 位（int64 上限） | **PASS** | `security.py:52`；超长/非数字 → None → 401 |
| 4 | bcrypt rounds | **PASS** | `security.py:16` `bcrypt__rounds=12`，passlib 1.7.4 + bcrypt 4.0.1 精确 pin（兼容修复） |
| 5 | 密码字节上限 ≤72（register+login） | **PASS** | `schemas/auth.py:14-31`（SEC-01 已修复，回归测试覆盖） |
| 6 | 密码最小长度 8 | **PASS** | 契约 CON-03，422 语义（register+login） |
| 7 | 越权边界：所有 todo 查询强制 `user_id` 过滤 | **PASS** | `todos.py:23-28`（`Todo.id == id AND Todo.user_id == user_id`）、list/create/update/delete 全部按 `user.id` 过滤 |
| 8 | 越权/不存在资源统一 404（防枚举） | **PASS** | `todos.py:20,26-27`；无 403 分支 |
| 9 | 登录失败统一消息（防账号枚举） | **PASS**（除 SEC-02 时序） | `auth.py:21-25` 统一"邮箱或密码错误" |
| 10 | 注册重复邮箱 409 | **PASS**（by-design） | `auth.py:36-37`，api-spec 要求 |
| 11 | SQL 注入面：全部 ORM/参数化，无拼接 | **PASS** | 全库仅静态 `text("SELECT 1")`（health）；select 均走 SQLAlchemy 绑定参数 |
| 12 | 无 eval/exec/os.system/subprocess/shell=True/pickle 用户输入 | **PASS** | grep 全库无命中 |
| 13 | 路径/ID 参数类型校验 | **PASS** | `id: int` 路径参数 → 非整数 422 |
| 14 | SECRET_KEY 必填无默认，缺失即启动失败 | **PASS** | `config.py:22`（pydantic-settings 必填，无回退默认值） |
| 15 | .env.example 仅占位 | **PASS** | `change-me-to-a-long-random-string` + 生成指引 |
| 16 | git 历史无 secret（p-001 路径） | **PASS** | `git ls-files` 无 `.env`；`git log --all -p` 中 SECRET_KEY 仅出现在架构/评审文档的叙述里；仓库级扫描命中的仅为其他项目测试夹具密码（hermes-*-role-test），非真实凭据 |
| 17 | 依赖锁定：前端 lockfile v3 | **PASS** | `package-lock.json`；npm ci 可复现 |
| 18 | 高风险的已知 CVE 人工核对 | **PASS**（有标注） | 见 SEC-08/DEP-01/DEP-02；vite 5.4.21 已含修复版本 |
| 19 | CORS 白名单（非 `*`）+ `Authorization`/`Content-Type` 放行 | **PASS** | `main.py:32-38`；`allow_credentials=True` + 显式 origin 列表（无通配符+凭据组合） |
| 20 | 生产 HTTPS 建议（nginx 层） | **待办** | 模板 nginx.conf 仅 HTTP:80，无 TLS；架构 §5.7 已要求，devops 落实 |
| 21 | Docker 非 root | **待办** | 见 SEC-07 |
| 22 | SEC-02 登录时序侧信道复评 | **未修复**（低危，接受） | `auth.py:52` 短路仍存在 |
| 23 | SEC-03 localStorage token 复评 | **接受**（低危） | 前端无 XSS sink，风险被压缩 |
| 24 | SEC-04 无限流复评 | **接受**（低危） | 契约未要求，Phase 7 加固项 |
| 25 | SEC-05 int(sub) 复评 | **PASS（已修复）** | `security.py:52` + `deps.py:30-33` + 回归测试 |

---

## 4. 结论

**PASS** ✅

- 高/中危：**0 项**。认证链（HS256 固定算法 + exp + sub 严格校验 + bcrypt rounds=12 + 72 字节上限）、越权边界（user_id 强制过滤 + 404 防枚举）、注入面（全参数化 + 无 eval/exec）、Secret 管理（必填无默认 + git 历史干净）均达标并有回归测试佐证（63 passed）。
- 遗留：**4 项低危**（SEC-02 时序、SEC-03 localStorage、SEC-04 无限流、SEC-07 部署加固/模板配置缺陷）+ 3 项信息级依赖标注（SEC-08/DEP-01/DEP-02）。均不构成阻断，符合"高/中危未解决 → FAIL"的判定反条件。
- 建议：Phase 7 devops 修复 SEC-06 模板缺陷、落实非 root 与 HTTPS、nginx 限流；后续迭代迁移 PyJWT（替换 jose+passlib）。

*审计人：security 子代理（Phase 7）*
