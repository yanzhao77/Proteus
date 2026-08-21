# 角色 Agent 注册表（p-001）

| 角色 | 子代理 id | 状态 | 任务 | 复用情况 |
|---|---|---|---|---|
| architect | 5b2181e5-188f-4eeb-af80-515d2eadc270 | ready | t-arch（architecture/api-spec/schema） | 一次性 |
| backend | ae1e5138-5761-431b-9511-a628d8fb8dc6 | ready | t-001/2/3 + 修复 6 项 | ✅ 复用（send_message） |
| frontend | 13cd635f-8f9f-4fd9-8518-260b0dfe4c6b | ready | t-005/6 + CON-07 修复 | ✅ 复用 |
| qa | 7113123f-5e03-45c7-b03f-b5c0492d933f | ready | t-004（39 用例） | 一次性 |
| review | 3728161a-3125-45ce-a5ac-ce291a7ed936 | ready | t-007 初审 + 复审 approve | ✅ 复用 |
| pm | 09a9f29d-0be0-416f-863a-c4010f2fdc61 | ready | product-spec.md | 一次性 |
| fix-engineer（换人） | 99598e77-1d12-42f3-a966-3ee0201e2cc5 | ready | Phase4 gate 回归修复（404） | Switch-Agent 演示 |
| security | （Phase 7 启动） | - | 安全审计 | - |
| devops | （Phase 7 启动） | - | Docker 化/冒烟 | - |
