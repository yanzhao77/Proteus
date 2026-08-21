# p-001 代码审查报告（t-007）

verdict: `request-changes`

> 审查范围：backend/app/**（auth/todos routers、core/security|deps、models、schemas、main、config、db）
> 与 frontend/src/**（api.js、App.jsx、AuthForm.jsx、TodoList.jsx、main.jsx）
> 对照：artifacts/api-spec.yaml、artifacts/architecture.md、artifacts/database-schema.sql、tasks/*.yaml
> 方式：静态阅读 + 动态验证（隔离 SQLite + TestClient，smoke 26/26 全绿；额外 8 组定向复现）。
> 结论：存在 1 项中危未解决缺陷（PATCH null → 500），按硬性约束判 **request-changes**。

---

## 一、发现表

| ID | 严重度 | 描述 | 位置 | 建议 |
|---|---|---|---|---|
| CON-01 | **中** | `PATCH /api/v1/todos/{id}` 显式传 `{"title": null}` 或 `{"done": null}` 时：`TodoUpdate` 字段为 `Optional[...]`，Pydantic 放行 null → `model_dump(exclude_unset=True)` 保留该键 → `setattr(todo,"title",None)` → 未处理 `IntegrityError` → **500 Internal Server Error**（已实测复现，title/done 均 500）。契约要求：null 属"请求体不符合 schema"应返回 422，且任何情况下不应 500。 | routers/todos.py:64-73；schemas/todo.py:21-24 | 两选一：① schema 层去掉 `Optional` 改为 `title: TitleStr \| None = None` 的语义改为「显式 null 即 422」（用 `model_config`/`Field` 禁止 null）；② router 层 `updates = payload.model_dump(exclude_unset=True, exclude_none=True)` 并在全部字段均被排除时返回 400（空请求体语义）。另建议全局捕获 IntegrityError → 500 兜底日志。 |
| SEC-01 | 低 | bcrypt 输入上限为 **72 字节**，但 `RegisterRequest.password` 用 `max_length=72`（**字符数**）。72 个 CJK 字符（216 字节）的密码被 passlib/bcrypt 静默截断为前 72 字节（约 24 字符），两段共享前 72 字节的不同密码可互相通过验证（已实测 72 CJK 密码注册返回 201）。 | schemas/auth.py:15；core/security.py:16 | 校验 `len(password.encode("utf-8")) <= 72`，或对 `CryptContext` 设 `truncate_error=True` 使超长输入显式报错。 |
| SEC-02 | 低 | 登录存在时序侧信道：`if user is None or not verify_password(...)` 短路，邮箱不存在时响应显著快于密码错误 → 可枚举已注册邮箱。 | routers/auth.py:52 | 邮箱不存在时也执行一次 dummy `verify_password`（恒假哈希），抹平时间差。 |
| SEC-03 | 低 | JWT 存 `localStorage`，无 HttpOnly cookie / CSP：一旦 XSS 即 token 泄露。Phase 2 单机开发可接受，但应记录为已知风险。 | frontend/src/api.js:5-17 | Phase 7 前至少加 CSP 与 `VITE_API_BASE_URL` 环境注入；长期建议 HttpOnly cookie 方案。 |
| SEC-04 | 低 | 注册/登录无速率限制（暴力破解面）。契约未要求，Phase 2 可接受。 | routers/auth.py | Phase 7 引入限流（如 slowapi）或反向代理层限制。 |
| SEC-05 | 低 | `deps.py` 对 `int(sub)` 无保护：Python 3.11+ 默认整数转字符串上限 4300 位，超长数字 `sub`（需有效签名才可达）会抛 `ValueError` → 500 而非 401。当前签名校验使其不可外部利用，属潜在健壮性缺口。 | core/deps.py:30 | decode 时限制 `sub` 长度（如 ≤19 位）或 `try/except (ValueError, TypeError)` 归入 401。 |
| CON-02 | 低 | 契约 400 语义偏差（有意为之但未对齐 spec）：弱密码（<8 字符）、title 为空/超长按 api-spec 应返回 400（业务校验），实现返回 422（Pydantic 默认）。schema 注释已声明为有意设计（"subsumed by Pydantic 422 per t-002"），且 smoke 断言 422；但与 api-spec 的 400 列表明确冲突，需契约侧决策后统一（改 spec 或改代码）。 | schemas/auth.py:10；schemas/todo.py:12 | 与 spec 拥有方确认：要么实现显式业务校验返回 400，要么修订 api-spec 删除 400 场景。 |
| CON-03 | 低 | `LoginRequest.password` 为 `min_length=1`，而 api-spec `Password` 组件为 `minLength: 8`（login 同样引用该组件）：<8 字符登录返回 401 而非 422（已实测：4 字符密码登录 → 401）。 | schemas/auth.py:20 | 对齐 spec：login 密码也设 `min_length=8`；或修订 spec。 |
| CON-04 | 低 | `/health` 可返回 `database: "degraded"`，超出 api-spec `HealthResponse.database` enum `[ok]`；`status` 恒为 "ok" 时 DB 降级仍 200。 | app/main.py:44-53 | 若保留降级上报，修订 spec enum 增加 `degraded`；或 DB 失败时返回 503。 |
| CON-05 | 信息 | 422 响应体 `detail` 为数组（FastAPI/Pydantic 默认），与 `Error` schema（`detail: string`）不完全一致。spec 第 13 行已注明 422 为 Pydantic 默认；前端 `typeof detail === 'string'` 分支兼容处理，无实际影响。 | 全局 | 可选：自定义异常处理器将 422 detail 归一为字符串，或修订 spec 标注 detail 可为数组。 |
| CON-06 | 信息 | 路径参数名 `{todo_id}` 与 api-spec `{id}` 不一致（OpenAPI 生成的 path template 为 `/api/v1/todos/{todo_id}`），端点行为等价。 | routers/todos.py:57,76 | 对齐参数名 `id`（若 apiCompleteness 门槛按模板字面比对）。 |
| CON-07 | 信息 | 前端 401 统一处理覆盖登录失败场景：凭据错误时服务端返回 401 + detail「邮箱或密码错误」，但 api.js 丢弃该 detail 并抛「登录已过期，请重新登录」→ 登录失败提示误导。 | frontend/src/api.js:50-54 | 401 分支区分端点：auth/login 与 register 的 401 保留服务端 detail；仅数据端点 401 才清 token 回登录。 |
| MAINT-01 | 低 | `users.email` 同时 `unique=True` 与 `index=True`：唯一约束在 SQLite/PG 下已隐式建索引，显式 index 冗余。与 database-schema.sql（仅 `uq_users_email`）不一致。 | models/user.py:16 | 去掉 `index=True`。 |
| MAINT-02 | 信息 | 架构声明 Python 3.11+，实测 venv 为 Python 3.9.6；代码靠 `from __future__ import annotations` + PEP 585 在 3.9 正常运行（smoke 通过）。运行版本与架构不符，需记录决策。 | requirements.txt；.venv | 更新 architecture.md 或升级 venv 到 3.11+。 |
| MAINT-03 | 信息 | vite.config.js 的 `/api` proxy 实际未生效：api.js 用绝对 `BASE_URL`（默认 `http://localhost:8000`）直连后端，依赖 CORS 而非代理。配置为死代码，且两种通道并存增加排障成本。 | vite.config.js:10-15；api.js:4 | 二选一：统一走相对路径 `/api`（proxy 生效、免 CORS），或删除 proxy 并保持 CORS 直连。 |

## 二、三面结论

### 1. 安全性（总体良好，无高危；5 项低危）
- **JWT**：HS256 算法固定（encode/decode 均显式指定）、claims 仅 `sub/iat/exp`（无 PII）、过期经实测 401 + `WWW-Authenticate: Bearer`、伪造签名 401、`SECRET_KEY` 无默认值（缺失启动即抛错）——符合架构 §5 与 api-spec。
- **bcrypt**：rounds=12、`bcrypt==4.0.1` 锁定规避 passlib 兼容坑、`password_hash` 仅存哈希（smoke 断言非明文）。
- **越权边界**：全部 todo 查询强制 `user_id` 过滤（list/get/patch/delete 均验证）；他人/不存在资源统一 404 防枚举；`user_id`/`password_hash` 不出 API。
- **输入/注入**：Pydantic v2 强类型校验；SQL 全部经 ORM 参数化（`text("SELECT 1")` 无用户输入）；CORS 白名单 + `Authorization`/`Content-Type` 放行与架构一致。
- **低危遗留**：多字节密码截断（SEC-01）、登录时序枚举（SEC-02）、localStorage token（SEC-03）、无限流（SEC-04）、`int(sub)` 健壮性（SEC-05）。均不阻断 Phase 2，建议在报告登记并排期。

### 2. 一致性（端点全覆盖；1 项中危契约违反 + 若干语义偏差）
- **端点/状态码/响应字段**：8 个端点与 api-spec 一一对应；注册 201、登录 200、创建 201、更新 200、删除 204、空 PATCH 400、401/404/409 语义均正确；`AuthResponse/UserOut/TodoOut/TodoListResponse/Error` 字段与 spec 对齐（`user_id` 不外泄）。
- **模型 vs database-schema.sql**：字段、长度（email≤255 / title≤200）、默认值（done=false）、`onupdate` 维护 updated_at、外键 CASCADE、`ix_todos_user_id` 全部一致；全部方言无关类型，SQLite→PG 零迁移成本符合架构红线。
- **关键缺口**：CON-01（PATCH null → 500）直接违反契约 422 语义且为未处理异常，是本次唯一的**中危**发现 → 触发 request-changes。
- **次要偏差**：400/422 语义两处（CON-02）、login 密码 minLength（CON-03）、health enum（CON-04）、路径参数名（CON-06）、422 detail 数组（CON-05，信息级）。

### 3. 可维护性（良好）
- 分层结构与架构 §6 一致（core/models/schemas/routers 职责清晰）；`_get_owned_todo` 复用、错误常量集中、docstring 充分；前端 401 统一事件、ApiError 封装、三态 UI 清晰。
- 低危项：email 冗余索引（MAINT-01）、venv 版本与架构不符（MAINT-02）、vite proxy 死代码（MAINT-03）。
- 轻微偏离架构建议结构（`api/client.js`/`context/`/`pages/` vs 实际 `src/api.js` + App 内联会话路由、无 React Router）：FR-4 功能满足，属"建议"级，不阻断。

## 三、测试状态

- `workspace/backend/tests/` 当前仅 `tests/smoke.py`（后端自检脚本）：本次复核实测 **26/26 全绿**（注册/登录/todo CRUD/越权 404/哈希存储）。
- t-004（QA 正式 pytest：`tests/test_auth.py`、`tests/test_todos.py`）状态 **pending**，由 QA 子代理负责。
- **测试审查将在 QA 完成后复核**（本次未因缺正式 pytest 判 FAIL，但 CON-01 的 null 用例应纳入 QA 用例集）。
- 建议 QA 补充用例：PATCH `title:null`/`done:null`（应 422 或 400，当前 500）、多字节 72 字符密码、登录短密码（422 vs 401）、/health DB 降级。

## 四、验证证据

- smoke.py 实测 26/26 PASS（本机 venv：Python 3.9.6 / fastapi 0.115.6 / sqlalchemy 2.0.52 / pydantic 2.13.4 / passlib 1.7.4 / bcrypt 4.0.1 / jose 3.3.0）。
- 定向复现（隔离 SQLite + TestClient）：JWT alg=HS256、claims=[exp,iat,sub] ✓；过期 token→401 ✓；伪造 token→401 ✓；`PATCH title=null`→**500**、`PATCH done=null`→**500**、`PATCH title=""`→422、null 后 PATCH 正常→200；login 4 字符密码→401（spec 422）；title 201 字符→422（spec 400）；72 个 CJK 字符密码→201（截断风险复现）。
