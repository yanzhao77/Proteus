# Runtime Capability Map

> AI Software Factory — Phase 0 Discovery 产出
> 本文档基于**当前运行时的实际检查结果**编写（Inspect / Read，非推测）。
> 检查时间：2026-08-21 · 检查人：DeepSeek Harness Agent（Creator Mode，cordis preset）
> 会话：`session-b12df22b-c4f1-49f7-bd43-d924b78bcb72` · 工作区：`/Users/sjw/Documents/GitHub/Proteus`

---

## Harness

| 项 | 值 | 证据 |
|---|---|---|
| 版本 | `0.1.0-rc.7`（`@deepseek-ai/dsh`） | `dsh --version` |
| 运行形态 | Web profile（`dsh --profile web`） | `~/.dsh/profiles/web/package.json` → bundles: `@deepseek-ai/dsh-base` + `@deepseek-ai/dsh-web-app` |
| Node / npm | v22.23.2 / 10.9.8 | `node --version` |
| DSH_HOME | `/Users/sjw/.dsh` | 环境变量 + `~/.dsh` 布局确认 |
| Web GUI | `http://127.0.0.1:3080` | `DSH_WEB_URL` |
| 默认模型 | provider `deepseek-official` / model `deepseek-v4-flash` / reasoningEffort `high` | `~/.dsh/settings.yaml`（hot-reload） |
| 默认 Agent Preset | `cordis`（创造模式） | `~/.dsh/settings.yaml` → `agent-presets.default: cordis` |
| 会话持久化 | 每会话一个 append-only JSONL（zstd 压缩）：`~/.dsh/sessions/<workspace-key>/<session-id>/session.jsonl.zstd` | 实际文件确认 |
| 凭据 | `~/.dsh/.credentials.yaml`（provider-managed，含 `DEEPSEEK_API_KEY`）；`~/.dsh/.anonymous-user-id` | 文件确认（值已脱敏） |
| 部署组成方式 | profile 根 `cordis.yml = []`，由 bundle 的 `cordis.patch.yml`（`dsh-base`、`dsh-web-app`）+ 用户 `cordis.patch.yml` 以 **patch layer** 叠加 | `~/.dsh/profiles/web/*.yml` |
| 官方安装位置 | `~/.npm/_npx/1e7f6d9597241db0/node_modules/@deepseek-ai/dsh/`（CLI 缓存，含 `config/agent-presets/`） | 路径确认 |
| 运行时 plugin 集 | `~/.dsh/profiles/node_modules/@deepseek-ai/`（约 190 个 `dsh-*` / `cordis-*` 包） | 目录枚举 |

**结论**：这是一个"单进程 Web 部署"的 DSH。所有能力都是 Cordis 插件行（composition），通过 patch layer 组合；官方 preset 只读，用户可写根为 `~/.dsh/.agent-presets/`。

---

## Cordis

- 本运行时的一切能力 = **`cordis.yml` 中的插件行（plugin row）**；组合以 **patch layer** 覆盖（按 id 定向替换 `config`、`disabled`、`insert` 列表）。
- 每行形如 `{ id, name: '@deepseek-ai/dsh-xxx', config?, inject?, disabled?, group?, isolate? }`。
- **激活是服务可用性驱动**，行顺序不承载加载语义。
- 服务注册：`ctx.provide(name, value)`；硬依赖用 `inject: ['serviceName']`（进入 waiting 直至服务出现）；可选依赖 `ctx.get('serviceName')`。
- 事件系统：`emit` / `serial` / `parallel` / `waterfall` 四种模式（Inspect 目录给出每种事件的 mode）。
- **Scope（`dsh-scope`）**：agent 的视图解析链为 `agent → preset → global`（就近遮蔽）。preset 的 standing mount 挂在 preset 层，每个加入该 preset 的 session 通过 scope parentage 共享同一实例，状态按 Session/Agent 各自隔离。
- **Realm / isolate**：preset 内的服务行必须放在带 `isolate` 的 group 中，否则发布到 root realm（进程全局），第二个 session 挂载即冲突，`dsh-agent-presets` 会拒绝 mount。
- 动态插件（`dsh-cordis-host-runner` + `dsh-tool-cordis`）：`cordis_define/run/stop/undefine` 在 vm sandbox 中求值 model 编写的 JS，进程内存存活，**不跨重启**。
- Typert：`ctx.typert` 注册生成式 schema；`typertGateway.invoke` 可调用 `@Remote` 方法（API 网关的远程面）。

---

## Host Plane

Host 组成 = `dsh-base` bundle + `dsh-web-app` bundle + 用户 patch。Host 持有**进程级、跨 session 共享**的一切：

