# Proteus Factory Home Frontend Component Architecture & State Machine V1.0

**状态：** 实现前技术设计基线
**日期：** 2026-08-17
**范围：** Factory Home 的 Web 前端组件、状态机、数据流、事件同步、无障碍、测试和分阶段实现。
**非范围：** 本文不实现前端代码，不更改 P0–P5/P6 Runtime，不建立第二套执行系统，不定义 Live Production Workspace 的内部图形编辑功能。

> **核心约束：** Factory Home 是 Production Creation 与 Production Portfolio 的控制表面。它可创建 Draft、请求计划、查询投影、显示 Gate 和导航到 Live Production；它绝不直接写 Project/Task/Execution 权威状态，绝不把 command receipt 误呈现为 authority 已应用，也绝不在浏览器中承担 Scheduler/Worker/Plan Authority 的职责。**Factory Home must never become a second execution system.**

![Factory Home 前端状态机](assets/factory_home_state_machine.png)

## 1. Goals and Design Decisions

Factory Home 必须同时满足两种看似相反的任务：它要让首次用户可以用一句 Idea 低摩擦开始，又要让 Returning User 和 Operator 看清正在运行的 Production、告警、Gate、证据入口和系统新鲜度。因而页面采用“中央意图、外围遥测”的构型：中央 Command Deck 处理用户目的，两侧/下方的 read-only decks 处理真实的工厂态势。

当前仓库没有通用 Web 前端；P5 仅有 FastAPI 端点及最小 Human Gate HTML renderer。实现应新建独立、薄的前端层，但它必须使用同一个受控 Product API Contract 和 Project/Plan/Gate authority chain。框架选择尚未冻结；本文定义框架无关的边界，并给出以 React + TypeScript 为建议映射的模块和测试形态。若使用 Vue、Svelte 或 server-rendered islands，状态域、command 安全和 Snapshot/事件对账规则不得改变。[1] [2]

| 决定 | 结论 | 原因 |
| --- | --- | --- |
| 核心对象 | `Production` 是用户对象，`Project` 是后端权威聚合。 | 保持用户心智统一，不新建第二状态机。 |
| 首屏主任务 | 新建 Production Draft，而非 Chat History。 | Idea 进入 Understanding/Proposal/Plan，不立即执行。 |
| 数据形态 | Snapshot-first，event-enhanced。 | 事件丢失/乱序时仍能回到权威 read model。 |
| 写入形态 | 只用语义命令 + actor + reason + idempotency + expected version。 | 延续 P0–P5 authority model。 |
| UI 状态 | 前端 statechart 与 Project/Task 领域状态分离。 | 防止 UI 临时状态覆盖运行事实。 |
| 风险操作 | 先 intent preview，再 authority command/Gate。 | 防止 Command Bar 或卡片成为控制后门。 |

## 2. Proposed Frontend Topology

```text
Browser
  └── FactoryHomePage
        ├── Router and page state (URL)
        ├── FactoryHomeController
        │     ├── Snapshot query coordinator
        │     ├── Event bridge / reconciliation coordinator
        │     ├── Semantic command client
        │     └── Statechart interpreter
        ├── Presentation components
        │     ├── Command Deck / Idea Composer
        │     ├── Action Required Deck
        │     ├── Production Portfolio Deck
        │     ├── Factory Status Rail
        │     └── Accessibility announcer
        └── Browser-only preference and unsubmitted form state

HTTP / Event edge
  └── Product API Facade
        ├── Production Entry Draft & Plan commands
        ├── Project / Gate / Portfolio queries
        └── Event projection stream (when approved for P6/P7)

Authority side (never browser-owned)
  └── Entry/Plan Authority → Project Authority → Scheduler/Worker/Verifier
```

### 2.1 Recommended File Boundaries

The following file plan assumes React + TypeScript. These are target modules, not a request to create them in this task.

