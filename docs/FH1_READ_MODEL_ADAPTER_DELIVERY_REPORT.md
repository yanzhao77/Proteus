# FH-1 Read Model Adapter Delivery Report

**状态：** `PARTIAL — READ-ONLY CONTRACT IMPLEMENTED; VERIFIED ACTOR-SCOPE COMPOSITION BLOCKED`
**日期：** 2026-08-18
**实施原则：** `UI → Product API → Authority → Projection → UI`；任何不存在的事实保持 `NOT_AVAILABLE`、`NOT_IMPLEMENTED`、`DEGRADED` 或 `null`，绝不由前端或示例数据补造。

## 1. Recon Findings

当前 Product API 已有 Project status、individual Human Gate、decision explanation、reconcile finding 与 Docker observation 的 allowlisted read route，但没有 Factory Home aggregate、Portfolio、Gate inbox、Production snapshot、Factory status、EntryDraft 或 event stream route。当前 FastAPI 的默认 `api_main.py` 使用 `EmptyReadModel`，且没有 verified browser identity-to-project-scope composition；`X-Hermes-Actor-*` 只会形成 Actor 值，不是认证证据。

现有 authority tables 的确提供了最小的 source-derived read facts：`projects` 中有 ID、title、state、version、timestamps；`human_gate_requests` 中有 Gate ID、Project ID、action scope、reason、expiry、request state、version、timestamps。没有 approved progress、worker/task count、completion percentage、Factory CPU/RAM/network/capacity/queue metrics、current summary、owner、plan revision 或 EntryDraft authority。

## 2. Implemented

| 文件 | 变更 |
| --- | --- |
| `hermes-runtime/src/hermes_runtime/application/factory_home_read_model.py` | 定义 `FactoryHomeReadModel`、`ActorProjectScope`、安全 unavailable 默认实现和模块可用性语义。 |
| `hermes-runtime/src/hermes_runtime/infrastructure/postgres_factory_home_read_model.py` | 新增 source-derived、GET-only PostgreSQL Project/Gate projection；默认 `DenyAllActorProjectScope` fail-closed。 |
| `hermes-runtime/src/hermes_runtime/application/product_api.py` | 仅扩展 allowlisted GET `/factory-home/**` 路由到现有 `ProductApiFacade`；无新 command path。 |
| `hermes-runtime/src/hermes_runtime/infrastructure/fastapi_app.py` | 仅注册六个 GET-only Factory Home transport route。 |
| `hermes-runtime/src/hermes_runtime/api_main.py` | 以 unavailable 或 deny-all scope 的 Factory Home read model 进行 bootstrap；不把未认证 header 当授权。 |
| `hermes-runtime/tests/test_factory_home_read_model.py` | 新增 7 项 backend read-model、scope、nullable 和 safe-failure 测试。 |
| `frontend/src/models.ts` | 扩展 typed read adapter contract 与 `product_api` mode。 |
| `frontend/src/api/productApiAdapters.ts` | 新增所有 Factory Home GET read 的唯一 HTTP/mapping 层；无 mutation。 |
| `frontend/src/api/index.ts` | production 默认选择 Product API read adapter；fixture 仍只能在显式 DEV 开关使用。 |
| `frontend/src/App.tsx` | Portfolio/Gate 独立 loading/empty/unavailable/error deck；没有 JSX mapping 或 authority fetch。 |
| `frontend/vite.config.ts` | 开发时 `/factory-home/**` proxy；不改变 Hermes Runtime。 |
| `frontend/src/api/productApiAdapters.test.ts` | 新增真实 GET adapter 解析、null progress、unavailable scope 与 mutation refusal 测试。 |
| `frontend/README.md` | 更新 FH-1 route、proxy、fixture 和 verified actor-scope 前提。 |
| `docs/PROTEUS_FACTORY_HOME_IMPLEMENTATION_V1.md` | 追加 FH-1 Implementation Delta。 |

## 3. Backend Read Models

| API | Source | Scope | Freshness | Status |
| --- | --- | --- | --- | --- |
| `GET /factory-home` | Scoped `projects` + `human_gate_requests` composition. | `ActorProjectScope` must resolve authorized Project IDs. | Per-record facts only; aggregate cursor `null`. | Contract implemented. |
| `GET /factory-home/productions` | `projects`; requested Gate count from `human_gate_requests`. | Same scoped IDs. | `updated_at` and `version` returned; business freshness `NOT_AVAILABLE`. | Contract implemented. |
| `GET /factory-home/productions/{id}` | Scoped Project projection. | Rejects IDs not in resolved scope. | Project `updated_at` and `version`. | Contract implemented. |
| `GET /factory-home/gates` | Requested `human_gate_requests` joined with scoped Project title. | Same scoped IDs. | Gate `updated_at` and `version`; business freshness `NOT_AVAILABLE`. | Contract implemented. |
| `GET /factory-home/drafts` | None. | N/A. | N/A. | `NOT_IMPLEMENTED`. |
| `GET /factory-home/status` | None. | N/A. | N/A. | `NOT_AVAILABLE`. |