- **注册表类**：`tools`（工具注册表 + 执行管线）、`skills`（分层技能注册表）、`subagents`（子代理注册表 + spawn/fork 后端）、`commands`（人类命令注册表）、`typert` / `typertGateway`（schema 与 Remote 调用）、`sessionProjections`（投影单元表）、`jobs`（后台任务注册表）、`storage`（存储 hub）、`settings`（热重载设置文档）、`credentials`、`webServer`（HTTP 路由）。
- **沙箱/审批栈**：`sandbox`、`sandboxPolicy`、`bash-sandbox`、`pwsh-sandbox`、`approval`（`dsh-user-approval`，policy `ask`）、`permissionPresets`、`fs-sandbox`、`fs-observation-policy`。
- **持久化**：`sessionPersistence`（jsonl append-only）、`sessionProjectionCache`、`sessionQuery`（SQLite，当前 `openAt: never`）、`attachments`、`storageDomain`（domain KV，json backend → `~/.dsh/storages/`）、`workspaceRegistry`。
- **模型路由**：`llm`（adapter 注册表 + `llm/stream` waterfall）、`llm-deepseek`、`llm-pi-ai`（dormant）、`agentDefaultModel`、`llmRetry`。
- **Agent 基础设施**：`agentLoop`（agent 工厂/驱动）、`agents`（live agent 注册表）、`session` / `sessions`（内存 session 存储）、`goal` + `goalRoundDriver`、`planMode`、`compaction`、`tokenMeter`、`spill`、`checkpoint`。
- **Web 传输**：`webStartup`、`webserver`、`webRuntime`、`clientModules`（浏览器 roster）、`clientConnection`、`apiGateway`（`dsh-host-apiproxy`）、`cordisHostRunner`、`codeRuntime`、`pluginInventory`、`client-hmr`。
- **工具执行后端**：`shell`（`dsh-bash-sandbox` 实现）、`subprocess`、`terminals`、`shellEnv`（`DSH_*` 变量）。
- **会话基础设施**：`sessionTitle`、`sessionStats`、`sessionReference`、`messageFeedback`、`sessionTelemetry`（默认 DISABLED）、`sessionCheckpointPolicy`。
- **服务（Inspect 目录实测 key）**：`agentDefaultModel, agentLoop, agentPresets, agents, agentTeams*, apiProxy, approval, attachments, clientModules, codeRuntime, commands, compaction, credentials, directoryPicker, e2b, fileReferences, fs, goals, invariants, jobs, llm, lsp, messageFeedback, permissionPresets, planMode, sandbox, sandboxPolicy, sessionPersistence, sessionProjectionCache, sessionProjections, sessionQuery, sessionReferenceResolver, sessions, sessionTelemetry, sessionTitle, settings, shell, shellEnv, skills, spillStore, storage, storageDomain, subagents, subprocess, systemPrompt, terminals, timer, tokenMeter, toolResultPruner, tools, typert, typertGateway, userQuestions, web, webServer, workflowEngine, workspaceRegistry`。

> ⚠️ `agentTeams`：仅在 **Inspect 编译期目录**中存在（monorepo 静态投影），其 Provider **未安装于本部署**（`node_modules` 与 host 组成中均无）。依赖前必须先验证/选装。

---

## Agent Plane

- 一个 preset = 一个目录：`agent.cordis.yml`（顶层插件行列表）+ 可选 `preset.yml`（仅展示元数据 `name`/`description`，`id` = 目录名）。
- preset 由 `dsh-agent-presets` 的 roster **每进程挂载一次**（standing mount，standing scope），命名它的每个 session 通过 scope parentage 加入；同一实例覆盖所有加入的 agent，插件内部状态按 Session/Agent 键控。
- **Agent plane 可贡献**：工具行（注册进该 agent 可见的工具目录）、persona / prompt sections（`dsh-persona`、`dsh-agent-instructions`、`systemPrompt.section`）、隔离 realm 内的私有服务、技能目录（`skill-filesystem` customSkillDirs）、投影单元。
- **Agent plane 不可拥有**（必须留在 Host）：注册表本身、沙箱/审批栈、持久化、模型路由、`shell-env`、`tokenMeter`、`tool-subagent-report`（continuable setup 非 scope-aware，多 mount 会重复注册抛错）。
- **子代理组合**：子代理通过 `agentPresets.composeFrom(childCtx, parentCtx)` 加入父代理的 standing composition（bind 而非 mount），否则子代理工具目录为空。
- **空 agent 可切换 preset**：`agentPresets.recompose()`（仅限未产生任何内容前；`agent-preset-locked` 保护）。
- 每个会话创建时在 header 记录 preset id；`resolveSessionPreset(session)` 解析实际运行 preset；切换会追加 `agent-preset/selected` 事件。

