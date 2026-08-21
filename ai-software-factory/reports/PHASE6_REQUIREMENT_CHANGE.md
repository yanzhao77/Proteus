# Phase 6 报告 — 需求变更引擎

> 日期：2026-08-21 · 状态：**完成** · 变更 FR-6（Todo 可选截止日期 due_date）增量执行实证

## 变更流程（需求 → 影响分析 → 计划 → 增量执行 → 验证）
1. **变更请求**：`memory/changes/0001-due-date.md`（FR-6，可选 ISO 日期）
2. **影响分析**：`scripts/impact.js`（任务 DAG 依赖闭包）→ seed t-003/t-006 → 受影响 {t-003 后端, t-004 测试, t-006 前端, t-007 Review}
3. **变更计划**：契约修订（api-spec TodoCreate/Out/Update + database-schema due_date）→ 后端（model/schema/router/测试）→ 前端（表单+展示）→ Gate → 只重跑受影响任务
4. **增量执行**：
   - 契约：api-spec.yaml（due_date format:date nullable，Update 显式 null=清除）、database-schema.sql（todos.due_date DATE NULL）
   - 后端（角色复用 ae1e5138）：f28dead —— `Mapped[Optional[date]]`（Python 3.9 兼容，`date|None` 无法解析）、null 清除语义（exclude_unset 后 due_date 显式 None → 写 NULL，其余 null 仍忽略，无字段才 400）、+15 回归用例
   - 前端（角色复用 13cd635f）：16084ab —— date 输入、列表展示「截止: YYYY-MM-DD」、空则不传字段
5. **验证**：pytest **63 passed**（48+15）+ FE build PASS + 变更记录回填

## 实证结论
- 未重建项目：仅受影响的 4 个任务子集重跑；认证等无关模块零改动
- 契约即真相：spec/schema 先改，实现跟随；前端发现 spec 未落地时主动上报（Evidence over claims 的延伸——角色不自证、偏差上报）
- 增量闭环 15 分钟级完成（含测试）
