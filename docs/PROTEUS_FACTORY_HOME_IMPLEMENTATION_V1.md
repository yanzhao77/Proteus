# Proteus Factory Home Implementation V1.0

**状态：** `PARTIAL — FRONTEND FOUNDATION COMPLETE, BACKEND AUTHORITY BRIDGE PENDING`
**实施日期：** 2026-08-18
**范围：** 独立 Factory Home 前端、JARVIS + TRON Tailwind 主题、显式 API adapter 边界、开发 fixture 隔离、页面路由、基础可访问性和自动化验证。
**非范围：** Entry Draft authority、Project/Task/Execution/Worker/Verifier/Scheduler 状态机、P6 Trial、schema/migration、Approval Bridge、真实 Portfolio/Gate/Snapshot/SSE API。

> **Authority Rule:** 浏览器中的 React state 只能表达输入、加载、错误、导航、收据等待和视觉偏好。任何 Production、Gate、Plan、Project、Task、Execution、Worker、Verification、Evidence 或 Delivery 事实必须来自 future authoritative Snapshot/Projection。当前后端缺少该契约时，默认 UI 以 `BACKEND AUTHORITY BRIDGE PENDING` 明示阻断，而不以 fixture 或按钮点击伪造事实。

## 1. Current Implementation Scope

Recon 确认当前仓库原先没有正式 Web frontend、`package.json`、Vite/Next/React/Vue 项目或 Tailwind 运行链；已有 `factory_workspace_ui.py` 是 FastAPI 的 server-rendered、明确 `DEMO / NON-AUTHORITATIVE` 骨架。Product API 目前提供 individual Project status、Human Gate detail/decision、decision explanation、reconcile finding 和 docker observation 等受控 route，但没有 Entry Draft、Portfolio、Gate inbox、Production snapshot、Factory Home aggregate read model 或 event stream contract。[1] [2]

因此本次实现选择在仓库根目录新建独立 `frontend/`，而不把 Node、React 或 Tailwind 嵌入 `hermes-runtime`。它是未来由 approved HTTP/Product API 接入的产品层；它没有数据库连接、Raw SQL、authority command handler、P6 runtime、Scheduler、Worker、Verifier 或 PostgreSQL imports。

| Area | Delivered | Explicitly not claimed |
| --- | --- | --- |
| Factory Home | `/home` Command Deck、Action Required、Portfolio、provenance rail、pending/fixture states。 | 当前真实 Project/Gate/Portfolio projection。 |
| Production Entry | `/new`、`/drafts/:id` 和 Idea → Understanding → Proposal → Master Plan → Approval Bridge 信息流。 | 默认 build 的 server Draft 创建、恢复、Understanding execution 或 Master Plan authority。 |
| Portfolio | `/productions`、state-safe `ProductionCard`、`NOT AVAILABLE` progress behavior。 | 实时进度、Worker count、task count、虚构 completion percentage。 |
| Live Production handoff | `/productions/:id` source-aware overview shell。 | Workflow graph、nodes、workers、verification、evidence、intervention、recovery UI。 |
| Gate | `/gates` Action Required view 和 Review navigation-only affordance。 | 直接 approve/reject/resume 或浏览器 DB mutation。 |
| Styling | Tailwind theme、effects、reduced motion、high contrast、state redundancy。 | 游戏 HUD、fake telemetry、infinite neon loop、particles。 |

## 2. Frontend Architecture

```text
frontend/ (independent React + TypeScript + Vite + Tailwind v3)
  ├── src/App.tsx                    Route shell + presentation composition
  ├── src/models.ts                  View models + typed semantic adapter interfaces
  ├── src/api/adapters.ts            Default authority-pending adapter implementations
  ├── src/api/fixtureAdapters.ts     Development-only, visibly labelled fixture adapter
  ├── src/api/index.ts               Safe adapter selection switch
  ├── src/styles/index.css           JARVIS + TRON tokens/effect components/fallbacks
  ├── src/test/**                    Test setup and authority-safety coverage
  ├── tailwind.config.ts             Theme tokens, finite keyframes and state colors
  └── README.md                      Local run and adapter hand-off guide
```

