# Proteus Factory Home Tailwind Theme & Effects V1.0

**状态：** 可直接采用的主题配置与样式实现规范。
**视觉方向：** **JARVIS 的精密指挥感 + TRON 的结构化能量边界**，受 NASA Mission Control 的事实纪律约束。
**适用范围：** Factory Home、Idea Composer、Portfolio、Action Required、Factory Status、Draft/Plan review 的共享视觉基础。
**不适用范围：** P0–P6 authority、Product API 语义、Project/Task/Execution/Gate 状态、真实事件传输、业务命令或数据持久化。

> 主题层只能渲染来自权威 Snapshot/Projection 的事实。它**不能**把 loading、动画、颜色、local storage 或按钮点击推断成 `Production Created`、`RUNNING`、`WAITING_FOR_HUMAN` 或任何其他后端事实。

## 1. Implementation Position

当前 Proteus 仓库没有 Tailwind、Node package manifest、React/Vue/Next/Vite 或通用 SPA；已落地的 Factory Workspace 是 FastAPI + server-rendered HTML 的显式非权威骨架。因此本交付物是**未来获批准的 Tailwind 前端的 reference pack**，而非对现有 Python runtime 的依赖注入或框架迁移。[1] [2]

在一个已批准的 Tailwind v3 frontend 项目中，复制以下两个文件并在根样式入口导入 effects layer：

| 文件 | 推荐目标位置 | 用途 |
| --- | --- | --- |
| `proteus_factory_tailwind_theme.ts` | `tailwind.config.ts` 或 `theme/proteus-factory.ts` | Semantic tokens、字体、shadows、keyframes、animations。 |
| `proteus_factory_effects.css` | `src/styles/proteus-factory.css` | Component classes、grid、clipped panels、状态模式、motion/accessibility fallback。 |

不应把 Tailwind CLI、Node runtime 或该配置直接塞进当前 `hermes-runtime`。当 Web frontend 技术决策正式获批后，再以独立前端构建链安装 Tailwind，并在 server-rendered skeleton 的视觉验收通过后逐步替换静态 CSS。

## 2. Visual System: Controlled Energy, Not Cyberpunk Noise

Factory Home 是 **Production Creation + Production Portfolio**，不是对话机器人、游戏 HUD 或通用监控大屏。JARVIS 贡献中心化意图、克制层次、精密文字和“命令已被接收”的方向感；TRON 贡献深黑青 canvas、切角面板、稀疏 cyan focus trace 和路径型连线。两者都必须被 Mission Control 纪律约束：数据可追溯、告警可行动、文本优先、状态冗余、无虚构遥测。

| 应保留的语言 | 对应 Tailwind 实现 | 必须避免 |
| --- | --- | --- |
| 深层空间感而非纯黑空洞 | `bg-factory-canvas-950` + `factory-radial` + 低透明 grid。 | CRT 曲面、连续 noise、强闪烁。 |
| 精密指挥区 | `factory-command-deck`、`font-display`、`tracking-command`。 | “Ask anything” chat shell。 |
| 结构化能量边界 | `clip-factory`、`shadow-cyan-trace`、一次性 `animate-trace-once`。 | 全屏 neon、无限 halo/rotate。 |
| 事实优先的状态 | `data-state` + `factory-status` + 文本/图标/pattern。 | 单靠颜色或无依据百分比。 |
| 稳定的系统活性 | Snapshot freshness、cursor、as-of text 的 telemetry 样式。 | CPU/RAM/network 假图表、AI thinking loop。 |

## 3. Theme Token System

### 3.1 Color Families

主题配置定义两个层次。`factory.*` 用于可控的基础 surface/ink/line 关系，`state.*` 仅用于由 authority projection 提供的语义状态。组件不得直接散落 hex 值；业务状态不得消费视觉名称例如 `cyan` 来表达运行。

