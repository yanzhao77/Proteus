# Phase 5 报告 — 人类干预（Human-in-the-loop）

> 日期：2026-08-21 · 状态：**完成** · 机制实现 + 实证

## 干预面与机制
| 用户动作 | 机制 | 实证 |
|---|---|---|
| 澄清 | `ask_user_question`（需求阶段带选项提问） | 需求阶段已设计；本会话按用户指示以假设 A1-A4 默认化 |
| 暂停 | 项目 runStatus=PAUSED + `pipeline-check.sh` 调度闸 | ✅ 演示：PAUSED → DENIED_PAUSED(exit 3)，无派发 |
| 恢复 | runStatus=RUNNING + 调度闸 | ✅ 演示：RUNNING → ALLOWED(exit 0) |
| 停止/取消 | runStatus=CANCELLED + interrupt_agent（子代理）+ goal clear | 机制就绪（pipeline-check 对 FAILED/BLOCKED 亦拒绝） |
| 审批 | `approval` 服务（approval/request waterfall）+ permission presets | 会话当前 policy=never（用户切换）；policy=ask 时审批点自动出现 |
| 修改/重定向 | 需求变更引擎（Phase 6）：影响分析 → 变更计划 → 增量执行 | 见 PHASE6 |
| 阻塞说明 | runStatus=BLOCKED + blockedReason | pipeline-check 输出原因 |

## 设计要点
- **调度闸**（pipeline-check.sh）：所有派发/推进动作先检查 runStatus；PAUSED/BLOCKED/WAITING_APPROVAL/FAILED 拒绝派发并说明原因。防止"用户暂停后 Agent 继续干活"。
- **Goal 联动**：会话级暂停走 `update_goal(pause/resume)`（持久化）；项目级暂停走 project.json——两者独立，支持"暂停单个项目、继续其他项目"。
- **审批边界**：危险操作（部署/凭据/破坏性命令）只在 Factory Manager 层执行并触发审批；子代理 approval=never（实测约束）。
- **事件可审计**：user.pause / user.resume / quality.failed 等全部写入 project.json events[]（持久）。
