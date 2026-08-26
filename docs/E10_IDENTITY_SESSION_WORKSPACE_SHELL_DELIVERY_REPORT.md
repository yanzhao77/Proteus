# E10 OIDC Identity、Session 与 Workspace Shell：交付报告

**状态：** PASS / COMPLETE。
**身份边界：** OIDC verifier 仍是身份真相来源；Product API 仍是业务读写 authority 表面。

## 实现

E10 添加短期、process-local 的 opaque session store。session 仅在成功验证标准 `Authorization: Bearer` 后创建；浏览器获得的仅是 `HttpOnly`、`SameSite=Lax` 的随机 session cookie。store 永不保存 bearer token、refresh token、Authorization header、raw claim 或 private key。`GET /session` 仅返回 subject、issuer 与 expiry 的最小 profile；`DELETE /session` 撤销 opaque id 并返回真正空 body 的 HTTP 204。

| HTTP surface | 行为 |
|---|---|
| `POST /session` | 验证 bearer OIDC identity 后创建 opaque session；无验证身份返回 401 |
| `GET /session` | 读取最小脱敏 profile；缺失/过期 session 返回 401 |
| `DELETE /session` | 撤销 session，并删除 HttpOnly cookie |
| `/factory-home/*` | 优先以已验证 session actor dispatch；actor header 与 session subject 不一致时 fail closed |

前端 Product API 和 session adapter 一律以 `credentials: include` 发送；不自行添加 actor header，不在 DOM、storage 或日志中保留 token。Workspace shell 显示脱敏 session 状态、可执行 sign-out，并在未认证或 adapter 不可用时显式降级，不回退到 production fixture。

## E10 验收

| 门禁 | 本轮结果 |
|---|---|
| local RS256 session exchange/profile/logout | `2/2 PASS` |
| OIDC/Factory Home/E7 focused authority regression | `24/24 PASS` |
| 前端 session adapter | `3/3 PASS` |
| 发现的token/cookie边界 | bearer 不回显；cookie 与 bearer 不同；无 bearer / actor-header绕过均 fail closed |

> E10 不创建 durable identity preference、业务表、角色或 grant；也不改变 E1–E8 authority semantics。