The dependency direction is **page/component → typed adapter → future Product API → existing authority → source-derived projection → page/component**. This implementation deliberately stops at the typed adapter boundary. `App.tsx` does not call `fetch` and cannot import or mutate Python authority modules.

## 3. Routes and Product Boundaries

| Route | Implemented presentation | Current adapter behavior | Boundary |
| --- | --- | --- | --- |
| `/home` | Hero/Idea Command Deck, Action Required, Continue Production, provenance. | Default: safe pending panels; DEV fixture: clearly labelled demo cards. | Does not create a Production. |
| `/new` | Focused Production Entry deck. | Same `ProductionDraftApi` contract. | `START PLANNING` never means Start Production. |
| `/drafts/:id` | Draft lifecycle information and future approval bridge sequence. | Default: pending; DEV fixture: demo Draft only. | Does not approve or materialize Project. |
| `/productions` | Portfolio states and filters-ready card layout. | Default: pending; DEV fixture: sample read models. | Does not invent a snapshot. |
| `/productions/:id` | Live Production handoff shell. | Default: pending; DEV fixture: labelled overview. | Does not rebuild Live Workspace. |
| `/gates` | Action Required/Gate inbox shell. | Default: pending; DEV fixture: sample gate. | Does not submit a gate decision. |

## 4. Components and View Models

The current source intentionally keeps components compact in `App.tsx` while contracts are in `models.ts`. Once real APIs exist, these primitives can be extracted into feature modules without changing the authority boundary.

| Component | Required view-model facts | Permitted interaction | Forbidden behavior |
| --- | --- | --- | --- |
| `IdeaDeck` | Local text, adapter result phase. | Submit intent through `ProductionDraftApi`. | Claim Draft/Production exists before a data projection. |
| `ProductionCard` | ID, state, phase, summary, freshness, action route. | Navigate to details/Gate. | Pause, resume, stop, mutate Project or fabricate progress. |
| `GateCard` | production ref, risk, reason, evidence count, freshness. | Navigate to review. | Approve/reject directly from Home. |
| `ViewNotice` | Explicit pending/error source. | Explain current gap. | Render false empty state as an authority result. |
| `Header` | adapter mode / connection label. | Navigate. | Create continuous fake liveness indicator. |

`ProductionCardViewModel.progress` is nullable. When it is `null`, the UI renders `PROGRESS NOT AVAILABLE`; it never replaces missing data with `0%`. Every state card includes a glyph, uppercase text label and a non-color rail/pattern through `data-state`.

## 5. API Adapter Contract

Four interfaces exist in `src/models.ts`: `ProductionDraftApi`, `ProductionPortfolioApi`, `GateApi` and `ProductionApi`. Mutating signatures include `actor`, `reason`, `idempotencyKey` and `expectedVersion`, exactly so a future semantic API can enforce attribution, rationale, idempotency and optimistic concurrency.

The default `authorityPendingAdapters()` returns only `{ kind: 'not_implemented', message }`. It makes no fake HTTP request, no raw mutation and no assumption that the P6 Trial Driver is a Product API. The only fixture mode requires both Vite development mode and `VITE_PROTEUS_DEMO=true`; it renders a persistent `DEVELOPMENT / DEMO` banner and all fixture mutations return `NOT_IMPLEMENTED`. A production build cannot select the fixture adapter.

## 6. Tailwind Theme and Effects

`tailwind.config.ts` and `src/styles/index.css` implement the existing Factory Home theme pack. They include `factory.canvas`, `factory.surface`, `factory.line`, `factory.ink`, cyan/violet/amber/red/green token families, `font-display`/`font-sans`/`font-mono`, `clip-factory`, component recipes and state treatments.