The read model catches source failures as stable `DEGRADED` module states. It does not expose exception text, database details, raw SQL, scheduler/worker/verifier internals, tokens or secrets. `ProductApiFacade` continues to run its existing safe-response check.

## 4. Frontend Adapter

`ProductionPortfolioApi`, `GateApi` and `ProductionApi.getSnapshot` now have real typed GET implementations in `productApiAdapters`. The default production adapter uses those contracts. `ProductionDraftApi` remains explicit `NOT_IMPLEMENTED`; all Draft and Production semantic mutations return `NOT_IMPLEMENTED` and no POST/PATCH/PUT/DELETE transport exists in `frontend/src`.

The frontend differentiates `EMPTY`, `NOT_AVAILABLE`, `ERROR`, `DEGRADED` and missing field values. A true `CURRENT` empty Portfolio renders `EMPTY PORTFOLIO`; unavailable scope displays an unavailable deck rather than “No productions”; network/API failure displays a load-failed deck without blanking Gate attention; `progress: null` renders `PROGRESS NOT AVAILABLE`.

## 5. Authority Safety

The implementation added no migration, no schema change, no P6 Trial Driver change, no P6 acceptance test change, no Scheduler/Worker/Verifier modification, no Execution authority mutation and no Gate decision transition change. New `/factory-home/**` routes are all GET-only and only call the Product API façade and read-model protocols. The frontend imports neither Hermes Python runtime, PostgreSQL/ORM code, P6 trial code, Scheduler, Worker, Verifier nor raw authority classes.

The bootstrap scope is deliberately fail-closed. A deployment without a verified identity-to-Project resolver returns no Project/Gate records. It does not trust `X-Hermes-Actor-*`, hardcode an admin/user identity or enumerate global Projects. This blocks real browser Portfolio display until the identity composition layer is approved.

## 6. Data Availability

| Field | Availability | Actual source / reason |
| --- | --- | --- |
| Production ID/title/display state/phase | Available. | `projects`. |
| Production source version/as-of/last update | Available. | `projects.version` / `projects.updated_at`. |
| Requested Gate count | Available. | Count of scoped `human_gate_requests` in `REQUESTED`. |
| Gate ID/action/reason/expiry/status/version/as-of | Available. | `human_gate_requests`. |
| `progress` and `progress_basis` | `null` / `NOT_AVAILABLE`. | No authority-backed progress definition. |
| worker count/task count/completion percentage | Omitted. | No safe aggregate source. |
| current summary/owner/plan revision | `null`. | No approved Product projection source. |
| Gate risk/evidence count | `null`. | No safe current read projection source. |
| Factory control plane/workforce/event stream metrics | `NOT_AVAILABLE`. | No formal metric authority. |
| cursor / SSE data | `null` / absent. | FH-1 intentionally excludes Event Bridge. |
| Draft cards | `NOT_IMPLEMENTED`. | No EntryDraft authority. |

## 7. Tests

| Command | Result |
| --- | --- |
| Backend focused suite | **PASS — 24 tests.** Includes 7 new FH-1 read-model tests plus FastAPI/Product API/Factory Workspace regressions. |
| `cd frontend && pnpm test` | **PASS — 33 tests across 5 files.** |
| `cd frontend && pnpm build` | **PASS.** |
| `cd frontend && pnpm lint` | **PASS — 0 warnings / 0 errors.** |
| P6 standalone acceptance | **Not re-verified in this session due local database privilege/configuration blocker.** Initial configured port was unavailable; available Todo account lacked `CREATE DATABASE`, required by the isolated P6 test setup. |

## 8. Protected Path Inspection

Protected-path inspection reported no diff under `hermes-runtime/migrations`, `hermes-runtime/src/hermes_runtime/trial`, `hermes-runtime/tests/test_p6_autonomous_trial.py`, `docs/P6_REPORT.md` or `docs/evidence/p6`. The only existing runtime modifications are in Product API/FastAPI composition and the new read-model modules/tests named above. No P6 code or evidence was changed.

## 9. Documentation

The following documentation was updated or added:

| Document | Status |
| --- | --- |
| `docs/PROTEUS_FACTORY_HOME_IMPLEMENTATION_V1.md` | Updated with FH-1 Implementation Delta. |
| `frontend/README.md` | Updated with GET read route, proxy and identity scope guidance. |
| `docs/FH1_READ_MODEL_ADAPTER_DELIVERY_REPORT.md` | This delivery report. |