---

## Agent Presets

官方 shipped root（只读，`system` trust）：`<dsh安装>/node_modules/@deepseek-ai/dsh/config/agent-presets/`

| preset | 名称 | 内容 |
|---|---|---|
| `standard` | 标准模式 | 完整编码 Agent：bash、fs 工具、jobs、skills、goal、plan mode、compaction、subagent(spawn/fork)、workflow、ralph、ask-user、todo、web |
| `code` | PTC 模式 | = standard + `dsh-agent-tool-presentation`（Code Mode，TypeScript SDK 组合多步操作） |
| `minimal` | 极简模式 | 仅持久 bash + str_replace_editor 双工具，固定 prompt，无 compaction |
| `cordis` | 创造模式 | = standard + `tool-cordis`（自指工具集：inspect/define/run/stop/undefine）+ 自定义 persona（两平面说明）+ 随 preset 携带的 `skills/` 目录（editing-cordis-compositions） |

用户可写根（`user` trust，authorable）：`$DSH_HOME/.agent-presets/`（当前**尚不存在**，`agentPresets.authorable = true`）

Authoring 机制（`ctx.agentPresets`）：
- `list()` / `resolve(id?)`（无记忆化，每次重读根目录，热可见）
- `copy(from, id, name?)` — **唯一的官方 authoring 写入**（整目录复制、symlink 解引用、权限收紧、重写 preset.yml 去掉 name/order）
- `remove(id)`（拒绝删除 shipped preset）、`read(id)`、`mount(agentCtx, id?)`、`recompose()`、`standingKeyFor()`、`composeFrom()`
- id 约束：`[a-z0-9][a-z0-9-]*`；重复 id 拒绝；损坏目录以 `broken` reason 列出而非跳过
- 行解析：包名从 **Host 组成**解析（非 preset 目录），相对路径从 preset 自身目录解析（技能目录随 preset 旅行），绝对路径保持原位
- 配置文件 `~/.dsh/settings.yaml`：`agent-presets.default: <id>` 可覆盖部署默认（当前为 `cordis`）

**重要**：不要修改 shipped preset。要改变能力 → 复制 `standard`（或 `cordis`）到 `~/.dsh/.agent-presets/<new-id>/` 后修改副本。

---

## Plugins

- Host 组成插件约 190 个 `@deepseek-ai/dsh-*`（见 `~/.dsh/profiles/node_modules/@deepseek-ai/` 枚举）。
- 关键业务能力插件（均可直接作为 preset 行复用）：
  - `dsh-agent-presets` — preset roster / mount / copy / recompose
  - `dsh-agent-loop` — agent 工厂与驱动（`agentLoop.create/createAgent/resume`）
  - `dsh-subagent` + `dsh-subagent-spawn-in-process` + `dsh-subagent-fork-in-process` — 子代理注册表与 in-process 后端
  - `dsh-workflow` + `dsh-workflow-worker-thread` + `dsh-tool-workflow` — 编排脚本引擎
  - `dsh-goal` + `dsh-goal-round-driver` + `dsh-tool-goal` — 持久目标与自动续轮
  - `dsh-storage` + `dsh-storage-json` + `dsh-storage-domain` — 持久 domain KV
  - `dsh-workspace` — workspace 注册表
  - `dsh-tool-cordis` + `dsh-cordis-host-runner` — 动态插件工具集
  - `dsh-skill` + `dsh-skill-filesystem` + `dsh-tool-skill` — 技能注册表与本地发现
  - `dsh-system-prompt` — prompt assembly（section/context/tools/variable）
  - `dsh-tools` — 工具注册表（`register/restrict/guard/presentAs`）
  - `dsh-jobs-local` — 后台任务注册表
  - `dsh-plan-mode`、`dsh-compaction-*`、`dsh-token-meter`、`dsh-llm-*`、`dsh-session-*`、`dsh-client-*` 等
- 动态 Plugin（本 session 可实验）：见下文 "Dynamic Plugin" 节。

---

## Tools

当前会话（cordis preset）实际可见工具目录（`Tool.listTools` 实测）：

| 类别 | 工具 |
|---|---|
| Shell | `bash`（沙箱执行、background jobs、`sandbox_permissions` 一次性升级） |
| 文件系统 | `read`, `write`, `edit`, `glob`, `grep`, `read_image` |
| 后台任务 | `job_output`, `job_list`, `job_kill` |
| 用户交互 | `ask_user_question`, `exit_plan_mode`（plan mode 时） |
| 检索 | `web_search` |
| 技能 | `skill`（加载技能目录） |
| 计划/目标 | `todo_write`, `create_goal`, `get_goal`, `update_goal` |
| 委托 | `subagent`（spawn，continuable）、`subagent_fork`（fork）、`list_agents`, `interrupt_agent`, `send_message` |
| 编排 | `workflow`（JS 编排脚本）、`ralph`（fresh-agent 循环） |
| 自指 | `cordis_inspect_list`, `cordis_inspect_query`, `cordis_inspect_self`, `cordis_define`, `cordis_run`, `cordis_stop`, `cordis_undefine` |

