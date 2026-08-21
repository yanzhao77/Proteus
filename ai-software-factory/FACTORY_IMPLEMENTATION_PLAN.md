# AI Software Factory — 实施计划（FACTORY_IMPLEMENTATION_PLAN.md）

> 前置：`RUNTIME_CAPABILITY_MAP.md`（实测能力）与 `SOFTWARE_FACTORY_ARCHITECTURE.md`（架构决策）已就绪。
> 本计划严格遵循：小步实现、每步验证、先 Inspect 再 Implement、不修改 Harness Core / shipped preset。
> 每个阶段 = `Implement → Test → Runtime Validate → Commit` 循环；每个完成项附验证清单。

---

## 里程碑总览

| Phase | 名称 | 目标 | 出口条件 |
|---|---|---|---|
| 0 | Runtime Discovery | 能力盘点 | ✅ 已完成（本计划 + 两份文档） |
| 1 | Factory Preset | Factory Manager 可运行：需求拆解 + 计划产出 | `software-factory` preset 挂载且能产出 implementation-plan |
| 2 | Production Workflow | 第一个完整生产闭环（需求→架构→实现→测试→Review） | 示例 Todo 项目跑通闭环 |
| 3 | Agent Team | 动态角色调度（PM/Architect/FE/BE/QA/Security/DevOps） | 角色子代理 + 任务 DAG 派发可用 |
| 4 | Quality Gate | Gate 自动验证 + 失败回退 | 注入缺陷能 FAIL→修复→PASS |
| 5 | Human Intervention | 暂停/恢复/停止/审批/修改 | 用户可在任一阶段干预 |
| 6 | Requirement Change | 影响分析 + 增量执行 | 改需求只重跑受影响任务 |
| 7 | Production Trial | 真实软件交付（React+FastAPI+PostgreSQL+Docker） | 项目可运行 + 全套产物 |

---

## Phase 1 — Factory Preset

### 1.1 目标
创建 `software-factory` Agent Preset，让一个 DSH Agent 成为 **Factory Manager**：能理解需求、澄清、拆解为项目计划（Epic/Feature/Story/Task + DAG）、产出标准 Artifacts。

### 1.2 实施步骤

1. **加载技能**：先加载 `editing-cordis-compositions` 与 `cordis-plugin-development` 技能（写 preset 前必须）。
2. **创建 preset 目录**（复制官方 `standard`，绝不修改 shipped）：
   - 通过 `agentPresets.copy('standard', 'software-factory')`（官方 authoring 路径）或手动复制 `~/.npm/_npx/…/dsh/config/agent-presets/standard/` → `~/.dsh/.agent-presets/software-factory/`。
   - 若选 cordis 为底（需要自指工具集），复制 `cordis`。
3. **修改 `preset.yml`**：`name: 软件工厂模式`、`description: AI Software Factory Manager…`。
4. **修改 `agent.cordis.yml`**：
   - `persona` 文本 → Factory Manager 完整职责（需求理解/规划/拆解/调度/监控/恢复/人类协作），含 Artifact-first、Evidence-over-claims、状态机、Quality Gate 纪律。
   - 新增 `skills/` 目录：先放 1–2 个核心技能（`factory-project`：项目骨架/状态机/Artifact 模板；`factory-dispatch`：角色委派与契约注入）。技能格式 `<skill>/SKILL.md`（frontmatter + 指令）。
   - 保留 standard 的既有行（tools/skills/goal/plan/compaction/delegation 等）不动。
5. **工厂模板落地**（workspace `ai-software-factory/templates/`）：
   - `project-skeleton/`（project.json、artifacts/、tasks/、contracts/、memory/、reports/、logs/）
   - `artifact-templates/`（requirements.md、product-spec.md、user-stories.yaml、architecture.md、api-spec.yaml、database-schema.sql、implementation-plan.md、test-plan.md、release-notes.md）
   - `contract-templates/`（role-contract.yaml、gate-defs.yaml）
   - `scripts/`（`project-init.sh`、`state-read.sh`、`state-write.sh` 或 Node 小工具，供 Manager 经 bash 调用）

