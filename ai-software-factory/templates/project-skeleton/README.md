# Factory Project Skeleton

项目结构（Artifact-first）：

- `project.json` — 状态机 + 元数据（权威，revision 递增；`status` 主线与 `runStatus` 见 factory-project 技能）
- `artifacts/` — 阶段产物（requirements.md … release-notes.md）
- `contracts/` — 角色契约 role-contract.yaml、质量门槛 gates.yaml
- `tasks/` — 任务表 tasks/<task-id>.yaml（DAG）
- `workspace/` — 被生产软件的源码树（git init）
- `reports/` — 阶段报告、Gate 证据、验收矩阵
- `logs/` — 任务运行日志
- `memory/` — ADR、需求变更、失败记录、预算账本

实例化：`templates/scripts/project-init.sh <project-id> <target-dir>`（默认 <factory-root>/projects/<project-id>）。
