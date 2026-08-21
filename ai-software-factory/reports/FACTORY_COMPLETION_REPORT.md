# AI Software Factory — 完成报告（V0.1）

> 日期：2026-08-21 · 执行：DeepSeek Harness（cordis 预设）Factory Manager · 目标：Phase 0-7 全部达成

## 一、交付总览
| Phase | 目标 | 结果 |
|---|---|---|
| 0 Discovery | 能力盘点 | ✅ RUNTIME_CAPABILITY_MAP.md（37 页：全部 Host 服务/事件/工具/预设实测） |
| 1 Factory Preset | Factory Manager 可运行 | ✅ software-factory 预设（16 行组成、Mount 验证 OK、10 技能、模板×19） |
| 2 Production Workflow | 第一个完整闭环 | ✅ p-001 需求→架构→实现→测试→Review 闭环（状态机 18 个 revision） |
| 3 Agent Team | 动态角色调度 | ✅ 8 角色（architect/pm/backend/frontend/qa/review/fix/security/devops），并行/复用/换人实证 |
| 4 Quality Gate | 自动验证 + 失败回退 | ✅ 5 类 Gate 脚本；注入回归 FAIL→换人修复→PASS 实证 |
| 5 Human Intervention | 暂停/恢复/审批/修改 | ✅ pipeline-check 调度闸 + PAUSED/RUNNING 实证 + 事件审计 |
| 6 Requirement Change | 影响分析 + 增量执行 | ✅ impact.js DAG 闭包；FR-6 due_date 增量（只重跑 4 个受影响任务） |
| 7 Production Trial | 真实软件交付 | ✅ React+FastAPI+PostgreSQL+Docker 可运行 + 全套 10 类产物 |

## 二、工厂能力（构建于 DSH/Cordis 原生原语）
- 预设：`~/.dsh/.agent-presets/software-factory/`（persona 12 原则 + factory-project/factory-dispatch + 8 角色技能）
- 项目状态机：`projects/<id>/project.json`（16 状态 × 8 runStatus，revision 递增，事件日志）
- 任务 DAG：`tasks/*.yaml`（dependsOn/role/acceptance/evidence）
- 调度闸：`scripts/pipeline-check.sh`（PAUSED/BLOCKED/WAITING_APPROVAL 拒绝派发）
- 影响分析：`scripts/impact.js`（依赖闭包）
- Gate：`scripts/gates/{test,build,security,record}-gate.sh`
- 角色契约：`contracts/<role>.yaml`（委派 prompt 注入）
- 恢复：子代理持久会话（send_message 复用/cold resume）+ project.json 现场恢复

## 三、实证数据
- pytest：39 → 48 → 63 passed（QA 39 + 回归 9 + FR-6 15）
- Review：request-changes（15 发现）→ 修复 8/8 → approve
- 安全审计：25 项检查 PASS，0 高/中危
- 生产冒烟：全链路 + 持久化（db 重启数据保留）
- 失败恢复阶梯全程实证：retry(修复轮) / switch-agent(换人修复) / escalate(Manager 修复 PG-01)

## 四、重要教训（memory 沉淀）
1. **子代理产物即时提交**：外部 git 操作可清扫未提交文件（INFRA-02，stash 恢复）
2. **方言无关红线要实测**：server_default=text("0") 逃过单元测试，被 PG 生产运行捕获（PG-01）
3. **权限即兼容性**：write 工具 600 权限在容器非 root 场景暴露（PERM-01）
4. **Gate 失败要留证据**：pytest 输出 + commit hash 注入修复任务，修复效率显著
5. **契约先行**：spec/schema 先改、实现跟随；角色发现 spec 未落地主动上报（Evidence over claims 延伸）

## 五、未实现/扩展点（诚实清单）
- 无完整 Factory Dashboard UI（动态插件 Slots 已探明，留待下一步）
- workflow 工具未用于流水线（Manager 直排 + 子代理；workflow 适合大规模 fan-out）
- agentTeams（catalog-only，未装）未采用；自建任务表替代
- 预算账本（tokenMeter 计量）未联动自动暂停（机制已设计）
- HTTPS/限流（SEC-02/03/04）为已知低危遗留
- 多项目/多用户（workspace 隔离已具备，组织模型未建）

## 六、约束遵守
- ❌ 未修改 Harness Core / 官方 shipped preset（standard/code/minimal/cordis 原样，system trust）
- ✅ 所有能力走 Plugin Composition / 用户预设 / 文件与脚本
- ✅ 每阶段 Implement → Test → Validate → Commit（11 次工厂仓库提交 + 9 次 workspace 提交）
