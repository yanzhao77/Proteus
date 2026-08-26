# E9–E11 Wave A：Global Product Workspace 实现契约

**基线：** `b23efde961ee34537d907e46bef49df98f0cc55d`（E8 已合并）。
**范围：** E9 Global Design System、E10 Identity/Session/Workspace Shell、E11 Project Operations Workspace。
**停止边界：** 本波次不进入 E12–E16。

## Authority 与数据边界

| Surface | 权威来源 | Wave A 行为 | 明确禁止 |
|---|---|---|---|
| 主题、语言、密度 | 浏览器非敏感 UI preference | 仅控制呈现；不承载身份或业务状态 | 不保存 token、project selection 或 authority fact |
| Identity / session | FastAPI 的 OIDC verifier 和短期 server-side opaque session | 浏览器只持有 HttpOnly opaque session id；`/session` 只返回脱敏 identity | 不把 OIDC/refresh token 写入 Cookie、DOM、storage、日志或前端状态 |
| Factory Home、Draft、Plan、Approval | 已有 Product API read/semantic command ports | Shell 和页面只通过 authenticated HTTP adapter 展示或提交既有语义命令 | 不从 React 构造 Project/Task/Plan authority |
| Project operations | E7 `PostgresLiveProductionReadModel` source-derived snapshot/feed | 展示 DAG、execution、verification、evidence、gate、waiting 与 recovery facts | 不 direct DML、不用 optimistic/event receipt 作为最终状态 |
| Recovery entry | 既有 human-gate / authority workflow | 只显示事实、原因与已存在受控入口；无权时 fail closed | 不提供 pause/resume/retry/reassign/direct recovery command |

## Migration 决定

**不创建 migration。** 当前 migration head 为 `0032_p6_execution_prepare_structured_secret_guard.sql`。E9 仅改变呈现层；E10 session 为短期 server-memory opaque reference，不是 durable user preference；E11 使用已存在的 E7 live snapshot、bounded feed 与 actor scope。因此本波次没有 first-class durable preference 或 read model schema 缺口，也不会创建空 migration。

## E9 Contract

E9 在全量现有生产页面建立唯一 semantic token 层：canvas/surface/elevated、文本、border、focus、action、status、chart/DAG/diff/log、spacing/radius/shadow/motion/typography/density。主题由 `data-theme` 驱动；语言由 `data-locale` 和 dictionary 驱动；状态同时呈现 label、图标与颜色。全局组件覆盖 loading、pending、error、stale、unavailable、empty、tooltip、icon button、table、panel、notice 与 status badge。

## E10 Contract

E10 新增 `/session` HTTP surface：exchange 只接收正常的 Authorization header 并在 verifier 成功后创建随机 opaque server session；浏览器 cookie 只包含随机 session id。`GET /session` 返回最小脱敏 profile，`DELETE /session` 销毁 session。Product API transport 使用 `credentials: include`，并绝不自行添加 actor header 或保存 token。Workspace shell 以 session state 驱动可访问页面；未认证状态不会回退到 fixture。

## E11 Contract

新路由 `/productions/:id/operations` 使用同一个 authenticated E7 snapshot。其 DAG、execution、verification、evidence、waiting、gate 与 recovery sections 是 read-only representation。Recovery/Gate CTA 仅携带本地 route context 到既有 Gate Inbox；它不发出 authority command。任何 `NOT_AVAILABLE`、`STALE`、`DEGRADED` 或 scope concealment 都在 UI 显式呈现并停止操作。

## Acceptance Matrix

| 层 | 最低验收 |
|---|---|
| E9 | light/dark tokens、locale switch、density、focus、tooltip、status non-color、空/错/陈旧状态在已存页面可见 |
| E10 | local RS256 test issuer exchange/session/logout；opaque id 不含 token；cookie session 可以调用 Product API；actor header 不成为授权来源 |
| E11 | source-derived live snapshot 通过 adapter 显示 DAG/execution/verification/evidence/recovery；cursor stale 与 unavailable fail closed；recovery CTA 无 direct command |
| Regression | frontend Vitest/build/oxlint、真实 PostgreSQL tests、browser route checks、Full Runtime、manifest non-self hash audit |