| Token family | Role | Typical utilities |
| --- | --- | --- |
| `factory.canvas` | 最深背景、页面层次。 | `bg-factory-canvas-950` |
| `factory.surface` | 面板、raised layer、输入背景。 | `bg-factory-surface-raised` |
| `factory.line` | 分区、切角、focus outline。 | `border-factory-line`, `border-factory-line-bright` |
| `factory.ink` | 正文、辅助文本、telemetry。 | `text-factory-ink-100`, `text-factory-ink-400` |
| `factory.cyan` | 主 CTA、focus、真实 LIVE connection。 | `text-factory-cyan-300`, `shadow-cyan-focus` |
| `factory.violet` | Draft/Planning。 | `text-state-planning` |
| `factory.amber` | Waiting/uncertain/approval attention。 | `border-state-waiting` |
| `factory.red` | Rejected/failed，必须静态可读。 | `text-state-failed` |
| `factory.green` | 已验证/完成。 | `text-state-completed` |

### 3.2 State Semantics

`data-state` 来自被验证的 view model，示例值为 `running`、`planning`、`waiting`、`paused`、`recovering`、`completed`、`failed`、`stale`。CSS 只能根据属性选择视觉 treatment；**不能在浏览器内由按钮状态、百分比、网络猜测或 mock 数据推导该属性。**

| State | 文本 + 图标 | 颜色 | 非颜色模式 | 可用 action |
| --- | --- | --- | --- | --- |
| `running` | `● RUNNING` | cyan | 实线左 rail | `OPEN PRODUCTION` |
| `planning` | `◇ PLANNING` | violet | 虚线 left rail | `CONTINUE PLANNING` |
| `waiting` | `⚠ WAITING FOR HUMAN` | amber | hatch/notch | `REVIEW GATE` |
| `paused` | `⏸ PAUSED` | muted ink | pause tab | `REVIEW RESUME` |
| `recovering` | `↻ RECOVERING` | cyan light | double trace | `OPEN PRODUCTION` |
| `completed` | `✓ COMPLETED` | green | terminal cap | `OPEN DELIVERY` |
| `failed` | `✕ FAILED` | red | static double rail | `INSPECT RECOVERY` |
| `stale` | `◌ SNAPSHOT STALE` | ink | neutral hatch | `REFRESH SNAPSHOT` |

### 3.3 Typography, Shape, Density

`font-display` is only for headings, compact actions and page labels. `font-mono` is reserved for as-of time, cursor, source IDs, counters and uppercase labels; it must never render long user Idea, Gate reason or Proposal body. `font-sans` remains default reading typography. Panels use `borderRadius.factory: 0` and `clip-factory` for the 12px tactical corner, preserving a normal rectangle fallback where `clip-path` is unavailable.

## 4. Layout Recipes

Use CSS Grid for information hierarchy, not decorations. At wide viewports the Home has left signal rail, central command deck, right attention rail, then a bounded Portfolio deck and provenance rail. At smaller breakpoints the Hero is first, followed by Attention, Active Production, Outcomes and Factory Status.

```tsx
<main className="factory-shell">
  <div className="relative z-content mx-auto max-w-[1440px] px-4 py-5 sm:px-6 lg:px-8">
    <FactoryHeader />

    <section className="grid gap-4 xl:grid-cols-12">
      <aside className="hidden xl:col-span-2 xl:block"><FactorySignalRail /></aside>

      <section className="xl:col-span-7">
        <IdeaCommandDeck data-state="valid" />
      </section>

      <aside className="xl:col-span-3"><ActionRequired /></aside>
    </section>

    <section className="mt-5"><ProductionPortfolio /></section>
    <FactoryProvenanceRail />
  </div>
</main>
```

| Width | Recommended grid | Required visual behavior |
| --- | --- | --- |
| `≥1280px` | 12 columns: 2 / 7 / 3. | Intent deck dominant; Portfolio 3 cards if source returns up to 3. |
| `1024–1279px` | 12 columns: 8 / 4; signal rail becomes horizontal. | Gate attention stays adjacent to command deck. |
| `768–1023px` | 8 columns; Hero full width. | Portfolio becomes 2 column only if card width remains readable. |
| `<768px` | Single column. | No horizontal scroll, no hover-only action, no halo that clips input. |