| Effect | Contract | Accessibility fallback |
| --- | --- | --- |
| Focus trace | Composer focus, 160ms once. | Static 2px focus ring. |
| Intent halo | Focus/real command phase, finite 140ms bloom. | Static line. |
| Command pending | Only an actual current command phase, bounded to pending lifecycle. | Static submitting label. |
| Snapshot skeleton | Specific deck refresh, 210ms sweep. | Static placeholder geometry. |
| Gate arrival | Projected Gate insertion, 180ms. | Direct card insertion. |
| Stale hatch | Snapshot freshness says stale. | Same text/pattern without motion. |

`prefers-reduced-motion: reduce`, `prefers-contrast: more`, `data-transparency="reduced"`, 44px minimum CTA (`min-h-11`) and `:focus-visible` 2px focus ring are implemented. There is no `animate-pulse`, rotating HUD, particle layer, fake CPU/RAM/network graph or fake agent thinking loop.

## 7. Mock / Development Boundary

| Mode | Selection | Visual disclosure | Reads | Mutations |
| --- | --- | --- | --- | --- |
| Authority pending (default build) | Always, unless explicit local dev fixture condition holds. | `BACKEND AUTHORITY BRIDGE PENDING`. | `NOT_IMPLEMENTED`. | `NOT_IMPLEMENTED`. |
| Development fixture | `import.meta.env.DEV && VITE_PROTEUS_DEMO=true`. | Persistent `DEVELOPMENT / DEMO` banner and `DEVELOPMENT FIXTURE` provenance. | Local sample view models. | Always `NOT_IMPLEMENTED`. |
| Future production adapter | Only after Product API contract is implemented and reviewed. | Actual source/freshness/as-of fact. | Source-derived Snapshot/Projection. | Semantic command + receipt + projection reconciliation. |

Fixture cards are deliberately not a “demo production system”: no fixture action creates a Project, Task, ExecutionRequest, Worker, Gate state transition or Evidence record.

## 8. Tests and Verification

| Command | Result | Coverage |
| --- | --- | --- |
| `cd frontend && pnpm test` | **PASS — 29 tests across 4 files.** | Pending/loading/error/stale render contracts, route set, state redundancy, Draft fixture restore, Gate fixture disclosure, adapter mutation refusal, 44px CTA, reduced motion/high contrast, no fake progress/telemetry and no direct authority UI path. |
| `cd frontend && pnpm build` | **PASS.** | TypeScript compilation and Vite production asset build. |
| `cd frontend && pnpm lint` | **PASS — 0 warnings, 0 errors.** | Static source checks. |
| P6 standalone acceptance | **PASS — 1 test, 151.423 s.** | Real PostgreSQL-backed P6 autonomous production acceptance after the frontend implementation. |
| Protected-path diff inspection | **PASS.** | No frontend task diff in migrations, P6 trial, P6 acceptance test, P6 report or P6 evidence. |

No screenshot/browser test harness existed in the repository. Visual QA was therefore limited to responsive Tailwind layout construction and automated source contracts, not a claim of live browser screenshot approval. Desktop 12-column (`2 / 7 / 3`), tablet collapse and mobile single-column behavior are implemented in the layout classes; browser visual approval remains an FH-6 follow-up once a browser E2E harness is chosen.

## 9. Known Backend Gaps

1. No `EntryDraft`/revision authority and no `POST /production-drafts` semantic command.
2. No Entry Understanding, Clarification, Assumption, Proposal or Master Plan read/command API.
3. No explicit `ApproveEntryPlan` command nor approved bridge that invokes existing Project/graph/verification authority.
4. No user-scoped Portfolio projection, Gate inbox projection, Production snapshot or Factory Home aggregate snapshot.
5. No authenticated frontend identity/capability token integration.
6. No approved snapshot/event cursor/SSE contract, so no safe connection status beyond explicit pending/fixture status.
7. Current FastAPI Product API default uses an empty read model and rejecting command gateway; it cannot serve Factory Home product facts without future composition wiring.

