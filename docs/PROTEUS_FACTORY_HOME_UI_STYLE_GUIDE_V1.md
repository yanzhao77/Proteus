# Proteus Factory Home UI Style Development Guide V1.0

**状态：** 可实施视觉与交互样式规格
**日期：** 2026-08-17
**适用范围：** Factory Home、Production Portfolio 卡片、Idea Composer、Attention/Gate 区、Factory Status Rail 和其共享组件。
**非范围：** 不复用 eDEX-UI 或影视资产；不定义通用品牌重塑；不替代 Live Production Workspace 的细节设计；不以视觉效果伪造运行事实。

> **视觉命题：** **JARVIS 的精密指挥感 + TRON 的结构化发光边界 + NASA Mission Control 的事实与告警纪律 + AI Agent Orchestrator 的实时编排可见性。** Factory Home 应让用户感到自己站在软件工厂的指挥台前，而不是置身于聊天窗口、游戏 HUD 或不可读的“黑客终端”。

## 1. Style Intent and Guardrails

Proteus 必须呈现为可信、克制、具有技术张力的生产控制界面。JARVIS 贡献中心化意图与精密层次；TRON 贡献深背景、切角边界和稀疏青蓝能量线；NASA Mission Control 贡献事实优先、告警层级、时间戳、来源与冗余编码；AI Agent Orchestrator 贡献 Production、Worker、Verifier、Gate、事件新鲜度之间的可扫描关系。eDEX-UI 提供的是信息分区和仪器面板感的参考，不是一个可以复制的设计资产包。[1]

| 必须实现 | 原因 | 明确禁止 |
| --- | --- | --- |
| 中央 Idea Command Deck 具有最大留白、最大对比和最低干扰。 | 新建 Production 是页面首要任务。 | 用密集遥测、假终端或全息球夺走输入焦点。 |
| Gate/Failure 等行动事项显著、可解释、有 Evidence/Review 路径。 | 人类控制必须真实可见。 | 只用红色脉冲或紧急感替代原因/动作。 |
| 生产卡片显示真实 phase/freshness/progress basis。 | Mission Control 纪律：可验证而非炫酷。 | 凭空 CPU/网络波形、Agent 思考动画、无依据百分比。 |
| 弱光、细线、切角、微型等宽遥测用于层级。 | 提供科幻仪器感。 | 强烈闪烁、彩虹霓虹、连续 glitch、CRT 曲率。 |
| 所有视觉状态可通过文本、图标、结构和 aria 识别。 | 无障碍与高可信度。 | 仅以颜色/光晕表达状态。 |

## 2. Visual Source Matrix

| 来源类型 | 转译为 Proteus 的组件语言 | 保持距离的元素 |
| --- | --- | --- |
| JARVIS 控制台 | `Intent Halo`、精密刻度、中央指挥区、卡片间的层级深度、自然语言意图与系统回执的连线。 | 电影界面、人物/声音人格化、旋转全息球和无数据装饰。 |
| TRON | 深蓝黑 canvas、cyan focus trace、切角轮廓、路径型连接光。 | 具体符号、电影视觉资产、满屏霓虹/高速闪烁。 |
| NASA Mission Control | alert queue、时间/来源、模块化 redundancy、低情绪的信息密度、稳定状态更新。 | 历史任务标记、机构 logo、虚假的 spacecraft telemetry。 |
| AI Agent Orchestrator | Running/Waiting/Paused cards、worker/verifier summary、Gate priority、event cursor、factory capability。 | Home 内的任意图编辑、未授权 control、无边界多 agent animation。 |
| eDEX-UI | 轨道分区、监控/主任务分离、等宽 auxiliary telemetry、主题化和触屏可用意识。 | 代码、主题、字体、图标、屏幕键盘、截图和 GPL 资产。 |

## 3. Canvas and Spatial System

