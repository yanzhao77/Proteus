# E9–E11 Wave A：Global Product Workspace 交付报告

**状态：** 本地 delivery complete；待独立 PR、远端 CI、标准 merge 与 post-merge master verification。
**基线：** `b23efde961ee34537d907e46bef49df98f0cc55d`。
**迁移决定：** 无新 migration；head 保持 `0032_p6_execution_prepare_structured_secret_guard.sql`。

## Scope Result

| Phase | Result | Authority boundary |
|---|---|---|
| E9 | Global semantic design system、responsive workspace、theme、density、`en-US`/`zh-CN` localization | UI preference only |
| E10 | OIDC-derived opaque session、session profile/logout、credentialed Product API workspace shell | verifier / Product API stay server-side |
| E11 | project operations workspace for DAG, execution, verification, evidence, waiting and recovery facts | E7 read-only projection; Gate Inbox navigation only |

## 本轮验证记录

| 门禁 | 结果 |
|---|---|
| no-DB unittest discovery | `707 run / 438 skipped / 0 failures`，`1.614s` |
| Full Runtime with fresh PostgreSQL 16, migrations 0001–0032 | `707 run / 12 skipped / 0 failures`，`471.213s` |
| E10 local RS256 session | `2/2 PASS` |
| E10 focused OIDC/Factory Home/E7 regression | `24/24 PASS` |
| frontend Vitest | `31` tests / `8` files PASS |
| frontend build | PASS |
| oxlint | `0 warnings / 0 errors` |

浏览器验收已在**沙箱干净检出** `d02811ead9dec4b4e78d54deef87457d2c972db4` 的 Vite preview 完成。Home 显示 stable workspace navigation、`Session required` 与不伪造 portfolio 的显式 Product API failure；Display settings 实测支持 Dark、`zh-CN` 与 density controls；Projects、Gate Inbox、New production 与 canonical E11 operations route 均可导航。无认证/无 snapshot 时不会伪造 Project、Draft、Gate、Execution、Verification、Evidence 或 Recovery fact；E11 明确声明无 direct authority mutation。此前用户桌面私网预览不可由隔离浏览器路由的限制，已由该干净检出浏览器验收替代。

## Stop Boundary

本波次不修改 migrations `0001–0032`、E1–E8 authority semantics、P0–P6 Recovery/Worker/Scheduler/Execution/Verifier/Gate authority、业务 schema、role 或 grant。没有真实 provider、模型、生产部署、credential 或 fixture data 进入 production build。E12、E13、E14、E15 与 E16 未进入。

## Current Acceptance Qualification

After the E9-only closure, the correct current statement is: **E9 PASS / ACCEPTANCE COMPLETE; E10 delivered as previously merged; E11 PARTIAL / ACCEPTANCE GAP; E9–E11 Wave A NOT COMPLETE.** The missing E11 condition is a compliant OIDC-user-callable existing authority semantic command and its authoritative receipt/replay/conflict/projection evidence. No substitute authority path was introduced.
