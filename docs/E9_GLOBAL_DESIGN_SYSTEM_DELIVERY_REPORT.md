# E9 Global Design System：交付报告

**状态：** PASS / COMPLETE。
**基线：** E8 merge commit `b23efde961ee34537d907e46bef49df98f0cc55d`。
**边界：** 本交付只建立呈现层，不引入业务 authority、数据库 schema 或 migration。

## 交付内容

E9 将 Factory Home、Entry Draft、Draft detail、Understanding、Clarifications、Proposal、Master Plan、E4 approval summary、Portfolio、Gate Inbox、Live Production、Project summary 与统一 loading/pending/error/stale/unavailable/empty 状态迁移到单一的响应式 workspace shell。视觉层采用稳定工作台布局、可横向滚动的数据表格、DAG 和日志面板，而不是营销 hero、装饰粒子、orb 或颜色唯一状态编码。

| Semantic family | 已交付范围 |
|---|---|
| Surface | `background.canvas`、`background.surface`、`background.elevated` |
| Content / focus | `text.primary`、`text.secondary`、`text.muted`、`border.*`、`focus.ring` |
| Action / state | `action.*`、`status.running/waiting/success/warning/failure/blocked` |
| Operations | `chart.*`、`dag.*`、`diff.*`、`log.*` |
| System | spacing、radius、shadow、motion、typography、density |

主题通过 `data-theme` 支持 system/light/dark；语言支持 `en-US` 与 `zh-CN`，日期由 `Intl.DateTimeFormat` 格式化。主题、语言和密度仅保存为浏览器非敏感 UI preference；实现未保存 OIDC token、refresh token、project identity 或 authority fact。StatusBadge 同时使用 label、图形标记与颜色；icon button 含可见 keyboard focus 和 tooltip。

## E9 验收

| 门禁 | 本轮结果 |
|---|---|
| E9 semantic design / App / contract Vitest | PASS |
| 前端完整 Vitest（截至E11） | `31` tests / `8` files PASS |
| production build | PASS |
| oxlint | `0 warnings / 0 errors` |

> E9 不创建 migration，且不进入 E10 之外的任何 authority 变化。