| Layer | Suggested modules | Responsibility | Forbidden dependency |
| --- | --- | --- | --- |
| Route shell | `routes/home.tsx`, `layout/AppShell.tsx` | URL parsing, page landmarks, feature flags. | Domain stores or direct database clients. |
| Controller | `features/factory-home/FactoryHomeController.tsx` | Joins queries, event bridge and statechart. | JSX-heavy visual layout or authority mutation logic. |
| Query adapter | `api/productionEntry.ts`, `api/portfolio.ts`, `api/gates.ts`, `api/factoryStatus.ts` | Typed HTTP calls, safe headers, response parsing. | Component state, optimistic lifecycle truth. |
| Event bridge | `events/portfolioBridge.ts` | Cursor handling, dedupe, cache patch, rehydrate. | Deciding final Project state. |
| Statechart | `state/factoryHomeMachine.ts`, `state/ideaComposerMachine.ts` | Local/transient UI states and guards. | Mirroring Scheduler/Task transition tables. |
| Domain mappers | `mappers/productionStatus.ts`, `mappers/gatePriority.ts` | Maps read models to display semantics. | Hard-coded color/JSX. |
| Components | `components/**` | Rendering, accessibility, user intents. | Raw `fetch`, direct global mutable store. |
| Tokens/styles | `styles/tokens.css`, `styles/factory-dark.css` | Design tokens and responsive layout primitives. | Production status business rules. |
| Tests | `tests/unit`, `tests/component`, `tests/contract`, `tests/e2e` | Validate each boundary. | Reliance on real production credentials. |

## 3. Component Architecture

### 3.1 Component Tree

```text
FactoryHomePage
├── AppShell
│   ├── SkipLinks
│   ├── GlobalNav
│   ├── ConnectionStatusRail
│   └── ScreenReaderAnnouncer
├── FactoryCommandDeck
│   ├── FactoryIdentityPanel
│   ├── IdeaComposer
│   │   ├── InputTelemetry
│   │   ├── ConstraintDrawer
│   │   ├── DraftResumeChip
│   │   └── StartPlanningButton
│   └── IdeaExamples (empty-state only)
├── ActionRequiredDeck
│   ├── GatePriorityCard × n
│   ├── FailureAttentionCard × n
│   └── ExpiringApprovalCard × n
├── ProductionTelemetryDeck
│   ├── ContinueProductionRail
│   │   └── ProductionSignalCard × n
│   ├── RecentOutcomesRail
│   │   └── OutcomeCard × n
│   └── PortfolioShortcut
├── FactoryStatusRail
│   ├── ControlPlanePulse
│   ├── WorkforceAvailability
│   └── EventFreshnessIndicator
└── HomeOverlays
    ├── VersionConflictDialog
    ├── ReconnectPanel
    └── NonBlockingToastStack
```

### 3.2 Component Contracts

| Component | Inputs | User intents emitted | Rendered facts | Must not do |
| --- | --- | --- | --- | --- |
| `FactoryHomePage` | Route params, authenticated actor. | Page open, filter change. | Page layout and landmarks. | Fetch each child independently or own authority state. |
| `FactoryHomeController` | Snapshot queries, stream status, statechart service. | Refresh, navigate, submit draft. | Loading/partial/degraded composition. | Call raw SQL/worker/scheduler. |
| `IdeaComposer` | Local draft text, validation, command phase. | Type, add constraint, submit, restore local text. | Unsubmitted input/field errors. | Display production as created before projection confirms it. |
| `StartPlanningButton` | `canSubmit`, command phase. | Submit intent. | Receipt pending/accepted label. | Trigger duplicate command or claim plan is running. |
| `ActionRequiredDeck` | Ordered gate/failure/expiry summaries. | Review gate, open production. | Gate count/risk/reason/time. | Approve/reject directly from a list card. |
| `ProductionSignalCard` | Portfolio projection item. | Open production, open overview. | State, phase, freshness, display progress. | Change Project state or fabricate progress. |
| `FactoryStatusRail` | Health/capacity/freshness read model. | Inspect details, refresh. | Actual Control Plane/Workforce/Event data. | Show generic fake CPU/network telemetry. |
| `ConnectionStatusRail` | Connection phase, `as_of`, cursor. | Refresh/reconnect. | Live/stale/rehydrating/degraded. | Suppress stale state to make UI look live. |
| `VersionConflictDialog` | Expected/current revision and safe diff summary. | Reload, reapply, cancel. | Command conflict explanation. | Auto-last-write-wins. |