工具注册表 `ctx.tools` 提供 `register(definition)` / `restrict(filter)` / `guard(guard)` / `schemas()` / `execute()`；预设行可注册该 agent 专属工具；动态插件可经 `harness.registerTool(ctx, tool)` 注册。
`tools/pre-execute`（allow/deny/ask）、`tools/post-execute`、`tools/result`、`tools/execute`（waterfall）构成工具级治理面——Factory 可在此加审批/审计/预算钩子。

---

## Subagents

- 注册表 `ctx.subagents`（Host 单例）：`registerProvider/getProvider/list/start`。
- 本部署后端：`spawn`（`dsh-subagent-spawn-in-process`）、`fork`（`dsh-subagent-fork-in-process`）；`codex` / `claude-code` 已 disabled（未安装，如要使用需在 Host plane 选装 Provider 并去掉预设行 disabled）。
- **one-shot**：一次性前台委托，`SubagentRun.result` 收结果，无冷恢复。
- **continuable**（`startContinuable`）：持久子会话 + 每消息 FIFO turn；`followup()`（父→子投递）、`reportFrom()`（子→父回报）、`interrupt()`（打断当前 turn，保留 inbox）、cold resume（从持久化描述符重建）；`drainContinuableChildren/Descendants` 收尾。
- 子代理继承：`composeFrom` 加入父的 preset 组成；**权限**：继承父 sandbox 作用域，且当 approval 服务存在时子代理 approval policy **固定为 `never`**（委派边界决定，无法在子代理内 ask）。
- 事件：`subagent/start`、`subagent/end`（scoped 到父）、`subagent/provider-added/removed`。
- 子代理持久描述符（`subagent/descriptor` session 事件）：provider、mode、label、agentOptions——cold resume 的完整重建输入。
- 深度：`subagentDepth` / `delegationDepthOf` 单调计数，`assertSubagentMaxDepth` 封顶。
- 工具形态（模型面）：`subagent` 默认 background continuable；`subagent_fork`（继承父会话历史）；`send_message` 后续投递；`list_agents`（children/descendants 视图：running/idle/ready）；`interrupt_agent`。
- 子代理也可以有自己的 persona/toolFilter/outputSchema（provider capability：`outputSchema`、`depthLimit`、`toolFilter`、`persona`）。

**对 Factory 的意义**：continuable 子代理 = 天然的"Factory Agent 角色实例"（持久会话、可复现、可打断、可续跑）；spawn 的一次性委托 = 单任务执行单元。

---

## Workflows

- 服务：`ctx.workflowEngine.start(request)` → `WorkflowRun`；`WorkflowRun.result` 永不 reject（失败以 `stopReason: 'error'` 呈现）。
- 请求：`{ meta: {name, description, phases?}, script, args?, subagentProvider?, maxTotalAgents?, parent, signal? }`。
- 脚本 hooks：`agent(prompt, opts?)`（含 `schema` 结构化输出、`label`、`phase`、provider/model 覆盖）、`pipeline(items, ...stages)`（无 barrier 多阶段）、`parallel(thunks)`（barrier）、`phase(title)`、`log(msg)`、`args`。
- 失败纪律：`WorkflowError` 带 code + `fatal`（`SCRIPT_PARSE`/`META_INVALID`/`AGENT_START`/`AGENT_CAP`/`RESULT_UNSERIALIZABLE`/`CANCELLED`…）；致命错误穿透 pipeline/parallel；普通子代理失败返回 `null` 由脚本处理。
- 事件：`workflow/start`、`workflow/end`、`workflow/phase`、`workflow/log`、`workflow/agent-start`、`workflow/agent-end`（observe-only，UI 可订阅）。
- **已知限制**：仅前台收集（无后台启动/poll）；**无 journaling / 无 resume**（进程重启不能继续 run）；无嵌套 workflow；无 token 预算词汇；run 由 holder 拥有（必须 `dispose()`）。
- 引擎：`dsh-workflow-worker-thread`（worker thread 隔离执行）。

**对 Factory 的意义**：workflow 脚本 = 生产流水线执行器（并行 fan-out、pipeline 阶段、结构化结果）；但**不能**作为长期运行的项目状态机（无恢复）——长流程必须拆为离散 run + 持久状态，或用 Goal 自动续轮驱动。