### 3.1 Layout Blueprint

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ PROTEUS // FACTORY HOME       [PRODUCTIONS] [WORKFORCE] [ACTIVITY] LIVE  │
├───────────────┬─────────────────────────────────────┬───────────────────┤
│ FACTORY PULSE │  WHAT DO YOU WANT TO BUILD?          │ ACTION REQUIRED   │
│ Control Plane │  ┌─────────────────────────────────┐│ [GATE × 1]        │
│ Workforce     │  │ Describe the software outcome…  ││ database migration│
│ Event stream  │  └─────────────────────────────────┘│ REVIEW →          │
│ as-of / cursor│    [ START PLANNING → ]  [DRAFT]     │                   │
├───────────────┴─────────────────────────────────────┴───────────────────┤
│ ACTIVE PRODUCTIONS // ORCHESTRATION SIGNALS                             │
│ [● DreamKnowledge | IMPLEMENTING | Worker 02 | fresh] [⚠ Gate]          │
│ [⏸ NexaCache | PAUSED | resume review]                                  │
├─────────────────────────────────────────────────────────────────────────┤
│ SNAPSHOT 14:02:18 UTC  ·  CURSOR 00A8F  ·  BUILD P6  ·  ? SHORTCUTS      │
└─────────────────────────────────────────────────────────────────────────┘
```

The layout must read in order: **create → decide → continue → inspect**. The central column is a safe “intent quiet zone”; rails provide observability but cannot overwhelm the primary task. The active-production deck is more prominent than recent outcomes. The lower provenance strip is always visible on desktop but collapses to an accessible details element on mobile.

### 3.2 Responsive Rules

| Breakpoint | Layout | Mandatory behavior |
| --- | --- | --- |
| `≥ 1440px` | 12-column canvas: 2-column signal rail, 7-column command deck, 3-column attention rail. | `Intent Halo` visible but restrained; active cards in 3 columns. |
| `1024–1439px` | 12 columns: command deck 8, attention rail 4; signal rail becomes compact row. | Attention stays near top; active cards 2 columns. |
| `768–1023px` | 8 columns: command deck full width; attention then production; status as compact summary. | No horizontal scroll; cards 2 columns only if min width holds. |
| `<768px` | Single column: header → connection → command → attention → active → outcomes → factory status. | Hero input is first; rails are collapsible sections; no hover-only affordances. |

## 4. Design Tokens

### 4.1 Color Tokens

```text
Canvas:      --factory-canvas-950: #060A0D
Surface:     --factory-surface-900: #0A1216
Surface Up:  --factory-surface-850: #0E1A1F
Line:        --factory-line-700:    #23414A
Line Bright: --factory-line-500:    #3B6570
Ink High:    --factory-ink-100:     #E6F7F5
Ink Medium:  --factory-ink-300:     #A8C8C6
Ink Dim:     --factory-ink-500:     #6E9290
Cyan Active: --factory-cyan-500:    #45E5E1
Cyan Focus:  --factory-cyan-300:    #A6FFF9
Planning:    --factory-violet-500:  #A78BFA
Waiting:     --factory-amber-500:   #F6B958
Failed:      --factory-red-500:     #FF6B73
Verified:    --factory-green-500:   #70E0A0
```

The exact values must be validated against contrast requirements on actual surfaces. Tokens are semantic: components consume `--state-waiting`, not `#F6B958`. A high-contrast mode must increase text and line contrast without changing semantic mapping; reduced-transparency mode removes background grid/scanline layers.

### 4.2 Type, Density and Shape

| Token family | Specification | Usage |
| --- | --- | --- |
| Display | 28–40px, 600–700 weight, letter spacing `0.04em`. | Page labels and “WHAT DO YOU WANT TO BUILD?”. |
| Body | 15–17px, 400–500, line-height 1.45–1.6. | Idea input, Gate reason, explanatory copy. |
| Telemetry | 11–13px, mono stack, uppercase labels, tabular numbers. | `AS-OF`, cursor, Worker count, status strip. |
| Spacing | 4px base; 8/12/16/24/32/48 scale. | All layout and component spacing. |
| Panel shape | Zero rounded radius; 8px clipped corner only where decorative safe. | Decks and cards. |
| Border | 1px line token; 2px focus outline. | Panels, controls, focus. |
| Glow | `0 0 16px` maximum, low-alpha cyan/semantic color. | Focus and active connection only. |

Long user-generated content must never use monospace; the visual style must yield to readability. Telemetry numerals use tabular figures so timestamps and counts do not reflow.

## 5. Component Style Specifications

### 5.1 App Shell and Header

The header is a 56–64px technical rail, not a marketing nav. It contains `PROTEUS // FACTORY HOME`, primary navigation, a compact connection capsule and current as-of time. The active nav item uses cyan line + text, not a filled tab. Connection state shows `LIVE`, `STALE`, `REHYDRATING` or `DEGRADED`, always with icon and expanded accessible text.