### 3.3 Dependency Direction

Presentation components depend only on view models and intent callbacks. Controllers depend on typed query/event/command adapters. Query/event/command adapters depend on the Product API Contract. The only permitted direction is **UI → semantic API → authority → projection → UI**. No component may import implementation types from the Scheduler, Worker, Verifier or PostgreSQL adapter.

## 4. Client State Model

Factory Home uses several state domains rather than one global “production store.” This separation prevents browser-local interaction from masquerading as backend truth.

| Domain | Examples | Storage | Source of truth | Recovery rule |
| --- | --- | --- | --- | --- |
| URL state | filters, sort, selected deck, return target. | URL. | URL/router. | Back/forward stable. |
| Remote projection | productions, Gate summaries, factory health, drafts. | Query cache. | Server Snapshot. | Revalidate on focus/reconnect/cursor gap. |
| Event bridge | cursor, connection phase, dedupe keys. | Memory + safe cursor. | Event protocol plus Snapshot. | Gap → discard deltas → Snapshot fetch. |
| Form state | unsent idea, constraints drawer, validation. | Component memory; optional `sessionStorage`. | User input before submit. | Preserve only non-sensitive text. |
| Interaction state | bootstrapping, stale, submitting, conflict. | Statechart interpreter. | Browser transient state. | Never set Project lifecycle directly. |
| Preferences | density, reduced motion, rails collapse. | User profile/browser preference. | User preference. | Do not include business facts. |
| Command receipt | idempotency key, 202 receipt, rejection. | Memory/receipt lookup. | Semantic command response. | Reconcile through read model before success claim. |

### 4.1 Page Connection Statechart

The connection region is responsible for facts displayed on the page, not the Factory runtime.

| State | Meaning | Entry | Exit/transition | UI requirement |
| --- | --- | --- | --- | --- |
| `bootstrapping` | Initial parallel reads in progress. | Home route activation. | Snapshot success → `ready`; all fail → `degraded`; some succeed → `partial`. | Stable skeleton blocks; no zero-state flicker. |
| `ready` | Snapshot fresh and event cursor valid. | Full rehydrate success. | disconnect/TTL → `stale`; refresh/gap → `refreshing`. | Show `LIVE` or `SNAPSHOT CURRENT` with as-of. |
| `refreshing` | Existing data retained while revalidating. | User refresh/event gap/visibility return. | success → `ready`; failure → `partial`/`degraded`. | Nonblocking progress trace; do not blank cards. |
| `stale` | Stream unavailable, cursor gap or TTL expired. | Disconnect/gap. | refresh/reconnect → `refreshing`. | Persistent stale rail; disable high-impact commands. |
| `partial` | One or more decks available; another failed. | Partial query settlement. | successful retry → `ready`; all fail → `degraded`. | Each affected deck shows its own recoverable error. |
| `degraded` | Page cannot establish sufficient safe data. | Initial/all query failure. | retry → `refreshing`; partial response → `partial`. | Explain availability; preserve safe navigation where possible. |

### 4.2 Idea Composer Statechart

| State | Guard/entry | Allowed user actions | Exit | UI behavior |
| --- | --- | --- | --- | --- |
| `empty` | Text empty. | Type, resume draft. | Nonblank input → `editing`. | CTA disabled with explanatory hint. |
| `editing` | Trimmed text locally valid. | Edit, add constraint, clear, submit. | Validation failure → `invalid`; submit → `submitting`. | Cyan focus trace; no activity claim. |
| `invalid` | Empty/over-limit/invalid attachment. | Amend, clear. | Valid → `editing`. | Field error + accessible explanation. |
| `submitting` | Semantic command dispatched. | Cancel local UI only; no second submit. | 202 → `awaitingProjection`; 4xx/409 → `rejected`; timeout → `uncertain`. | Button displays `SUBMITTING`; keeps input visible. |
| `awaitingProjection` | Receipt accepted. | Wait, navigate away safely. | Draft revision seen → `redirecting`; timeout → `uncertain`. | Displays `RECEIPT ACCEPTED`; not “Production started.” |
| `redirecting` | Server projection confirms draft. | N/A. | Route transition complete. | Move to Understanding/Draft context. |
| `uncertain` | Network/response outcome unknown. | Lookup with same idempotency key, retry read. | Receipt/snapshot confirms → `awaitingProjection`; rejection → `rejected`. | Instructs user not to submit again. |
| `rejected` | API rejected/expected version conflict. | Amend, reload, retry, cancel. | valid submit → `submitting`. | Error code, safe reason, conflict resolution. |