## 10. Next Phase

The safest next implementation is **FH-1: Read Model Adapter**, before any Entry mutation. Define source-derived, scoped Portfolio/Gate/Production Snapshot contracts and their per-deck `as_of`, freshness, source and version fields; then replace only the default pending read adapter. After read contracts are verified, implement **E1 EntryDraft Core** and then **FH-2 Draft receipt → projection reconciliation**. The Approval Bridge must remain last and must reuse existing Project/Task graph/Verification authority rather than front-end-created lifecycle state.

## 11. Run Instructions

```bash
cd frontend
pnpm install
pnpm dev

# Optional local development presentation fixture; never a production mode
VITE_PROTEUS_DEMO=true pnpm dev

pnpm test
pnpm build
pnpm lint
```

## 12. References

[1]: [`docs/ENTRY_RECON.md`](ENTRY_RECON.md)
[2]: [`docs/PROTEUS_FACTORY_HOME_FRONTEND_ARCHITECTURE_V1.md`](PROTEUS_FACTORY_HOME_FRONTEND_ARCHITECTURE_V1.md)
[3]: [`docs/PROTEUS_FACTORY_HOME_TAILWIND_THEME_V1.md`](PROTEUS_FACTORY_HOME_TAILWIND_THEME_V1.md)
[4]: [`docs/P6_REPORT.md`](P6_REPORT.md)
[5]: [`frontend/README.md`](../frontend/README.md)


---

# FH-1 Implementation Delta — Factory Home Read Model Adapter

**状态：** `PARTIAL — GET-ONLY CONTRACT AND FRONTEND ADAPTER COMPLETE; VERIFIED BROWSER ACTOR SCOPE BLOCKED`
**实施日期：** 2026-08-18

## A. Implemented Read Endpoints

| API | Authority source | Scope | Freshness / as_of | Status |
| --- | --- | --- | --- | --- |
| `GET /factory-home` | Scoped `projects` plus requested `human_gate_requests` records. | `ActorProjectScope` resolver supplied by deployment composition. | Per-record source fields exist; aggregate `cursor` remains `null`, aggregate freshness is `NOT_AVAILABLE`. | Implemented contract. |
| `GET /factory-home/productions` | `projects` and scoped count of `human_gate_requests.request_state = REQUESTED`. | Same actor-scoped Project ID set. | `projects.updated_at`, `projects.version`, source `projects`; business freshness remains `NOT_AVAILABLE` because no freshness authority exists. | Implemented contract. |
| `GET /factory-home/productions/{id}` | Scoped Project card lookup. | Refuses IDs outside resolved scope. | Source-derived card fields only. | Implemented contract. |
| `GET /factory-home/gates` | Requested `human_gate_requests` joined to scoped `projects`. | Same actor-scoped Project ID set. | `human_gate_requests.updated_at`, `human_gate_requests.version`, source `human_gate_requests`; freshness remains `NOT_AVAILABLE`. | Implemented contract. |
| `GET /factory-home/drafts` | No EntryDraft authority or schema exists. | N/A. | N/A. | Explicit `NOT_IMPLEMENTED`. |
| `GET /factory-home/status` | No supported Factory metric projection exists. | N/A. | N/A. | Explicit `NOT_AVAILABLE`; no fake CPU/RAM/network/workforce/queue data. |

All routes use the existing `ProductApiFacade` and FastAPI `_dispatch` path. They are GET-only, run the existing safe-response filter, do not issue commands, and do not call Scheduler, Worker, Verifier, P6 Trial Driver or Project/Task/Execution/Gate authority mutation paths.

## B. Projection Data Availability