### 1.3 验证清单（规格书第 36 节）
- [ ] `agentPresets.list()` 含 `software-factory`（trust=user），`resolve('software-factory')` 成功
- [ ] 新会话选择该 preset（settings 或 UI）→ `Tool.listTools` 与 standard 一致 + 无多余行
- [ ] `skills.snapshot()` 含 `factory-project` / `factory-dispatch`；`skill('factory-project')` 可加载
- [ ] 手工跑一次：输入"做一个 Todo SaaS（React+FastAPI+PostgreSQL）" → 产出 `implementation-plan.md`（Epic/Feature/Story/Task + DAG + 角色分配）+ `project.json`（状态 REQUIREMENT_APPROVED）
- [ ] 文件与 storageDomain 记录一致
- [ ] 官方 4 preset 未被动过（diff 校验）

### 1.4 风险与对策
- preset 行归属错误 → 按 `editing-cordis-compositions` 技能诊断（realm/plane 规则）。
- 复制失败（id 冲突/非法）→ 检查 id 合法性，删除残留目录后重试。

---

## Phase 2 — Production Workflow

### 2.1 目标
跑通**第一个完整生产闭环**：Requirement → Architecture → Implementation → Testing → Review（对一个最小 Todo 项目）。

### 2.2 实施步骤
1. **阶段脚本化**：把 Phase 1 手工流程固化为 `factory-stages/` 下每阶段一个检查清单 + 脚本：
   - `stage-requirement`：澄清（ask_user_question）→ requirements.md → Gate（覆盖率）
   - `stage-architecture`：架构子代理产出 architecture.md/api-spec/db-schema → Gate（一致性审查）
   - `stage-implement`：按 implementation-plan 派发子代理写码（每任务：任务 yaml + 验收）→ 任务状态机
   - `stage-test`：跑测试（bash/jobs）+ QA 子代理 → test-report → Gate
   - `stage-review`：Review 子代理（读 diff + 代码）→ review-report → Gate
2. **闭环驱动器**：Manager 用 Goal（`create_goal` 目标 = "完成示例项目到 DELIVERED"）自动续轮；每轮恢复 `project.json`，执行当前阶段的一批动作。
3. **首次全流程演练**：Todo 项目（最小可用：FastAPI CRUD + React 单页 + SQLite 起步，PostgreSQL 留 Phase 7）。

### 2.3 验证清单
- [ ] 项目从 PROJECT_CREATED 走到 ACCEPTANCE（状态机事件序列正确记录）
- [ ] 每个阶段产物齐全且 Gate 通过记录在 reports/
- [ ] 至少一次**人工制造的失败**（如给子代理错误 spec）→ 恢复协议生效（retry/拆分/换人）
- [ ] 子代理事件（subagent/start、subagent/end）可观察

### 2.4 风险与对策
- 子代理上下文膨胀 → 任务缩小 + `toolResultPruner`/compaction 已有兜底；task 拆分。
- workflow run 中途断 → 每阶段幂等（读状态→执行→写状态），重跑安全。

---

## Phase 3 — Agent Team

### 3.1 目标
动态角色调度：按项目需要 spawn PM/Architect/FE/BE/QA/Security/DevOps 角色子代理，任务 DAG 派发。

### 3.2 实施步骤
1. **角色技能包**：为每个角色建 `<skill>/SKILL.md`（frontend-development、backend-development、database-design、testing、security、architecture、product-management、devops…），放 `~/.dsh/.agent-presets/software-factory/skills/`（随 preset 旅行）或项目级 `.agents/skills/`。
2. **派发器**：`scripts/dispatch.js`（或 Manager 内逻辑）：读 `tasks/ready` → 按 role 构造委派 prompt（契约 + 任务 + artifacts 路径 + outputSchema）→ `subagent`（continuable）→ 记录 childId 到任务 yaml → 收结果 → 更新状态。
3. **并行纪律**：默认并行 ≤3；同一角色串行复用同一子代理；`send_message` 续投递后续任务。
4. **角色池观察**：`list_agents`（children/descendants）定期记录到 `reports/agents.md`。
5. **（可选）agentTeams 验证**：Inspect 目录存在 `agentTeams` 契约但 Provider 未装——先验证 live store 是否提供；不提供则跳过，用自建任务表（不影响本阶段目标）。