### 5.2 Factory Command Deck

The Command Deck is the visual heart of the page. Above the textarea, show a small telemetry label: `NEW PRODUCTION // INPUT 01`. The input placeholder is “Describe the software outcome you want to create…”. The composer has a calm, large text field; its focus trace travels once around the clipped panel edge. The optional `Intent Halo` is a segmented, low-opacity orbital/linear ring outside the panel. It becomes visible only on focus, a submitted command receipt or analysis pending; it never continuously rotates.

| State | Surface treatment | Copy / control treatment |
| --- | --- | --- |
| Empty | Quiet surface, dim example chips. | CTA disabled with concise guidance. |
| Focused / editing | Cyan 1px focus trace and halo once. | Clear cursor, no typewriter animation. |
| Valid | Small `READY TO PLAN` telemetry marker. | CTA available. |
| Submitting | Input stays readable; top edge shows 1–2px linear progress trace. | CTA `SUBMITTING`; duplicate submit disabled. |
| Receipt accepted | Cyan trace moves to provenance strip once. | `RECEIPT ACCEPTED — AWAITING UPDATE`. |
| Uncertain | Amber hatch along top, no error glow. | `CHECKING RECEIPT; DO NOT RESUBMIT`. |
| Rejected | Red line + explicit text reason. | Focus returns to actionable field/reload choice. |

### 5.3 Attention Rail

The Attention Rail has NASA-like prioritization: Gate/Failure/Expired approvals are sorted by risk, time sensitivity and blocked-production impact. Each item includes a status glyph, uppercase state, action statement, reason excerpt, age/expiry, evidence count and one CTA (`REVIEW →`). The top card may use an amber/red left signal bar; it must never rely on flashing. More than three items collapse into a `VIEW ALL ACTIONS` row with count.

### 5.4 Production Signal Cards

Production cards communicate agent orchestration without impersonating a workflow editor. Each card contains: Production name; display state; current phase; actual current summary; Worker/Verifier summary if the projection provides it; `as_of`; Gate count; optional progress only with `progress_basis`; and Open action. The card has a thin semantic left rail, a clipped corner and a small origin stamp such as `PROJECT P-0142 // SNAPSHOT FRESH`.

| State | Glyph | Status label | Pattern | Action |
| --- | --- | --- | --- | --- |
| Running | `●` | `RUNNING` | solid cyan rail. | `OPEN PRODUCTION`. |
| Planning/Draft | `◇` | `PLANNING` / `DRAFT` | violet dashed rail. | `CONTINUE PLANNING`. |
| Waiting Human | `⚠` | `WAITING FOR HUMAN` | amber notch/hatch. | `REVIEW GATE`. |
| Paused | `⏸` | `PAUSED` | muted line with pause tabs. | `REVIEW RESUME`. |
| Completed | `✓` | `COMPLETED` | green terminal cap. | `OPEN DELIVERY`. |
| Failed | `✕` | `FAILED` | red double line, static. | `INSPECT RECOVERY`. |
| Stale | `◌` | `SNAPSHOT STALE` | neutral hatch overlay. | `REFRESH`. |

### 5.5 Factory Status Rail

This rail may evoke eDEX/Mission Control monitoring, but only with source-backed facts. It contains three compact modules: `CONTROL PLANE`, `WORKFORCE`, `EVENT STREAM`. Each module has availability, a short summary and `as_of`; it may use dot matrices, tick marks, simple scalar bars or cursor readouts. **It does not display fake CPU, RAM, or network telemetry** simply to look technical.

## 6. Motion, Sound and Feedback

Motion is causal. It may depict focus, a submitted request, a real reconnect, an authoritative card change or a Gate arriving. It must not depict vague “AI thinking.” Sound is outside P6 scope and disabled by default; any later sound cue must have a visual duplicate and an independent mute preference.

| Event | Motion | Duration | Reduced-motion fallback |
| --- | --- | --- | --- |
| Command Deck focus | One cyan edge trace + one halo illumination. | 140ms. | Instant focus outline. |
| Idea receipt | Directional trace toward provenance. | 180ms. | Button label change only. |
| Snapshot refresh | Skeleton sweep within affected deck. | 160–220ms. | Opacity change. |
| Connection live | Single connection capsule bloom. | 120ms. | Immediate `LIVE` label. |
| Connection stale | Glow stops; stale hatch fades in. | 120ms. | Immediate stale text. |
| Gate received | Attention card line expands once. | 160ms. | Immediate insert. |
| Projection status changed | Semantic rail cross-fade; no count-up. | 160–200ms. | Immediate updated label. |