| Field | FH-1 value | Rationale |
| --- | --- | --- |
| Project / Production ID, title, display state, phase, version, timestamp | Source-derived from `projects`. | Existing authority facts. |
| Gate ID, action scope, reason, expiry, request state, version, timestamp | Source-derived from `human_gate_requests`. | Existing authority facts. |
| `progress` / `progress_basis` | `null` / `NOT_AVAILABLE`. | No approved progress authority exists; no calculation is introduced. |
| `worker_count`, `task_count`, `completion_percentage` | Omitted. | No source-backed aggregate authority. |
| `current_summary`, `owner`, `plan_revision` | `null`. | No safe authority source is available. |
| Gate `risk`, `evidence_count` | `null`. | Existing records do not provide a safe current Product projection for these fields. |
| `cursor` | `null`. | FH-1 does not implement event/SSE bridge. |
| Factory metrics | `NOT_AVAILABLE`. | No metric read model exists. |
| Drafts | `NOT_IMPLEMENTED`. | EntryDraft authority is intentionally deferred. |

## C. Actor Scope and Bootstrap Safety

The new PostgreSQL projection requires `ActorProjectScope.project_ids_for(actor_scope)` to return an authenticated, authorized Project ID set. When a deployment has no verified identity-to-scope adapter, `DenyAllActorProjectScope` / `UnavailableFactoryHomeReadModel` returns `NOT_AVAILABLE` with no cards or Gate records. It never enumerates global projects, accepts a browser-provided actor as proof of authorization, or returns an empty Portfolio as if it were a factual result.

The current FastAPI actor headers are propagated to the Product API but are not themselves verified browser authentication. This is the FH-1 deployment blocker: a real identity adapter must be composed before real browser users can receive the source-derived Portfolio/Gate projections. The contract and endpoints are ready for that composition; production bootstrap remains fail-closed.

## D. Frontend Adapter Delta

The default production frontend adapter is now `productApiAdapters`, which consumes only `GET /factory-home/**` JSON envelopes through typed API adapter classes. `App.tsx` contains no direct `fetch`; fetch and source mapping live in `src/api/productApiAdapters.ts`. The fixture selection is unchanged and still requires both development mode and `VITE_PROTEUS_DEMO=true`; it cannot be selected by a production build.

Portfolio and Gate decks now fail independently. A real empty response renders `EMPTY PORTFOLIO` or `NO ACTIONS REQUIRING YOU`; a backend unavailable response renders a module-specific unavailable notice; an HTTP/network failure renders a module-specific load-failed notice. `progress: null` remains `PROGRESS NOT AVAILABLE`, and source/freshness facts are never inferred by React time arithmetic.

## E. FH-1 Tests and Verification

| Command | Result | Notes |
| --- | --- | --- |
| `PYTHONPATH=src .venv/bin/python -m unittest tests.test_factory_home_read_model tests.test_fastapi_service_host tests.test_public_api_boundary tests.test_public_api_domain tests.test_factory_workspace_ui -v` | **PASS — 24 tests.** | Source-backed card/Gate mapping, nullable data, unauthorized scope, safe failure, GET-only Product API routes, existing API and UI regressions. |
| `cd frontend && pnpm test` | **PASS — 33 tests across 5 files.** | Product API parsing, unavailable scope, no FH-1 mutation, existing visual/authority contracts. |
| `cd frontend && pnpm build` | **PASS.** | TypeScript and production Vite build. |
| `cd frontend && pnpm lint` | **PASS — 0 warnings / 0 errors.** | Frontend static check. |
| P6 standalone acceptance after FH-1 | **BLOCKED by local test environment.** | The configured database port was unavailable; the available local Todo credential could connect but lacked `CREATE DATABASE`, which `test_p6_autonomous_trial` requires. No P6 file/test/runtime was modified. |

## F. Remaining Blockers and Next Phase