---

## Sessions

- `ctx.sessions`（内存存储）：`create/prepare/enter/announce/flush/get/list/fork`。
- `ctx.agentLoop`：`create(id, options, meta)` / `createAgent(ownerCtx, options)` / `resume(ownerCtx, options)`。
- 持久化：`dsh-session-persistence-jsonl`（append-only JSONL，zstd，root `~/.dsh/sessions`）；`sessionPersistence.load/readFrom/list/inspect`。
- `sessionQuery`：`readSession/readSurface/filterEvents/listEvents/traceSession`（SQLite 全文检索 opt-in，当前 `openAt: never`）。
- 投影：`sessionProjections.register(def)`（每 session 的投影单元表，`sessionProjectionCache` 持久化缓存）、`sessionProjectionCache.coldSnapshot`。
- 派生：fork（`sessions.fork`，继承历史）、`sessionReferenceResolver`（跨会话引用）、`sessionTitle`、`sessionStats`、checkpoint（每模型请求前持久化检查点）。
- 事件：`session/created`、`session/disposed`、`session/event`（post-commit feed）、`session/flush`（并行持久化闸）、`agent/session-start`、`agent/created`、`agent/status`、`agent/error`、`agent/pre-step`（waterfall，可替换进入 step 的消息）、`agent/request`、`agent/request-error`、`agent/turn-stopping`。
- 会话事件流（SessionEvent）是可追加的：动态插件可用 `session.event` 或 domain 记录持久化 Factory 自己的事件词汇。

---

## Storage

- `ctx.storage` hub：`mount(form, facility)`、`form(name)`；backend 注册表。
- 后端：`storage-json`（文件 JSON，root `~/.dsh/storages/`，如 `session_projcache.json`、`workspace.json`）。
- **`ctx.storageDomain`（domain KV）**——Factory 项目记忆的首选持久化原语：
  - `defineDomain(spec)`（zod record schemas）→ `open(spec)` → `Domain` 句柄（读同步、写串行、先落盘后更新内存、`domain/changed` 事件、`close()` 幂等）。
  - 配置：`backend`（默认 json）、`routes`（per-domain 后端路由）。
  - 限制：单进程变更可见性（无跨进程 revision）、无跨表事务、无二级索引、无多段 key。
- `ctx.workspaceRegistry`：`create(path, title)` / `list` / `get` / `delete` / `resolveByPath` / `archiveSession` —— 独立项目工作区注册。
- `attachments`（不可变二进制）、`spillStore`（大文本 spill）、`sessionProjectionCache`、`messageFeedback`（domain sidecar 示例）。

---

## Sandbox

- `ctx.sandboxPolicy`：`defaultMode`（默认 `workspace-write`，`DSH_PERMISSION_MODE` 可覆盖）、`workspaceRoot`（= `process.cwd()`，本会话为 `/Users/sjw/Documents/GitHub/Proteus`）、`resolve(request)`、`overrideOf(session)`。
- `ctx.sandbox.confine(argv, policy)`：进程级限制（本地实现 `dsh-sandbox-local`；Windows ACL / landlock 后备）。
- 本会话当前策略（运行时快照）：`workspace-write` —— 文件操作仅允许 session workspace；越界操作被拒（`[sandbox: file access denied]`），一次性升级需 `sandbox_permissions` + approval。
- 子代理：继承父 sandbox 作用域；approval 固定 `never`；`sandbox_permissions` 升级在子代理内被确定性拒绝 → 危险操作必须留在父级或显式策略。
- `fs-sandbox` 是 `ctx.fs` 的沙箱化实现；`fs-observation-policy` 要求写前读。
- 文件观察：`fs/observed`、`fs/write-intent`、`fs/edit-intent`（waterfall）——Factory 可用于文件变更审计。

---

## Approval

- `ctx.approval.request(req)` → `ApprovalOutcome`；`setPolicy(agent, policy)` / `overrideOf(session)`。
- 部署策略：`policy: 'ask'`（`DSH_PERMISSION_MODE == 'danger-full-access'` 时为 `never`）。
- `approval/request` waterfall —— 可挂自定义 answerer / 审计。
- 危险操作（`rm`、`sudo`、生产部署、凭据访问等）默认落在沙箱拒绝 + 审批升级路径；**不要关闭安全机制**。
- 动态 Client Plugin 的 `cordis_run` 会创建 approval 请求（awaiting-approval），用户批准/拒绝后才运行。
- 委派子代理 approval 固定 `never` → Factory 的生产任务（编码、测试）在子代理内执行安全；需要审批的操作由 Factory Manager（父级）自己执行。

---

## Dynamic Plugin