### 3.3 验证清单
- [ ] 同一示例项目：后端任务由 backend 子代理完成、前端由 frontend 子代理完成（list_agents 可区分）
- [ ] 任务 DAG：依赖任务顺序执行；并行任务同时 running（job/agent 状态）
- [ ] 角色契约（contracts/<role>.yaml）随委派注入且子代理遵循（抽查产物符合 output）
- [ ] 失败换人路径：同任务 2 次失败 → fresh spawn → 成功

### 3.4 风险与对策
- 子代理互相覆盖文件 → 任务级文件边界（outputs 声明）+ Manager 在派发间做集成校验。
- 角色记忆漂移 → 关键约束写进每次委派 prompt（契约非人肉记忆）。

---

## Phase 4 — Quality Gate

### 4.1 目标
Gate 自动执行 + 失败自动回退（FAIL → RETRYING → 修复 → 重跑 → PASS）。

### 4.2 实施步骤
1. **Gate 执行器**：`scripts/gates/` 下每类 Gate 一个脚本/清单：
   - test-gate（跑 pytest/jest，退出码 + 覆盖率阈值）
   - lint-gate（eslint/ruff，规则文件）
   - build-gate（构建命令 + 产物存在性）
   - security-gate（依赖审计 + OWASP 清单审查子代理）
   - review-gate（Review 子代理输出结构化 verdict：approve/request-changes + 理由）
2. **Gate 编排**：阶段出口调用对应 Gate；结果写 `reports/<stage>-gate.md` + 状态机迁移（FAILED→RETRYING，PASS→下一阶段）。
3. **回退闭环**：RETRYING 时派发修复任务（可带 Gate 输出作为输入），修复后重跑 Gate；超过 attempts 上限 → 升级（第 9 节恢复协议）。

### 4.3 验证清单
- [ ] 故意注入 bug（如改坏一个路由）→ test-gate FAIL → 修复任务自动派发 → PASS
- [ ] 安全 Gate 能发现已知漏洞模式（如硬编码 secret / 未锁版本）
- [ ] Gate 结果可审计（reports/ 留下每次执行的证据）

### 4.4 风险与对策
- Gate 脚本本身有 bug → 先对 Gate 做单元验证（用已知好坏输入测）。
- 覆盖率阈值虚高 → 阈值写进项目配置，允许按项目调整并记录理由。

---

## Phase 5 — Human Intervention

### 5.1 目标
用户在任一阶段可 Pause/Resume/Stop/Approve/Reject/Modify/Redirect。

### 5.2 实施步骤
1. **暂停/恢复**：Manager 在每轮开头检查会话 Goal 状态（`get_goal`）与项目 `project.json.status`；用户说"暂停"→ `update_goal(pause)` + 状态 PAUSED（冻结派发）；"继续"→ resume。
2. **审批点**：需求澄清（ask_user_question 选项）、危险操作（approval）、阶段 Gate 汇总（可选"继续/调整"确认）。
3. **重定向**：用户在任意点给出修改 → 记录到 `memory/redirects.md` → 变更引擎（Phase 6）或当前任务重派。
4. **UI 辅助（可选）**：动态插件在 `conversation.session.header.actions` 或 `conversation.input.dock` 挂"暂停/继续"按钮（Client half 调 `host.call` → Host half 调 goals 服务）；实验性，Phase 5 未期。

### 5.3 验证清单
- [ ] 实现中途说"暂停"→ 状态 PAUSED，无新任务派发；"继续"→ 从断点续跑
- [ ] "停止后端开发，把 PostgreSQL 改 MySQL" → 进入变更流程（见 Phase 6 验证）
- [ ] 所有审批点在会话中可见（approval 记录）

---

## Phase 6 — Requirement Change

### 6.1 目标
影响分析 + 变更计划 + 用户确认 + 增量执行。