FH-1 must not move to Approval Bridge or Entry mutation. The immediate next phase is **FH-1.x Verified Identity Scope Composition**: introduce an approved authenticated identity adapter that can resolve user-scoped Project IDs without trusting browser headers, then wire `PostgresFactoryHomeReadModel` in bootstrap with that resolver and run the real PostgreSQL P6 acceptance in a database account allowed to create the isolated trial database. Only after that can the browser safely see real Portfolio/Gate data. EntryDraft authority, Draft mutation, Master Plan, Approval Bridge, SSE/Event Bridge and Live Production Workspace remain out of scope.


---

# FH-1.x Implementation Delta — Verified Identity Scope Composition

FH-1.x now reuses the existing OIDC `VerifiedIdentity` verifier for Factory Home only. A Factory Home request must carry a valid `Authorization: Bearer` token; the FastAPI layer verifies it before creating the Product API request. `X-Hermes-Actor-*` remains historical actor metadata for other paths and is never a Factory Home authorization source. A missing/invalid token fails closed; a browser header conflict with the verified OIDC subject is rejected.

The source-derived `PostgresCreatorActorProjectScope` uses only the existing initial `project_transition_records` requester fact to derive Project IDs for a verified subject. This is deliberately a creator/requester-only scope: no Project membership, owner, admin or collaborator model is invented. Unavailable verifier/configuration, invalid identity, actor mismatch, empty scope and storage failure remain unavailable rather than exposing global Projects or pretending the Portfolio is empty.

Production bootstrap composes the real Factory Home PostgreSQL read model only with explicit database plus OIDC issuer/audience/JWKS configuration. Otherwise it remains unavailable. The Frontend receives the same FH-1 GET-only contract and continues to own no identity, authorization or Project scope decision.

Verification after this delta: **35 backend focused tests PASS; 33 frontend tests PASS; frontend build PASS; frontend lint has 0 warnings / 0 errors; unchanged P6 standalone acceptance PASS (1 test, 101.035 s) using the documented isolated PostgreSQL endpoint.** Protected-path diff inspection found no modification to migrations, P6 Trial, P6 acceptance, P6 report or P6 evidence.

The remaining product decision is whether creator/requester-only visibility is sufficient. Do not introduce FH-2 mutation, EntryDraft, Approval Bridge or a general RBAC/membership system without an explicit authority design decision.


---

# E1 EntryDraft Core Implementation Delta

E1 replaces the former `NOT_IMPLEMENTED` Draft placeholder with a separate, authority-backed EntryDraft core. It introduces only creator-scoped Draft creation, list/detail reads, append-only revision, submit and archive lifecycle transitions; it does not create a Project, Production, Task, Execution, Worker, Scheduler, Verifier, Gate decision, Plan or Approval Bridge fact.

Draft HTTP routes are OIDC-gated and reuse the verified identity model established by FH-1.x. `EntryDraft` scope is independent from `PostgresCreatorActorProjectScope`: reads and mutations predicate on the Draft’s `creator_subject` rather than Project IDs. A mismatched actor header, unverified subject or foreign Draft ID has no authorizing effect; foreign Draft reads return safe `NOT_AVAILABLE` semantics.

The E1 migration uses isolated Draft tables for current state, immutable revisions, immutable transition records and persistent Draft idempotency receipts. Existing `command_receipts` remains Project-bound, so it is not misused for a pre-Project object. Identical command replay is persistent; changed payload under the same key conflicts; stale expected versions fail without overwrite.

The React frontend now has truthful `/new`, `/drafts` and `/drafts/:id` behavior through the existing `ProductionDraftApi` / `productApiAdapters` boundary. DEV fixtures cannot mutate Drafts and production does not select fixtures. The implementation has no direct React authority call, local Draft status or client-created factual Draft result.

Verification after E1: **6 E1 PostgreSQL authority/API tests PASS; 41 focused backend tests PASS; 33 frontend tests PASS; production build PASS; lint 0 warnings/errors; unchanged P6 standalone acceptance PASS in 90.677 s.** Protected-path diff and `git diff --check` are clean.