### 4.3 State Transition Guards

| Event | Required guard | Permitted effect | Prohibited effect |
| --- | --- | --- | --- |
| `IDEA_SUBMITTED` | Text valid, not already submitting, actor allowed. | `POST /production-drafts` with idempotency. | Create Project/Task/Execution. |
| `RECEIPT_ACCEPTED` | Receipt correlates with current idempotency key. | Wait for projection. | Claim Understanding/Plan/Production exists. |
| `EVENT_CURSOR_GAP` | Cursor not monotonic or schema incompatible. | Mark stale, trigger full rehydrate. | Continue patching cache from unknown sequence. |
| `GATE_REVIEW_CLICKED` | Gate ID is in user-scoped projection. | Navigate to Gate detail. | Approve/resume directly. |
| `PRODUCTION_OPEN_CLICKED` | Production reference exists. | Navigate/load Snapshot. | Construct lifecycle state from card props. |
| `RESUME_INTENT` | Valid existing resume context. | Open controlled resume preview/detail. | Force Project from PAUSED to RUNNING. |

## 5. Snapshot, Event, and Command Flows

### 5.1 Snapshot-first Read Flow

At route activation, the Controller requests the minimum Home bundle in parallel: user-scoped Portfolio, attention/Gate summaries, factory status and resumable Drafts. Responses should contain a projection version/cursor, `as_of`, explicit freshness/availability fields and safe links/IDs. The Home renders after a quorum of useful facts; an unavailable status rail cannot hide an available Gate.

A future aggregate `GET /factory-home` read endpoint may reduce round trips, but it must be a read projection. It should not substitute for the existing Project/Gate source records, and it must expose per-deck freshness to preserve module-level error isolation.

### 5.2 Event Hydration

1. Establish the event stream only after the initial Snapshot has been stored.
2. Store the last accepted cursor per authenticated profile/session.
3. On each event, verify schema compatibility, actor scope, monotonic cursor and aggregate version before patching a corresponding query cache entry.
4. Dedupe by immutable event ID; do not dedupe only by timestamp.
5. On disconnect, cursor gap, sequence regression or unknown critical event: show `STALE`, stop applying deltas, fetch a fresh Snapshot, then resume from the new cursor.
6. Event text is notification/projection material. A terminal event does not alone let the UI claim `COMPLETED`; the refreshed Projection must assert verified delivery.

### 5.3 Semantic Command Flow

```text
User intent
  → local validation + statechart guard
  → command payload {actor, reason, idempotency_key, expected_version, content refs}
  → Product API semantic command
  → command receipt (accepted / rejected / unknown)
  → authority applies decision and emits event
  → Snapshot/projection confirms material state
  → UI updates final card/state
```

All retries use the same idempotency key until the command outcome is known. A `202` acknowledgement means the request has been accepted for authoritative processing; it does not mean a Production was created, a Gate applied or a Plan executed. Components must use separate copy: `RECEIPT ACCEPTED`, `AWAITING AUTHORITATIVE UPDATE`, and `APPLIED` only after projection confirmation.

## 6. API View Models and Contract Proposal

The frontend must consume stable view models rather than raw domain tables. Names below are proposed contracts; implementation must extend the existing Product API Facade, reject generic mutations and preserve safe response behavior.[1]