（Creator Mode 自指能力，`dsh-tool-cordis` + `dsh-cordis-host-runner`）

- 工具：`cordis_define`（定义包，不运行）→ `cordis_run`（运行/更新/回滚）→ `cordis_stop`（停止，保留定义）→ `cordis_undefine`（永久删除）；`cordis_inspect_*`（只读检查）。
- 生命周期：session 级、进程内存；不写文件、不改 `cordis.yml`、**不跨重启**；不能自动转正为持久插件（需走正式 preset/plugin 开发流程）。
- **Host half 可用 Builtin**：`ctx`（`get/on/provide/effect`）、`harness`（`handle(method, handler)` 包私有 Client RPC、`defineTool(definition)`、`registerTool(ctx, tool)`）、`console`、`btoa/atob`、`TextEncoder/TextDecoder`。纯 JS，无 TS/JSX/import。
- **Client half 可用 Builtin**：`ctx`、`React`（`createElement` 等）、`host.call(method, args)`（Client→Host 私有 RPC，仅 lossless JSON）、`styles.insert(css)`、`console`。
- **Client Slots**（动态 Client UI 的座位，实测目录）：`conversation.input.dock`（输入框上方整行，additive）、`conversation.session.header.actions`（会话头部按钮，additive）、`settings.section`（设置页，additive）、`sidebar.footer.action`（侧栏底部动作）、`shell.overlay`（全屏浮层）、`conversation.chat.turnTail`（每轮尾部链）、`tool.call.toolview`（keyed 工具卡片视图）、`tool.view.cordis`（包私有运行卡片区域）、`conversation.composer.dock`（输入框下方横带）等。
- 动态工具 schema 经 JSON 克隆规范化跨 realm；记录 JSON-invisible keys 会被拒。
- 信任边界：不是安全沙箱（model 写的 JS 可达 host-realm 助手），视为 shell 权限。

**对 Factory 的意义**：动态插件 = Factory Dashboard / 项目控制台 / 工具卡片 UI 的实验路径（Client half + `host.call`）；正式能力（preset、持久服务）必须落在 `~/.dsh/.agent-presets/` 或 Host 组成。

---

## Existing Skills

本会话可见技能目录（`skills` 注册表 + 会话注入）：

| skill | 用途 | 来源 |
|---|---|---|
| `cordis-plugin-development` | 动态 Cordis 插件开发：平台选择、Inspect Provider、define/run/repair/rollback、Client Slot/theme、动态工具 | cordis preset 内置 |
| `editing-cordis-compositions` | 编写/修改/验证 Cordis 组成：preset 编写、插件行归属、mount 验证 | cordis preset 随附 `skills/` 目录 |

技能发现机制（`dsh-skill-filesystem`）：
- 根优先级：`<project>/.dsh/skills`（100）→ `<project>/.agents/skills`（200）→ `customSkillDirs` → `~/.dsh/skills`（user-dsh，400）→ `~/.agents/skills`（500）。
- 格式：`<root>/<name>/SKILL.md` 或 `<root>/<name>.md`（frontmatter：`name`/`description`/`whenToUse`/`disable-model-invocation`/`user-invocable`），发现只扫一层。
- 当前 `~/.dsh/skills` 尚不存在；`customSkillDirs` 可让 preset 自带技能目录（cordis preset 即如此）。

**对 Factory 的意义**：专业能力（需求分析、架构、前端/后端开发、QA、安全…）做成 `<name>/SKILL.md` 技能包，按角色 preset 挂载——正是规格书第 16 节的目标。

---

## Reusable Components

可直接复用于 Software Factory 的运行时原语（均已实测存在）：

