# 需求变更记录 0001 — 待办支持截止日期 due_date

日期: 2026-08-21 · 提出者: user · 模式: 增量执行（不重建项目）

## 变更描述
新增 FR-6：待办条目支持可选截止日期 `due_date`（ISO 日期，仅日期无时间）。

## 影响分析（impact.js 输出）
seed: t-003（Todo CRUD）与 t-006（前端待办页）
受影响任务: t-003（后端 CRUD）、t-004（测试）、t-005/t-006（前端）、t-007（Review）
受影响产物: api-spec.yaml（TodoCreate/TodoOut/TodoUpdate）、database-schema.sql（todos.due_date）、product-spec.md（功能清单）

## 变更计划（用户确认——按无暂停模式记录为已批准）
1. 修订 api-spec.yaml + database-schema.sql（契约层，Manager 执行）
2. 后端：model/schema/router 增加 due_date（可空、格式校验）+ 回归测试（复用 backend 子代理）
3. 前端：待办项展示 due_date（复用 frontend 子代理）
4. Gate：pytest 全绿 + npm build 通过
5. 只重跑受影响任务；与截止日期无关的模块（认证等）不重跑

## 执行摘要
- 2026-08-21: 契约修订（api-spec/schema）完成；backend f28dead（+15 用例，null 清除语义）+ frontend 16084ab；pytest 63 passed；FE build PASS；api-spec/schema 已含 due_date