| View model | Required fields | Notes |
| --- | --- | --- |
| `FactoryHomeSnapshot` | `as_of`, `cursor`, `freshness`, `actor_scope`, `attention[]`, `continuations[]`, `outcomes[]`, `factory_status`, `drafts[]`. | Aggregate convenience read model; every nested item retains `source_version`. |
| `ProductionCardVM` | `production_id`, `project_id`, `display_name`, `display_state`, `phase`, `progress?`, `progress_basis`, `current_summary`, `owner`, `gate_count`, `last_updated`, `freshness`, `links`. | `progress` is optional and must state basis. |
| `GateCardVM` | `gate_id`, `production_ref`, `action_summary`, `risk`, `reason`, `evidence_count`, `expires_at?`, `status`, `review_link`. | No direct decision token/secret. |
| `FactoryStatusVM` | `control_plane`, `workforce`, `event_stream`, `as_of`, `degraded_reasons[]`. | Only actual reported metrics/capability. |
| `DraftCardVM` | `draft_id`, `idea_excerpt`, `entry_state`, `revision`, `updated_at`, `next_action`, `resume_link`. | Draft is not Production. |
| `CommandReceiptVM` | `command_id`, `idempotency_key`, `accepted_at`, `status_url?`, `rejection_code?`, `correlation_id`. | Receipt status explicitly distinct from projection state. |

## 7. Error, Offline, and Conflict Handling

| Condition | Detection | Required frontend behavior | Must not happen |
| --- | --- | --- | --- |
| Initial query failed | Query adapter rejection. | Module/whole-page degraded state, retry button, safe previous cache. | Empty state that implies user has no Productions. |
| Partial query failed | Settled request mixture. | Only the affected deck errors; remaining decks work. | Fail the full Home route. |
| Stream disconnect | WebSocket/SSE close or heartbeat timeout. | Stale rail, as-of, rehydrate retry. | Continue labeling data as live. |
| Cursor gap/unknown schema | Event validation. | Stop deltas, full Snapshot. | Guess state transition. |
| Duplicate submit | Button guard and idempotency. | Disable second dispatch/lookup receipt. | Create a second Draft. |
| Command timeout | No final receipt. | `uncertain`, same-key status lookup. | Recommend blind resubmission. |
| 409 version conflict | Command rejection. | Show current/expected version and reload/reapply path. | Silent overwrite. |
| Session expired | Auth adapter response. | Save unsent non-sensitive text locally, require sign in, revalidate. | Persist actor tokens/secrets in local storage. |
| Offline | Browser network signal plus request failure. | Preserve unsent text with explicit local-only marker; block send. | Pretend Draft is server saved. |

## 8. Accessibility and Interaction Requirements

Factory Home is a mission-control-like surface, but it must be usable without a mouse, animation or color perception. The route exposes landmarks for navigation, Command Deck, Action Required, Productions and status. The first skip link focuses the Idea input. Focus order follows visual decision priority, not DOM convenience. Every colored state has an icon, uppercase label, text explanation and programmatic accessible name.

`aria-live="polite"` announces only low-frequency, actionable changes: connection state, Gate count delta, Idea command receipt and command rejection. Individual stream events must not flood screen readers. The visual status rail is mirrored by text such as `Snapshot stale as of 14:02:18 UTC`. Focus outlines are at least 2px with visible offset; glow is an enhancement, not focus indication. `prefers-reduced-motion` removes pulses, scanning and animated counters. All main state copy supports localization without injecting format strings into telemetry labels.

## 9. Test Strategy

| Layer | Target | Representative tests |
| --- | --- | --- |
| Unit | Statecharts, validators, status mappers, cursor logic. | Invalid Idea cannot dispatch; timeout retains idempotency; stale blocks high-impact command; dedupe/gap behavior. |
| Contract | Typed API adapters. | Payload has actor/reason/key/version; payload rejects `project_state`/`task_state`/raw SQL/event fields; safe response parser. |
| Component | Deck behavior/accessibility. | Focus order, empty/loading/error/stale variants, status redundancy, gate card navigates only. |
| Integration | Controller + test server. | Initial parallel reads, partial failures, receipt then projection confirmation, 409 reload flow. |
| End-to-end | Realistic protected fixture. | First Idea → Draft route; browser reload → Home resume; gate review; disconnect → rehydrate; no duplicate Draft. |
| Visual regression | Token and layout contracts. | desktop/tablet/mobile, normal/high contrast/reduced motion, state cards. |