## 10. Remaining Blockers

1. There is no verified browser identity adapter that yields an authorized Project ID set; the current FastAPI Actor header is not sufficient authorization.
2. The default application server does not compose a real authenticated `ActorProjectScope`; it therefore fails closed.
3. No EntryDraft/understanding/proposal/plan/approval authority exists.
4. No official progress, worker/task, completion, Factory status, SSE/cursor or Live Production snapshot authority exists.
5. The current local P6 acceptance environment could not be provisioned because no available test DB account had the required create-database privilege. This is a test-environment blocker, not a source change.

## 11. Next Recommended Phase

Proceed with **FH-1.x Verified Identity Scope Composition**, not FH-2 and not Approval Bridge. The next change should supply an approved authenticated identity → actor scope → authorized Project ID resolver, wire it into `PostgresFactoryHomeReadModel`, and rerun the isolated P6 acceptance using a database account with `CREATE DATABASE`. Only once real browser actor scope is verified should the default Factory Home display current Portfolio/Gate projection data. Entry mutation, Approval Bridge, P6 runtime changes, SSE/Event Bridge and Live Production Workspace remain prohibited.


---

# FH-1.x Verified Identity Scope Composition

## 1. Recon Findings

仓库已经具备可复用的 OIDC verified identity 实现，而不是需要新建认证系统。`infrastructure/oidc.py` 的 `OidcTokenVerifier` 验证 JWT 签名、algorithm allowlist、`kid`/JWKS、issuer、audience、expiry、not-before 和 subject，并产生 `VerifiedIdentity`。`LocalIdentityAssertionProvider` 仅用于 Human Gate 的 deterministic local/test assertion，源码明确说明它不是 production IdP，因此没有被用于 Factory Home browser authentication。

`Actor` 是运行时 metadata，当前 FastAPI 可由 `X-Hermes-Actor-*` 形成 Actor，但这些 header 不是认证证据。现有 Project table 没有 owner/membership/RBAC scope 表。最小可复用且不改变 schema 的 scope source 是 `project_transition_records` 的 initial creation fact：`previous_state IS NULL`、`requested_by_type = 'user'` 和 `requested_by_id = verified OIDC subject`。这只能表达 conservative creator/requester visibility，不能解释为协作成员、管理员、审批者或全局 Project 可见性。

## 2. Identity Source and Scope Composition

```text
Authorization: Bearer OIDC JWT
  → OidcTokenVerifier
  → VerifiedIdentity(subject, actor=Actor(USER, subject))
  → ProductApiRequest.verified_identity_subject
  → ProductApiFacade actor_scope(identity_verified=true)
  → PostgresCreatorActorProjectScope
  → initial project_transition_records requested_by_id match
  → frozenset/tuple of authorized Project IDs
  → PostgresFactoryHomeReadModel
  → GET /factory-home/**
```

`PostgresCreatorActorProjectScope` queries only initial Project transitions matching the verified subject. It returns `None` if identity is not verified, subject is absent, actor metadata differs from the subject, or the storage operation fails. It never returns all Projects. The existing `DenyAllActorProjectScope` remains available and the unavailable model remains the bootstrap fallback.

## 3. Bootstrap and Browser Trust Boundary

Factory Home routes now require a bearer token independently of historical actor header handling. `create_app(..., oidc_verifier=...)` applies OIDC verification only to `/factory-home/**`; existing Product API routes retain their prior behavior. Missing verifier configuration yields `503 FACTORY_HOME_IDENTITY_UNAVAILABLE`; missing or invalid token yields `401 FACTORY_HOME_AUTH_REQUIRED` / `401 FACTORY_HOME_AUTH_INVALID`.

When an `X-Hermes-Actor-ID` or `X-Hermes-Actor-Type` header conflicts with the verified token subject or the expected `user` type, the request receives `401 FACTORY_HOME_ACTOR_MISMATCH`. A matching header has no authority effect; OIDC verification remains the only trusted identity source. The browser does not submit Project IDs as authorization proof and the frontend contains no auth or scope logic.

`api_main` now composes `PostgresFactoryHomeReadModel` with `PostgresCreatorActorProjectScope` only when a database URL and all explicit OIDC configuration values are present: `HERMES_OIDC_ISSUER`, `HERMES_OIDC_AUDIENCE`, and valid `HERMES_OIDC_JWKS_JSON`. Missing or invalid configuration keeps Factory Home unavailable rather than providing a fallback user, test issuer, hardcoded Project set or global query.

## 4. Security Model and Isolation