| 原语 | 服务/工具 | Factory 用途 |
|---|---|---|
| Preset 系统 | `agentPresets`（list/resolve/copy/mount/recompose） | `software-factory` 角色 preset；按项目动态创建角色 preset |
| 子代理 | `subagents` + `subagent`/`subagent_fork`/`send_message`/`list_agents`/`interrupt_agent` | 角色 Agent 实例（PM/架构/前端/后端/QA/安全/DevOps）、任务执行单元、失败重试/换人 |
| 编排 | `workflowEngine` + `workflow` 工具 | 生产流水线（requirement→architecture→impl→test→release）、并行 fan-out、结构化子代理结果 |
| 持久目标 | `goals` + `create_goal`/`get_goal`/`update_goal` | 工厂级长期目标、自动续轮驱动 |
| 持久记忆 | `storageDomain` + `storage`/`storage-json` | 项目状态机、任务表、Artifact 注册、决策记录、预算账本 |
| 工作区 | `workspaceRegistry` + `fs` | 项目独立 workspace、隔离、Git |
| 后台任务 | `jobs` | 构建/测试/部署的长任务监控 |
| 工具治理 | `tools` registry + `tools/pre-execute`/`post-execute`/`result` | Factory 工具、审批/审计钩子、成本钩子 |
| Prompt | `systemPrompt.section/context/tools/variable` | Factory Manager persona、契约注入、运行上下文 |
| 事件 | `session/event`、`domain/changed`、`workflow/*`、`subagent/*`、`agent/*`、`tools/*` | 可观察性事件流（Factory Dashboard 数据源） |
| 会话查询 | `sessionQuery`/`sessionProjections`/`sessionProjectionCache` | 项目历史回放、投影、dashboard 状态 |
| Web 扩展 | `webServer.register` + Client Slots | Factory Dashboard / 项目控制台 UI |
| 用户交互 | `userQuestions.ask`、`approval` | Human-in-the-loop：澄清、审批、暂停/继续 |
| 模型路由 | `llm`、`agentDefaultModel` | 按角色/任务选模型、成本控制 |
| 设置 | `settings` | 工厂配置（预算、默认值）热更新 |
| 状态检查 | `tokenMeter` | token 计量（无预算词汇，需自建账本） |

---

## Missing Components

规格书要求但**运行时未提供**、需由 Factory 构建的部分：

| 缺失能力 | 现状 | 构建路径建议 |
|---|---|---|
| Factory 项目状态机 | 无 | `storageDomain` 持久项目记录 + 状态迁移函数（Factory 自己的代码/技能） |
| 任务 DAG（依赖/并行/条件分支） | workflow 提供 pipeline/parallel 但无持久 DAG、无恢复 | 项目目录 `tasks/` 文件 + workflow 脚本解释执行；`agentTeams`（catalog-only）有 `createTask(blockers)` 可作未来选项 |
| Quality Gate | 无内置 | Factory 编排 + 验证逻辑（lint/test/build 退出码、覆盖率、安全检查）+ 独立 Reviewer 子代理 |
| 需求影响分析 / 变更引擎 | 无 | Factory 技能 + 产物依赖图（artifacts 引用追踪），增量重执行受影响任务 |
| 预算/成本控制 | `tokenMeter` 只计量不设预算 | Factory 账本（storageDomain）+ workflow/agent 预算参数 + 超预算 pause 询问 |
| Factory 事件词汇 | 有通用事件（workflow/agent/tools/session…） | 用 `domain/changed` + 自建事件追加，或在动态插件中定义 |
| Factory Dashboard UI | Slots 存在、无工厂视图 | 动态插件 Client half 挂 `conversation.input.dock`/`settings.section` + `host.call` |
| 角色 Agent 契约注册 | 无 | 契约 = 预设 persona + skills + 产物模板（artifacts/contracts/） |
| 多项目多用户组织 | workspaceRegistry 单层 | MVP 用 workspace 隔离；组织/团队/成员留给扩展点 |
| 部署 Provider 抽象 | 无 | 自建 `deployment-manifest.yaml` + 脚本（docker compose 起步） |
| 长期项目记忆恢复 | 会话可恢复、domain 可持久 | 项目目录 + storageDomain + 恢复文档模板 |

---

## Recommended Factory Architecture

（详见 `SOFTWARE_FACTORY_ARCHITECTURE.md` —— 摘要）

```
AI SOFTWARE FACTORY（构建于 DSH/Cordis 之上）
│
├── Factory Manager（software-factory preset 的 Agent）
│      persona/契约/skills/tools 由 preset 提供
│      用 workflow 脚本跑生产流水线，用 subagent 调度角色，用 goals 驱动长期目标
│
├── Factory 项目（每个项目 = workspace 目录 + storageDomain 记录）
│      artifacts/ tasks/ agents/ reports/ logs/ + project.json（状态机）
│
├── 角色 Agent = continuable subagent（持久会话）
│      PM / Architect / FE / BE / QA / Security / DevOps / Reviewer
│      每个角色有 Contract（persona + input/output + tools + skills + quality criteria）
│
├── 生产流水线 = workflow 脚本 + Quality Gate
│      Requirement → Architecture → Implementation → Integration → QA → Release
│      每阶段：Agent → Artifact → Validation → Gate（FAIL→修复循环）
│
├── Human-in-the-loop = userQuestions + approval + goal pause/resume
├── 可观察性 = 事件 + storageDomain 投影 + （未来）Dashboard 动态插件
└── 安全 = 遵守 sandbox/approval；危险操作留在父级；子代理固定 never-approval
```