Tests must not directly seed an impossible UI state by bypassing command/authority semantics. Fixtures may use read-model builders for rendering but E2E should create state via official commands or controlled test fixtures that preserve the same invariants.

## 10. Implementation Slices

| Slice | Scope | Dependency | Completion signal |
| --- | --- | --- | --- |
| FH-0 | Token foundation, AppShell, no-data skeleton and route contract. | None; static fixtures only. | Accessible Home shell with visual states. |
| FH-1 | Snapshot query adapters, Portfolio/attention decks, status/freshness. | Read-model endpoints. | Home renders current real read projection, including partial/degraded states. |
| FH-2 | Idea Composer local state and Draft creation receipt flow. | `POST /production-drafts` semantic contract. | Single Idea produces one Draft receipt and navigates only after projection. |
| FH-3 | Draft resume/Understanding navigation, Welcome Back. | Draft read model. | Browser revisit restores server Draft/Production context. |
| FH-4 | Gate cards and existing Gate Detail integration. | Human Gate query/UI. | Review navigation works; no direct approval from Home cards. |
| FH-5 | Event bridge/SSE if approved by P6 route. | Cursor/event contract. | Disconnect, gap and rehydrate tested. |
| FH-6 | Responsive polish, visual regression, accessibility audit. | FH-0–5. | Desktop/tablet/mobile and reduced motion ready. |

## 11. Acceptance Criteria

| ID | Criterion |
| --- | --- |
| FH-AC-001 | Home opens into a stable skeleton then a Snapshot-backed state; it never flashes a false empty Portfolio. |
| FH-AC-002 | One valid Idea dispatch produces one idempotent Draft command and no Project/Task/Execution write. |
| FH-AC-003 | A `202` receipt is visually distinct from a Draft/Plan/Production authority update. |
| FH-AC-004 | Home supports fresh, refreshing, stale, partial and degraded read states with explicit copy. |
| FH-AC-005 | Stream cursor gap/unknown critical event forces Snapshot rehydration before any final state assertion. |
| FH-AC-006 | Production/Gate cards are projection renderers; they cannot mutate authority state. |
| FH-AC-007 | Gate cards provide evidence/risk/review navigation and do not bypass existing Gate decision flow. |
| FH-AC-008 | Every status has icon, label, text and accessible name; color is supplemental. |
| FH-AC-009 | Keyboard navigation reaches Idea input first and all visible actions in logical order. |
| FH-AC-010 | Reduced-motion and high-contrast variants preserve all command, attention and status information. |
| FH-AC-011 | On browser return, submitted Draft/Production context is loaded from server; only unsent non-sensitive text may recover locally. |
| FH-AC-012 | Frontend modules have no direct Scheduler/Worker/Verifier/Postgres imports or generic state-mutation API path. |

## References