## 5. Core Component Recipes

### 5.1 Factory Shell and Header

```tsx
<div className="factory-shell">
  <header className="relative z-content flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-factory-line py-3">
    <a className="font-display text-sm font-bold tracking-[0.14em] text-factory-ink-100" href="/home">
      PROTEUS <span className="text-factory-cyan-300">//</span> FACTORY
    </a>
    <nav className="flex items-center gap-4 text-sm text-factory-ink-400" aria-label="Factory navigation">...</nav>
    <span className="factory-connection-pill" data-connection="stale">◌ SNAPSHOT STALE</span>
  </header>
</div>
```

The connection pill must be bound to the read model’s freshness field and show `LIVE`, `STALE`, `REHYDRATING` or `DEGRADED` in text. Do not use a pulsing dot to create apparent activity.

### 5.2 Idea Command Deck

```tsx
<section className="factory-command-deck" data-state="valid" aria-labelledby="idea-title">
  <span className="factory-intent-halo" aria-hidden="true" />
  <p className="factory-telemetry">NEW PRODUCTION // INPUT 01</p>
  <h1 id="idea-title" className="mt-3 max-w-3xl font-display text-4xl font-semibold tracking-display text-factory-ink-100 sm:text-5xl">
    What do you want to build?
  </h1>
  <p className="mt-4 max-w-2xl text-base leading-7 text-factory-ink-300">
    Describe the software outcome. Proteus will produce a reviewable plan before production exists.
  </p>
  <label className="mt-8 block text-sm font-semibold text-factory-ink-200" htmlFor="idea">Software outcome</label>
  <textarea id="idea" className="factory-input mt-2" placeholder="Describe the result you want to produce…" />
  <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
    <span className="factory-telemetry text-state-planning">◇ DRAFT NOT YET SUBMITTED</span>
    <button className="factory-button-primary" type="button">START PLANNING <span aria-hidden="true">→</span></button>
  </div>
</section>
```

Allowed `data-state` values are `empty`, `editing`, `valid`, `submitting`, `accepted`, `uncertain`, `rejected`. `submitting` activates only a bounded progress trace; it does not assert a command outcome. `accepted` copy must be **RECEIPT ACCEPTED — AWAITING AUTHORITY UPDATE**, not “Production Created.”

### 5.3 Production Card

```tsx
<article className="factory-production-card" data-state="waiting">
  <div className="flex items-start justify-between gap-3">
    <div>
      <p className="factory-telemetry">PROJECT P-0142 // SNAPSHOT FRESH</p>
      <h2 className="mt-2 font-display text-xl font-semibold text-factory-ink-100">DreamKnowledge</h2>
    </div>
    <span className="factory-status" data-state="waiting" data-icon="⚠">WAITING FOR HUMAN</span>
  </div>
  <p className="mt-6 text-sm leading-6 text-factory-ink-300">Database migration approval required before the next verified action.</p>
  <footer className="mt-6 flex items-center justify-between gap-3 border-t border-factory-line pt-3">
    <span className="factory-telemetry">AS OF 14:02:18 UTC · GATES 1</span>
    <a className="factory-button-secondary" href="/gates/gate-123">REVIEW GATE →</a>
  </footer>
</article>
```

The source system must only render Worker/Verifier count, current summary or progress when each field is actually projection-backed. When not available, show `NOT AVAILABLE` rather than a placeholder metric.

### 5.4 Attention, Empty, Loading and Stale

```tsx
<section className="factory-attention-card" data-severity="critical" data-arrived="true">...</section>
<section className="factory-panel factory-snapshot-stale p-5">...</section>
<section className="factory-panel p-5"><div className="factory-skeleton h-4 w-28" /></section>
```

Skeletons preserve panel geometry but are not center spinners. A stale panel stops active glow and displays last safe `as_of`, reason and an explicit refresh action. Empty state keeps the Hero visually dominant; it must not imitate a runtime failure.

## 6. Effects Contract