| Scenario | Actual result |
| --- | --- |
| Verified user A / scope `{Project A}` | Portfolio contains only Project A. |
| Verified user B / scope `{Project B}` | Portfolio contains only Project B. |
| User A requests Project B | `NOT_AVAILABLE` with `item: null`; no Project B title, state, version, timestamps, gate count or existence fact is returned. |
| Missing or malformed identity | 401 before the read model is used. |
| Verifier not configured | 503 fail closed before the read model is used. |
| Verified user without scoped Projects | Scope resolver returns an empty collection; no global fallback is possible. |
| Browser header says user B, verified JWT says user A | 401 actor mismatch; user B is never queried. |

The pre-existing FH-1 discipline remains unchanged: all endpoints are GET-only and source-derived; progress stays `null` with `NOT_AVAILABLE`; worker/task/count/completion values are omitted; unavailable summary/owner/plan revision/risk/evidence stay `null`; Factory telemetry remains `NOT_AVAILABLE`; Drafts remain `NOT_IMPLEMENTED`; cursor/SSE remain absent.

## 5. Files Changed

| File | Change |
| --- | --- |
| `hermes-runtime/src/hermes_runtime/domain/product_api.py` | Adds optional `verified_identity_subject` transport context to `ProductApiRequest`. |
| `hermes-runtime/src/hermes_runtime/application/product_api.py` | Includes verified subject/flag in Factory Home actor scope passed to the existing read-model façade. |
| `hermes-runtime/src/hermes_runtime/infrastructure/postgres_factory_home_read_model.py` | Adds `PostgresCreatorActorProjectScope`, based on existing Project creation transition records. |
| `hermes-runtime/src/hermes_runtime/infrastructure/fastapi_app.py` | Adds OIDC-gated dispatch only for existing Factory Home GET routes. |
| `hermes-runtime/src/hermes_runtime/api_main.py` | Adds explicit OIDC configuration composition and fail-closed scope resolver bootstrap. |
| `hermes-runtime/tests/test_factory_home_identity_scope.py` | Adds OIDC identity, actor mismatch, scope isolation, no-leak and resolver tests. |
| `docs/PROTEUS_FACTORY_HOME_IMPLEMENTATION_V1.md` | Receives FH-1.x implementation delta. |
| `frontend/README.md` | Receives verified identity deployment configuration note. |

## 6. Protected Paths

Protected-path inspection returned no changes for `hermes-runtime/migrations`, `hermes-runtime/src/hermes_runtime/trial`, `hermes-runtime/tests/test_p6_autonomous_trial.py`, `docs/P6_REPORT.md` or `docs/evidence/p6`. Scheduler, Worker, Verifier, Execution authority and Gate transition logic were not modified.

## 7. Tests

| Command | Result |
| --- | --- |
| `PYTHONPATH=src .venv/bin/python -m unittest tests.test_factory_home_identity_scope tests.test_factory_home_read_model tests.test_fastapi_service_host tests.test_oidc_and_human_gate_ui tests.test_public_api_boundary tests.test_public_api_domain tests.test_factory_workspace_ui -v` | **PASS — 35 tests.** Includes verified identity, missing/invalid identity, mismatch, user A/B isolation, unauthorized lookup no-leak, resolver fail-closed, read model, FastAPI/OIDC/API and UI regressions. |
| `cd frontend && pnpm test` | **PASS — 33 tests.** |
| `cd frontend && pnpm build` | **PASS.** |
| `cd frontend && pnpm lint` | **PASS — 0 warnings / 0 errors.** |
| `PYTHONPATH=src HERMES_TEST_DATABASE_URL='postgresql://postgres:hermes@127.0.0.1:55432/hermes_test' .venv/bin/python -m unittest tests.test_p6_autonomous_trial -v` | **PASS — 1 test, 101.035 s.** The test used its unchanged isolated `CREATE DATABASE hermes_p6_ci` semantics. |

The P6 run emitted two pre-existing `ResourceWarning` notices for unclosed runner output file handles in `trial/harness.py`; the acceptance result was PASS and no P6 file was changed.

## 8. Remaining Risks and Next Phase

The scope model is intentionally **creator/requester-only** because no Project membership/ownership authority exists. It must not be broadened into roles or RBAC by inference. The deployment still needs real issuer/audience/JWKS configuration and a production secret-management decision; absent configuration safely returns unavailable.

**FH-1.x is implementation complete and P6 acceptance passes.** The next design candidate may be E1 EntryDraft Core, but only after an explicit decision on whether creator-only Project visibility is the intended product authorization model. Do not proceed to FH-2 mutation, Approval Bridge or Live Workspace on the basis of this read-only scope resolver alone.
