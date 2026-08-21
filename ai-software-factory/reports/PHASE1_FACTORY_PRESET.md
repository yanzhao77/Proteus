# Phase 1 报告 — software-factory 预设

> 日期：2026-08-21 · 执行：Factory Manager（本会话）· 状态：**完成并通过验证**

## 交付物

| 项 | 路径 | 说明 |
|---|---|---|
| Agent Preset | `~/.dsh/.agent-presets/software-factory/` | 从官方 `standard` 复制后修改（shipped preset 零改动） |
| 预设元数据 | `preset.yml` | 名称「软件工厂模式」+ Factory Manager 描述 |
| 组成文件 | `agent.cordis.yml` | 16 行（与 standard 一致）；persona 替换为 Factory Manager（12 条运行原则）；`skill-filesystem` 增加 `customSkillDirs`（复用 cordis proven pattern） |
| 技能 | `skills/factory-project/SKILL.md`、`skills/factory-dispatch/SKILL.md` | 随预设旅行 |
| 模板 | `ai-software-factory/templates/`（project-skeleton / artifacts×15 / scripts×2） | 已 git 提交 |

## 验证证据（规格书 §36 验证清单）

- [x] **Preset Discovery**：`agentPresets.list()` 含 `software-factory`（trust=user，broken=null）
- [x] **Preset Mount**：`agentPresets.standingKeyFor('software-factory')` → `mounted: OK`（真实组合插件子树；四种失败模式均被该检查覆盖）
- [x] **结构验证**：YAML 解析通过；16 行；persona 文本 3514 字符含 Factory Manager 身份；customSkillDirs 指向预设自身 `skills/`
- [x] **官方 preset 未动**：standard/code/minimal/cordis 均为 system trust，原路径未变
- [ ] **Tool/Prompt Visibility**：需用户在新会话选择「软件工厂模式」后确认工具目录（预设决定工具 schema 与 prompt sections，只有真实会话可见）→ 待办
- [ ] **Subagent/Workflow on new preset**：Phase 2 演练验证 → 待办

## 实施过程记录

1. 加载 `editing-cordis-compositions` 技能
2. 动态探针插件 `fpt-1`（cordis_define → cordis_run）暴露 `agentPresets` 服务为模型工具（`preset_copy/preset_check/preset_list`）
3. 复制 standard → 用户根（沙箱升级 danger-full-access，用户批准）
4. 批量编辑：persona 替换、skill-filesystem 行、preset.yml、2 个技能文件
5. 结构验证（node + yaml）
6. `preset_check` + `preset_list` 官方验证通过
7. 探针插件已卸载（`cordis_undefine`）

## 备注

- 运行时沙箱当前为 `danger-full-access`、审批策略 `never`（用户已切换）；子代理审批固定 never 的约束仍生效。
- 用户指示：后续任务自动继续，不再暂停等待确认。