The effects are deliberately finite and causal. Continuous or ambient loops are disallowed except the real `submitting` progress trace, whose lifecycle ends at a real receipt/timeout/abort boundary.

| Effect | Trigger | Class/keyframe | Duration | Reduced-motion behavior |
| --- | --- | --- | --- | --- |
| Focus trace | Composer focus. | `factory-panel--focus`, `trace-once`. | 160ms. | 2px static outline. |
| Intent halo | Focus, real submit, or accepted receipt. | `factory-intent-halo`, `connection-bloom`. | 140ms once. | Visible static line only. |
| Receipt signal | Receipt changes to accepted. | `receipt-signal`. | 190ms. | Copy changes only. |
| Snapshot skeleton | Specific read panel refreshes. | `factory-skeleton`, `snapshot-sweep`. | 210ms. | Opacity change only. |
| Gate insertion | New authoritative Gate projection arrives. | `gate-arrival`. | 180ms. | Direct card insertion. |
| Stale state | Stream gap/disconnect or stale snapshot. | `factory-snapshot-stale`, hatch. | 0–120ms. | Same hatch + text. |
| Command pending | Real semantic command is processing. | `progress-traverse`. | 900ms loop only while pending. | Static `SUBMITTING` label. |

The stylesheet includes both `prefers-reduced-motion: reduce` and `prefers-contrast: more`. It also provides `[data-transparency="reduced"]`, which can be a non-authority UI preference. Do not persist project/runtime state in the same preference store.

## 7. Accessibility, Performance and Fallback

All status presentation uses icon + label + text + non-color pattern. CTA hit targets are at least 44px (`min-h-11`). `:focus-visible` has a 2px cyan ring with canvas offset. Use `aria-live="polite"` only for actionable command/recovery/Gate changes; do not announce every event stream delta. The decorative grid is `pointer-events: none`, CSS-only, opacity-controlled and suppressed in high contrast/reduced transparency. No Canvas, WebGL, particle background, background video or audio is included.

`clip-path` is decorative. Browsers without support still show bordered rectangular panels. Avoid animation of `clip-path`, filter blur or layout-affecting properties. The provided keyframes animate only opacity, transform or shadow and remain under 220ms except the finite pending progress trace.

## 8. Adoption Checklist

| Step | Required evidence | Must not do |
| --- | --- | --- |
| 1. Approve frontend stack | Recorded decision to introduce Tailwind frontend. | Add Tailwind packages to current FastAPI runtime implicitly. |
| 2. Import tokens/effects | Visual review against Factory Home style guide. | Copy eDEX-UI code/assets/fonts/themes. |
| 3. Bind state attributes | View model lists `state`, `as_of`, `freshness`, source. | Infer state in CSS/client local storage. |
| 4. Integrate components | Keyboard, mobile, 200% zoom and high-contrast checks. | Rely on hover/glow/color alone. |
| 5. Wire semantic API later | Command receipt → snapshot reconciliation. | Display Project created on click/HTTP receipt only. |
| 6. Test visual discipline | Screenshot and DOM assertions for state redundancy. | Render fake telemetry/agent thinking visuals. |

## 9. Files in This Delivery

- `proteus_factory_tailwind_theme.ts` — Tailwind v3 token/animation configuration.
- `proteus_factory_effects.css` — `@layer` component classes, finite effects and accessibility fallbacks.
- `PROTEUS_FACTORY_HOME_TAILWIND_THEME_V1.md` — this specification and component recipes.

## References

[1]: [`PROTEUS_FACTORY_HOME_UI_STYLE_GUIDE_V1.md`](PROTEUS_FACTORY_HOME_UI_STYLE_GUIDE_V1.md)
[2]: [`PROTEUS_FACTORY_HOME_FRONTEND_ARCHITECTURE_V1.md`](PROTEUS_FACTORY_HOME_FRONTEND_ARCHITECTURE_V1.md)
[3]: [`factory_workspace_ui.py`](../hermes-runtime/src/hermes_runtime/application/factory_workspace_ui.py)