### 6.2 实施步骤
1. **依赖图解析**：`scripts/impact.js` 解析 artifacts/tasks 的 `dependsOn/consumes/producedBy` → 图。
2. **影响分析**：输入变更描述（或 requirements.md diff）→ 标记受影响节点 → 输出变更计划（受影响 artifacts/tasks + 建议动作 + 估算）。
3. **确认**：`ask_user_question`（计划 + 选项：执行/调整/放弃）。
4. **增量执行**：状态机回退到受影响阶段 → 只重跑受影响子树 → 重新走对应 Gate。
5. **记录**：变更入 `memory/changes/<n>.md`（影响图 + 决定 + 执行摘要）。

### 6.3 验证清单
- [ ] 变更"数据库 PostgreSQL→MySQL"：架构/api/db/code/tests 受影响节点被标记；无关模块（如前端样式）未重跑
- [ ] 变更计划先展示、经确认后才执行
- [ ] 完成后项目仍通过全部 Gate

---

## Phase 7 — Production Trial

### 7.1 目标
Factory 真实生产一个可运行软件：**React + FastAPI + PostgreSQL + Docker**（Todo 或 Knowledge Base SaaS）。

### 7.2 实施步骤
1. 输入完整需求（如规格书 §0 示例）→ 走 Phase 1–6 全流程。
2. **后端**：FastAPI + SQLAlchemy + PostgreSQL（docker-compose 起 PG）；JWT 注册/登录、Todo CRUD。
3. **前端**：React（Vite）+ 登录/注册/Todo 页面，接 API。
4. **AI 能力（可选增强）**：若需求含 RAG/对话，由 AI Engineer 子代理实现（chunking/embedding/检索接口）。
5. **Docker**：Dockerfile（前后端）+ docker-compose.yml（web + api + db + volumes）。
6. **全量 Gate**：test/lint/build/security/performance + 部署冒烟（Manager 层 `docker compose up` + 健康检查，需审批）。
7. **交付物**：源码树 + Dockerfile + docker-compose.yml + README + API 文档 + DB schema + 测试报告 + 安全报告 + 构建报告 + 发布说明（release-notes）。

### 7.3 最终验收（规格书 §37）
- [ ] `docker compose up` 后前端可访问、注册/登录/Todo CRUD 真实可用（健康检查证据存 `reports/`）
- [ ] 全部产物存在且与实现一致（artifact hash 记录）
- [ ] 每个 Gate 的 PASS 证据在 reports/（Evidence over claims）
- [ ] 用户可回看：项目状态机全历史、任务表、失败/恢复记录、变更记录
- [ ] 整个项目目录可独立复制/重新恢复（恢复演练：新会话读 project.json 继续）

---

## 横切工作项

| 项 | 何时 | 说明 |
|---|---|---|
| 事件与记账 | Phase 2 起 | 事件写 project.json + storageDomain；budget 记账（tokenMeter 估算） |
| 日志 | 全程 | 每任务 logs/；失败进 memory/failures.md |
| 文档同步 | 每阶段 | 更新 ai-software-factory/docs/（本计划 + 架构随实现修订） |
| 安全 | 全程 | 不关闭 sandbox/approval；子代理固定 never-approval；危险操作 Manager 层 + 审批 |
| Git | 全程 | Factory 自身代码（ai-software-factory/）按实现步骤提交；被生产项目独立 git init |
| 恢复演练 | Phase 2/4/7 | 模拟进程重启（新会话继续项目）验证恢复 |

---

## 完成定义（Definition of Done）

- `software-factory` preset 独立可加载、可验证、可回滚，官方 preset 零改动。
- 一次完整生产（Phase 7 示例）跑通，交付可运行项目 + 全套产物。
- 恢复、失败、变更、人类干预四条路径都有演练证据。
- 每项能力以实测为准：任何新 API 依赖先 Inspect，不猜。

---

## 下一步（等待确认）

按规格书 STEP 9：**等待用户确认后进入 Implementation**。

用户确认后，第一件事（Phase 1 起步）：
1. 加载 `editing-cordis-compositions` 技能
2. `agentPresets.copy('standard'|'cordis', 'software-factory')` 建 preset
3. 写 persona/skills/模板 → 验证（§1.3 清单）→ 提交