设计要点（针对实测限制的决策）：
1. **持久状态在文件 + storageDomain，不在 workflow run 内**（workflow 无恢复）。
2. **长流程 = 离散 workflow run + Goal 续轮**（每轮恢复自项目状态文件）。
3. **任务执行 = 子代理 + 项目 artifacts 交接**（Artifact-first，而非聊天传递）。
4. **危险/审批操作 = Factory Manager 亲自执行**（子代理 approval=never）。
5. **正式能力落 preset（`~/.dsh/.agent-presets/software-factory/`），实验落动态插件**。
6. **不修改 Harness Core / shipped preset**；`standard`/`cordis` 只读参考，复制后修改。

---

## Risks

1. **Inspect 目录是编译期超集**：`agentTeams` 等目录条目可能无运行 Provider；实现前必须用 live store 验证。
2. **动态插件不跨重启**：任何依赖动态插件的能力都会在重启后消失；正式化必须转 preset/持久文件。
3. **Workflow 无 journaling/resume**：长流水线不能依赖单次 run 完成；进程重启会丢失 run 内进度。
4. **子代理 approval 固定 never**：委派给子代理的危险操作会确定性失败；必须由父级执行或显式策略。
5. **沙箱仅限 workspace**：Factory 项目必须位于 session workspace（当前为 Proteus 仓库内目录）或经审批升级；`workspaceRoot` 外的构建产物/依赖安装会受限。
6. **storageDomain 单进程**：跨进程/重启后 GUI 观察不到 domain 变更（领域数据在 json 文件，进程重启可重读，但无跨进程事件）。
7. **会话日志 zstd 二进制**：外部工具解析需要 zstd 支持（`dsh` 自带读写；手工读取需 `zstd` CLI）。
8. **默认模型单一**：deepseek-v4-flash 全角色默认；重任务（架构/审查）可经 subagent 的 model 参数换更强模型（需 provider 可用）。
9. **动态 Client 插件需 approval**：Dashboard 类的浏览器 UI 首次运行需用户批准。
10. **session-query SQLite 关闭**：全文检索当前不可用（`openAt: never`）；如需可按部署文档开启。

---

## Compatibility Concerns

1. **preset 复制后 id 必须合法**（`[a-z0-9][a-z0-9-]*`），且不能与既有 id 冲突（`copy()` 拒绝）。
2. **preset 内服务行必须带 isolate realm**，否则 mount 被拒；共享宿主服务的行（如 tool-bash 后端）留在 Host。
3. **不要给 preset 添加 `tool-subagent-report`**（非 scope-aware，重复注册抛错）；report 归 Host。
4. **动态插件 Host half 无 `ctx.effect`**（facade 只暴露 on/provide/register 的清理路径）——副作用清理用 `ctx.on` 或官方 disposer。
5. **Client 插件不能用 JSX/import**；React 用 `React.createElement`；跨 realm 只传 lossless JSON。
6. **workflow 脚本只能用 hooks**（`agent/pipeline/parallel/phase/log/args`），无 Node API（无 fs/net/timer）。
7. **子代理工具目录来自父 preset**（composeFrom）；若未来使用未挂 preset 的 Host 工具层，行为不同——测试时注意。
8. **settings 热重载**：`settings.yaml` 修改即时生效于新 session；运行中 session 的 preset 组成不变（stamp 机制）。
9. **模型缓存（KV cache）**：preset 工具集/提示变化会使请求前缀失效——Factory 能力演进时注意成本。
10. **本仓库（Proteus）已有独立软件工厂实现**（Hermes runtime，Python + PostgreSQL + React + Control Plane/Worker/Verifier/Evidence 架构）；本计划构建的是 **Harness/Cordis 原生**的 Software Factory（预设 + 子代理 + workflow + storageDomain），两者是不同技术路径，可互为参考（Proteus 的 Evidence/Authority/Recovery 思想可借鉴），但代码不混用。

---

## 检查方法附录（可复现）

- `dsh --version`；`env | grep DSH`
- `cat ~/.dsh/settings.yaml`；`ls ~/.dsh/{profiles,sessions,storages}`
- `cat <dsh>/config/agent-presets/{standard,code,minimal,cordis}/{preset.yml,agent.cordis.yml}`
- `cat ~/.dsh/profiles/web/cordis.yml`；`cat <base>/cordis.patch.yml`；`cat <web-app>/cordis.patch.yml`
- `cat <dsh-agent-presets>/README.md`（roster/authoring/mount 语义）
- `cat <dsh-subagent|dsh-workflow|dsh-storage-domain|dsh-tool-cordis|dsh-skill-filesystem>/README.md`
- 运行时 Inspect：`cordis_inspect_list` → `cordis_inspect_query`（Service.listService / Event.listEvents / Builtin.listBuiltins / Tool.listTools / Slots.listSubTree）
- `cordis_inspect_self`（本 session 动态插件；当前为空）