No motion may exceed 240ms except a finite analysis/reconnect progress indicator with an actual lifecycle boundary. Avoid continuous loops, repeated blinking, parallax, random particle effects, CRT flicker or rendering-heavy canvas effects.

## 7. States: Loading, Empty, Error, Stale

| Condition | Required visual | Required content | Anti-pattern |
| --- | --- | --- | --- |
| First load | Stable panel-shaped skeleton, low opacity. | “Loading factory snapshot…” only when needed. | Spinner in the center of an otherwise empty page. |
| Empty Portfolio | Command Deck gets more vertical space; examples appear. | “No productions yet. Start with an outcome.” | Empty telemetry panels implying system fault. |
| No action required | Attention Rail becomes a calm `NO ACTIONS REQUIRING YOU` stamp. | Timestamp and brief explanation. | Hiding the rail and changing layout unpredictably. |
| Partial failure | Affected panel line turns neutral/amber, retains prior safe content. | Retry + error category. | Full-page hard error. |
| Degraded | Connection/status rail persists with explanation. | `FACTORY DATA PARTIALLY UNAVAILABLE` + as-of. | Continue showing `LIVE`. |
| Stale | Neutral hatch overlay and stopped active glow. | `SNAPSHOT STALE AS OF …` + refresh. | Dimming everything until unreadable. |
| Rejected command | Red rail and focused next action. | Safe error/reason/next action. | Generic “something went wrong.” |

## 8. Accessibility and Inclusion

The sci-fi identity is an enhancement layer over a fully usable command surface. Maintain WCAG AA contrast for body text and controls; test high contrast on all semantic states. Use icon + label + sentence for status. The main body font must be legible at 200% zoom; telemetry may scale without breaking panel edges. All interactions have keyboard equivalents and visible focus. Do not use images to convey state, do not hide key text inside glow, and do not rely on audio. Live regions announce only actionable mutations and must never announce every incoming event.

## 9. Performance Implementation Guidance

Decorative grid, scanning and glow must be CSS-only, composited and disabled in reduced transparency/reduced motion. Avoid canvas/WebGL/video backgrounds. Use CSS custom properties for tokens and construct clipped corners with pseudo-elements or a minimal vector mask; verify fallback rectangle remains acceptable. Component-level suspense/skeleton ensures a slow Factory Status rail does not stall Idea Composer. Virtualize long production lists outside Home; Home itself should show a bounded number of cards plus a Portfolio link.

## 10. Design QA Checklist

| Check | Pass condition |
| --- | --- |
| Intent hierarchy | At 1440px, the Idea Composer remains the first visual focal point within three seconds of viewing. |
| Fact discipline | Every metric/phase/progress shown has a source field or explicit `unknown`/`not estimated` state. |
| Actionability | Every Gate/Failure card states why it matters, what is needed, and where to review. |
| Status redundancy | Screenshot/DOM checks find icon, label, textual explanation and non-color pattern for each status. |
| Motion | Reduced-motion snapshot contains no loops/scanning/counting; normal mode contains only causal transitions. |
| Responsive behavior | 320px, 768px, 1024px and 1440px paths expose all primary actions without overlap or hover-only dependency. |
| Contrast | Normal/high-contrast panels meet approved contrast targets across cyan/amber/red/green/violet states. |
| IP/licensing | No eDEX-UI code, screenshot, icon, theme, font or copied asset is present. |

## References

[1]: [eDEX-UI repository and README](https://github.com/GitSquared/edex-ui)
[2]: [eDEX-UI default screenshot](https://raw.githubusercontent.com/GitSquared/edex-ui/master/media/screenshot_default.png)
[3]: [`docs/PROTEUS_PRODUCTION_ENTRY_UX_V1.md`](PROTEUS_PRODUCTION_ENTRY_UX_V1.md)
[4]: [`docs/PROTEUS_FACTORY_HOME_FRONTEND_ARCHITECTURE_V1.md`](PROTEUS_FACTORY_HOME_FRONTEND_ARCHITECTURE_V1.md)