[1]: [`docs/PROTEUS_PRODUCTION_ENTRY_UX_V1.md`](PROTEUS_PRODUCTION_ENTRY_UX_V1.md)
[2]: [`docs/PROTEUS_LIVE_PRODUCTION_UX_V1.md`](PROTEUS_LIVE_PRODUCTION_UX_V1.md)
[3]: [`docs/P6_MINIMUM_IMPLEMENTATION_ROADMAP.md`](P6_MINIMUM_IMPLEMENTATION_ROADMAP.md)
[4]: [eDEX-UI README](https://github.com/GitSquared/edex-ui)
[5]: [eDEX-UI default interface screenshot](https://raw.githubusercontent.com/GitSquared/edex-ui/master/media/screenshot_default.png)


## 12. DESIGN DELTA — Factory Home Frontend Implementation V1.0

**记录日期：** 2026-08-18
**变更性质：** 受控实现决策；不改变本文的 Authority、Snapshot-first、语义命令和 P6 compatibility 约束。

| 原始设计基线 | 已实现决定 | 原因与边界 |
| --- | --- | --- |
| 框架保持未冻结，React + TypeScript 仅为建议映射。 | 创建独立 `frontend/` React + TypeScript + Vite + Tailwind v3 项目。 | Recon 确认仓库不存在正式 Web frontend、Node manifest、SPA 或 Tailwind；用户已明确允许在此情况下创建独立 frontend。未把 Node/Tailwind 混入 `hermes-runtime`。 |
| 设计要求 Snapshot-first / event-enhanced Controller。 | 首个实现版本只提供 `authorityPendingAdapters` 与被隔离的 `developmentFixtureAdapters`；不建立 Event Bridge。 | 当前 Product API 没有 Draft、Portfolio、Gate list、Production snapshot 或 SSE contract。没有安全的真实 read layer 时，页面显示 `BACKEND AUTHORITY BRIDGE PENDING`，而非伪造 Snapshot。 |
| `FactoryHomeController` 将连接 query/stream/command adapters。 | 当前 `App.tsx` 使用 typed adapter interfaces 进行最小 resource composition。 | 这是 FH-0 frontend foundation；真实 query/event controller 将在后端 read contracts 建立后替换。组件没有 raw fetch、SQL、Scheduler/Worker/Verifier/P6 imports。 |
| Idea submit 在 `202` 后等待 Draft projection。 | 默认 build 中 `ProductionDraftApi.createDraft` 返回 `NOT_IMPLEMENTED`；development fixture 可导航到 demo Draft，但展示 persistent `DEVELOPMENT / DEMO` banner。 | 当前没有 `/production-drafts` authority。默认 production build 绝不会创建 Draft、Project、Task、Execution 或 claim `Production Created`。 |
| Factory Home cards 从 Project/Gate/Portfolio projection 获取事实。 | 默认 build 的 Portfolio/Gate/Production adapters 均为 explicit pending；fixture 卡片仅在 `VITE_PROTEUS_DEMO=true` 的开发服务器出现。 | 避免把 static/sample values 伪装为 P6/Project authority。真实 progress 显示为 `NOT AVAILABLE`，而非 `0%` 或编造值。 |
| Home 与 Live Production 通过受控 navigation 分工。 | 实现 `/home`、`/new`、`/drafts/:id`、`/productions`、`/productions/:id`、`/gates` 路由；Production overview 是 handoff shell。 | 不在 Home 重建 Workflow、Workers、Verification、Evidence、Recovery 或 Intervention。 |

### Delta Acceptance

1. `frontend/` 的默认路径由 Product API capability 缺口安全地阻断，并不模拟 authority success。
2. Development fixture 与 authority-pending adapters 是不同模块，fixture 只能在 `import.meta.env.DEV && VITE_PROTEUS_DEMO=true` 时被选择。
3. Theme 是有限/因果的 Tailwind effect layer，包含 reduced-motion/high-contrast fallback；没有无限 neon pulse、rotating HUD、particles、fake telemetry 或 fake progress。
4. P6 standalone autonomous trial 在前端隔离实现后重新执行并通过；没有 P6 代码、migration、trial harness、Scheduler、Worker、Verifier、Gate 或 Evidence diff。

**后端先决条件：** 真实 Factory Home 需要先实现 EntryDraft/revision authority、Portfolio/Gate/Production Snapshot projections、semantic command endpoints 和 Approval Bridge。前端不得以开发 fixture 替代这些条件。

## References (Implementation Delta)

[6]: [`frontend/README.md`](../frontend/README.md)
[7]: [`frontend/src/models.ts`](../frontend/src/models.ts)
[8]: [`frontend/src/api/adapters.ts`](../frontend/src/api/adapters.ts) and [`fixtureAdapters.ts`](../frontend/src/api/fixtureAdapters.ts)
[9]: [`docs/PROTEUS_FACTORY_HOME_IMPLEMENTATION_V1.md`](PROTEUS_FACTORY_HOME_IMPLEMENTATION_V1.md)
