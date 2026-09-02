# E14 Worker Control Plane — Implementation Delivery Report

**Delivery state:** `E14 PASS / IMPLEMENTATION CANDIDATE`
**Baseline:** branch `feat/e14-worker-control-plane`, based on remote `master` (E13-complete, `E14–E16 | NOT ENTERED` in `PROTEUS_E2X_P6_BASELINE_MANIFEST.md`).
**Scope:** E14 only. This candidate is an isolated, verified implementation candidate and is **not committed, published, merged, or final acceptance authority** (same convention as `THIS_E13_IMPLEMENTATION_CANDIDATE`).

## 1. Decision and authority boundary

E14 delivers a **creator-scoped, read-only Worker Control Plane projection** over existing P2 execution authority facts. It surfaces three surfaces: the **Worker Fleet**, the **Worker Detail**, and the **Execution Queue**. Every projection is **source-derived and read-only**: it issues no DML, mints no fencing tokens, acquires no leases, admits no workers, and cannot transition any Project, Task, Execution, Lease, or Fencing state.

The browser may only call three GET endpoints:
- `GET /factory-home/workers` — creator-scoped worker template fleet.
- `GET /factory-home/workers/{worker_id}` — creator-scoped worker template detail (assignments + leases).
- `GET /factory-home/execution-queue` — creator-scoped pending/active execution queue.

The server derives the actor's scoped project ids from the **verified OIDC identity** (never from a browser-supplied header or param). The browser **cannot** submit an actor, creator-id, project-id, scope, authority, or any SQL. A worker/project that is not in the caller's creator scope is **not disclosed** (fail-closed). Unverified identities resolve to no scope. The requirement's **"no fencing token"** constraint is enforced at every exposed surface.

## 2. Delivered interaction model

| Surface | Route | Delivered behavior | Authority boundary |
|---|---|---|---|
| Worker Fleet | `GET /factory-home/workers` | Table of creator-scoped worker templates: worker id, revision, runtime kind, trust level, availability, admission, concurrency capacity, active/total assignments, project, reason, updated-at. Rows link into Worker Detail. Template/Runtime filter. | Read-only projection over `worker_template_availability` + `worker_template_revisions`; no writes. |
| Worker Detail | `GET /factory-home/workers/{worker_id}` | Worker template header plus up to 50 recent assignments and 50 leases (state, agent identity, scheduler, timestamps). | Fail-closed if the worker is not in the caller's creator scope or does not exist; lease/assignment payloads expose no fencing token. |
| Execution Queue | `GET /factory-home/execution-queue` | Creator-scoped pending/active queue items: queue state, request state, priority, task, worker template, available-at, enqueued-at, current lease badge. Queue/Project/Task filter. | Read-only view over `execution_queue_current_states`; no claim, no lease acquisition. |
| Pending / unconfigured | — | `authorityPendingAdapters` returns a **pending** adapter so the three routes render an explicit pending/unavailable surface rather than crashing. | No optimistic or fallback mutation of authority facts. |

## 3. Server and persistence evidence

The projection is a **new read-only adapter**, `PostgresWorkerControlPlaneReadModel`
([`hermes-runtime/src/hermes_runtime/infrastructure/postgres_worker_control_plane_read_model.py`](../hermes-runtime/src/hermes_runtime/infrastructure/postgres_worker_control_plane_read_model.py)). It reuses `PostgresCreatorActorProjectScope` for creator scoping and reads only source authority tables. It issues **no DML, no migration, and no schema change** — there is no `00xx` E14 migration. All P0–P6 authority and role/ACL/function-owner structure is unchanged.

The Product API facade exposes a creator-scoped controller
([`hermes-runtime/src/hermes_runtime/application/worker_control_plane.py`](../hermes-runtime/src/hermes_runtime/application/worker_control_plane.py)) wired through
[`api_main.py`](../hermes-runtime/src/hermes_runtime/api_main.py) and
[`product_api.py`](../hermes-runtime/src/hermes_runtime/application/product_api.py). The FastAPI transport
([`fastapi_app.py`](../hermes-runtime/src/hermes_runtime/infrastructure/fastapi_app.py)) registers the three GET routes and dispatches through the existing factory dispatcher, so verified-identity precedence and fail-closed unauthenticated behavior apply.

### Verified-identity precedence and safety

- Unauthenticated requests **fail closed** (no projection data).
- A browser-supplied actor header can **never override** the verified OIDC identity.
- Verified subject is authoritative even when the actor id string differs from the verified subject.
- `worker_detail` is fail-closed for foreign/unknown workers (returns `NOT_AVAILABLE`) — fixing the previous cross-creator scope leak.
- Array bindings use Python `list` (the earlier tuple→list bug is fixed and verified against real PostgreSQL).

## 4. No fencing token (requirement)

The E14 requirement is explicit: **no fencing token**. Every read-model payload omits it:

- **Worker detail leases**: `_safe_lease_payload` no longer emits `fencing_token`; the leases SELECT no longer reads `el.fencing_token`.
- **Worker fleet / worker detail / assignments / queue**: no `fencing_token` field appears in any safe payload.
- **Frontend**: `WorkerLeaseViewModel.fencingToken` and the `wfLease` mapper's `fencingToken` mapping were removed.

The only remaining `fencing_token` SQL reads `ercs.current_fencing_token` in the queue SELECT, which is used only as an internal read and is **not** emitted by `_safe_queue_item_payload`. Tests assert the JSON-serialized output of every surface contains no `fencing_token`, `dsn`, `postgres://`, or `password`.

## 5. Frontend evidence

New creator E14 components under [`frontend/src/components/`](../frontend/src/components/):
`WorkerFleet.tsx`, `WorkerDetail.tsx`, `ExecutionQueue.tsx`, routed in
[`App.tsx`](../frontend/src/App.tsx) at `/workers`, `/workers/:id`, `/execution-queue`.

The `WorkerControlPlaneApi` interface and view models (`WorkerFleetItemViewModel`, `WorkerDetailViewModel`, `WorkerLeaseViewModel`, `ExecutionQueueItemViewModel`) were added to [`frontend/src/models.ts`](../frontend/src/models.ts). The Product API adapter
([`frontend/src/api/productApiAdapters.ts`](../frontend/src/api/productApiAdapters.ts))
maps the server envelope into those read-only view models and drops the fencing token from leases; the pending factory
([`frontend/src/api/adapters.ts`](../frontend/src/api/adapters.ts)) returns `pending` until the Product API is configured.

### Frontend test results (Vitest): 94/94 PASS, 14/15 files

Includes the new [`frontend/src/e14WorkerControlPlane.test.tsx`](../frontend/src/e14WorkerControlPlane.test.tsx) (7 tests: fleet render/filter/link, empty state, detail render, unavailable state, queue render/LEASED badge). The single non-passing file (`e2e/e13-editor.spec.ts`) fails **at Playwright collection** with a pre-existing `test.describe.configure()` environment error and runs **zero** E14 tests; it is unrelated to this candidate and was already present in the E13 baseline.

| Check | Result | Notes |
|---|---|---|
| `npx tsc --noEmit` | PASS | 0 errors |
| Vitest unit/component (incl. E14 7 tests) | PASS | 94/94, 14/15 files |
| `theme.test.ts` (i18n `validateCatalogs`) | PASS | 7/7 after i18n E14 repair |
| `oxlint` | PASS | no new E14 errors |

### i18n repair

The prior E14 i18n pass had added the 31 `e14.*` message keys to the `MessageKey` type union and every locale `completeCatalogs` entry **except `zh-CN`**, and had **not** added the `e14.*` value entries to the canonical `en` object (leaving stray `| 'e14...'` type-union continuation lines after the object). This broke `validateCatalogs()` and the theme catalog-equality test. Repair ([`frontend/src/i18n.ts`](../frontend/src/i18n.ts)): added the 31 E14 English pairs to `en`, made the type union contiguous, removed the stranded continuation lines, and added all 31 E14 Chinese pairs to `zh-CN`. `validateCatalogs()` now returns true and all 22 locale catalogs are key-complete for E14.

## 6. Backend test evidence

All three E14 backend test files pass (run against the seeded real-PostgreSQL E14 database):
- [`tests/test_e14_worker_control_plane_product_api.py`](../hermes-runtime/tests/test_e14_worker_control_plane_product_api.py) — 7/7 PASS (verified-scope passthrough, unconfigured fail-closed, unknown-route rejection, verified-subject precedence, worker-detail id passthrough).
- [`tests/test_e14_fastapi_transport.py`](../hermes-runtime/tests/test_e14_fastapi_transport.py) — 6/6 PASS (200 envelopes for all three routes, unauthenticated fail-closed, browser-header-can't-override identity, long-worker-id safety).
- [`tests/test_e14_worker_control_plane_postgres.py`](../hermes-runtime/tests/test_e14_worker_control_plane_postgres.py) — **5/5 PASS against real PostgreSQL** (creator scoping, cross-creator worker detail not disclosed, no fencing/DSN/password in JSON, unknown worker fail-closed, unverified scope never resolved).

**17/17 E14 backend tests PASS** against the seeded `hermes_e14_*` real-PostgreSQL database (worker templates and cross-creator data present, so the isolation and fencing tests run for real rather than skipping).

## 7. Regression evidence

- E14 is a read-only overlay; no existing authority path or migration changed.
- `git diff --check` returns clean (no whitespace/trailing errors).
- Secret scan: no credentials or secrets introduced (DSN/password assertions fail closed in tests).

## 8. Final test numbers

Counts are **disjoint** — the i18n `validateCatalogs()` test lives inside `theme.test.ts` and is part of the 94 Vitest tests, so it is **not** added again on top. Non-test gates (TypeScript compile, `git diff --check`) are listed separately and are **not** test counts.

**Automated tests (111):**

| Category | Run | Passed | Skipped | Failed |
|---|---|---|---|---|
| Vitest unit/component (14 files incl. 7 E14 + 8 theme/i18n) | 94 | 94 | 0 | 0 |
| E14 Product API unit | 7 | 7 | 0 | 0 |
| E14 FastAPI transport | 6 | 6 | 0 | 0 |
| E14 real-PostgreSQL | 5 | 5 | 0 | 0 |
| **Total automated tests (94 + 17)** | **111** | **111** | **0** | **0** |

**Non-test gates (pass, not counted in 111):** `npx tsc --noEmit` (0 errors); `git diff --check` (clean). The single non-passing Vitest-collected file `e2e/e13-editor.spec.ts` fails **at Playwright collection** with the pre-existing `test.describe.configure()` environment error and runs zero tests; it is a baseline environment issue, unrelated to E14, and does **not** claim any Playwright E2E run is green.

## 9. Security review

**Verdict: `PASS-WITH-FINDINGS`.** The candidate is safe to publish: the E14 read-only surfaces are identity-scoped and fail closed across creators, all SQL is parameterized, no secret/credential/DSN/fencing-token is disclosed, and both independent PoCs executed against real PostgreSQL confirmed the isolation boundaries. The findings below are LOW/informational hardening items (§9.2), none of which is an exploitable cross-tenant leak; they are recorded as residual risk (no repo change made for them).

Security review methodology: OWASP WSTG/ASVS-informed threat modeling, run as **three independent hunters in parallel** (attack surface, auth/data-isolation, runtime/supply/config), followed by **two independent PoC engineers** executing against a real PostgreSQL 16.15 instance (all 33 migrations) driving the actual `PostgresWorkerControlPlaneReadModel` + `PostgresCreatorActorProjectScope`. Findings were cross-checked between hunters and falsified/confirmed by the PoCs.

### 9.1 Confirmed mitigations (no action needed)

| # | Concern | Evidence |
|---|---|---|
| M1 | Identity derivation (three routes) | All three E14 GET routes dispatch via existing `_factory_dispatch` → `_verified_dispatch` (fastapi_app.py:247-257). Subject/actor derived server-side from the OIDC `hermes_session` cookie (`httponly`/`secure`/`samesite=lax`, `InMemoryOidcSessionStore` ttl 900s) or a verified bearer; browser headers are compared-for-mismatch and rejected (404/401), never treated as authority. CWE-287 not triggered. |
| M2 | Creator-scope + cross-creator isolation | `worker_detail` gates on `awa.template_id = %s AND wtr.project_id = ANY(%s)` (read model :116-117) — foreign workers fail closed `WORKER_TEMPLATE_NOT_FOUND`. `execution_queue` gates on `eqcs.project_id = ANY(%s)` (:189). Assignments/leases independently scope-constrained (:128/:139) and unreachable past the template guard. **PoC 2: 36/36 checks pass** — creatorB sees zero creatorA queue rows and cannot retrieve creatorA worker_detail; authority tables intact after injection strings. |
| M3 | SQL parameterization + read-only | All 10 `%s` placeholders parameterized; AST scan shows **0 f-strings, 0 `.format()`** in the read model. **PoC 2** confirmed all 6 crafted/malformed worker_ids (`' OR 1=1 --`, `'; DROP TABLE projects; --`, `'; DELETE FROM …;`, `'{}{}'""'`, `a\x00b`, random UUID) degrade fail-closed with no schema/DSN/exception echo. All 5 `connection.execute()` calls are SELECT; zero `.commit()`/DML/autocommit. `psycopg.connect()` `autocommit=False` + `with`-close rolls back. |
| M4 | Credential/secret/fencing-token leak scan | No `fencing_token`, `dsn`, `password`, `postgres://`, or `api_key` in any safe payload. `ercs.current_fencing_token` is read internally but omitted by `_safe_queue_item_payload`; leases never read `el.fencing_token`. `ensure_safe_response` (domain/product_api.py:109-142) recursively rejects secret-keyed fields. **PoC 1/2** confirmed no secret/credential/capability/tool disclosure and no DSN/exception echo in DEGRADED payloads. |
| M5 | Product API forbidden-field / authority shape | `reject_forbidden_authority_shape` (product_api.py:85) rejects forbidden authority fields on every request; E14 routes are GET-only so body/authority are server-derived and inert. |
| M6 | E11/E12/E13 authority isolation | E14 is a read-only overlay; no authority path or migration changed (`git diff --check` clean; no `00xx` E14 migration). |
| M7 | Commit-scope hygiene | Confirmed pre-existing `.omo/` (agent scratch) and `frontend/scripts/create-test-token.js` (E13 e2e helper) are **not** part of the E14 candidate; they are excluded from the publish staging set (§11). |

### 9.2 Findings (recorded, not exploitable cross-tenant)

| # | Severity | CWE | Finding | PoC status | Residual risk |
|---|---|---|---|---|---|
| F1 | LOW / informational | CWE-863 | `list_workers` uses `WHERE wtr.project_id = ANY(%s) OR wtr.project_id IS NULL` (:80), disclosing NULL-project **global** shared-template metadata (template id, revision, runtime kind, trust level, concurrency capacity, availability/admission status, reason) to any verified creator with ≥1 project. `worker_detail` has **no** IS NULL escape (:116-117), so clicking a global template returns `WORKER_TEMPLATE_NOT_FOUND` — a fail-open/fail-closed **list/detail asymmetry**. Counts remain scope-limited (`ANY(scoped)` at :71/:76). | **PoC 1 CONFIRMED** on real PG: creatorA sees tpl-global(null)+tpl-owned-a; creatorB sees tpl-global only. No secrets/credentials/capabilities/tools (detail-only stay closed); no cross-tenant assignment/agent data. | Recommend dropping `OR wtr.project_id IS NULL` unless a NULL-project template is intended to be entitled to caller scope. LOW impact: shared-template *metadata* (no per-tenant data) is disclosed to authenticated creators. |
| F2 | LOW / informational | CWE-400 (CWE-770) | `list_workers` has no LIMIT and runs 2 correlated `count(*)` subqueries (resource growth). Worker detail caps assignments/leases at 50 each (:130/:146); queue caps at 200 (:191). Migration 0016 has no covering index on `(worker_template_id, worker_template_revision, project_id)`. | not PoC-executed (static/diagnostic) | Recommend a covering index + hard LIMIT cap on `list_workers`. No current production trigger. |
| F3 | informational | CWE-200 | `_find_secret_values` (domain/product_api.py:136) matches secret keys by **equality** only, so a differently-named sensitive field (e.g. `current_fencing_token`) would not be caught by the response scan — it is currently safe only by allowlist omission, not by the scanner. | static/diagnostic | Recommend adding `actor`/`scope`/`authority` to the shared forbidden-field set (CWE-284) and a substring/pattern secret scan. No current exploit path. |
| F4 | informational (inherited, not E14-introduced) | CWE-117 | `X-Request-ID` is reflected unvalidated into response headers (fastapi_app.py:108, :452, :522); CRLF in the value yields literal header lines. Present on all routes, pre-existing. | static | Pre-existing on all routes, not introduced by E14. Requires client to poison its own response + cache keying to escalate. Out of E14 scope; logged for a future hardening pass. |

Overall, no exploitable cross-tenant leak, no injection, no read-write escape, and no secret disclosure were found; the candidate may proceed to the gated publish flow.

## 10. E15–E16 status

**NOT ENTERED.** No E15 or E16 work has started. `PROTEUS_E2X_P6_BASELINE_MANIFEST.md` still records `E14–E16 | NOT ENTERED`; this candidate is not merged and does not update the status matrix (a separate closure step updates the manifest upon acceptance, per the E13/E12 convention).

## 11. Acceptance limits and next steps

This candidate is verified and green (111/111 automated tests: 94 Vitest + 17 E14 backend, the latter against real PostgreSQL). The security review has **passed** (verdict `PASS-WITH-FINDINGS`, §9) with only LOW/informational hardening items recorded as residual risk. The next step is the gated publish flow: precise staging → commit → push → open PR → CI → post-merge verification → status-closure update marking `E14 Worker Control Plane | PASS / COMPLETE` in `PROTEUS_E2X_P6_BASELINE_MANIFEST.md` and the README. Per the gate, no commit, push, or PR is made until the security review passes (now satisfied). E14 does not enter E15–E16.

## References

[1]: E14 read model, [`hermes-runtime/src/hermes_runtime/infrastructure/postgres_worker_control_plane_read_model.py`](../hermes-runtime/src/hermes_runtime/infrastructure/postgres_worker_control_plane_read_model.py).
[2]: E14 Product API controller, [`hermes-runtime/src/hermes_runtime/application/worker_control_plane.py`](../hermes-runtime/src/hermes_runtime/application/worker_control_plane.py).
[3]: E14 transport, [`hermes-runtime/src/hermes_runtime/infrastructure/fastapi_app.py`](../hermes-runtime/src/hermes_runtime/infrastructure/fastapi_app.py).
[4]: E14 frontend components, [`frontend/src/components/`](../frontend/src/components/), [`App.tsx`](../frontend/src/App.tsx).
[5]: E14 frontend tests, [`frontend/src/e14WorkerControlPlane.test.tsx`](../frontend/src/e14WorkerControlPlane.test.tsx).
[6]: E14 backend tests, [`hermes-runtime/tests/test_e14_worker_control_plane_product_api.py`](../hermes-runtime/tests/test_e14_worker_control_plane_product_api.py), [`hermes-runtime/tests/test_e14_fastapi_transport.py`](../hermes-runtime/tests/test_e14_fastapi_transport.py), [`hermes-runtime/tests/test_e14_worker_control_plane_postgres.py`](../hermes-runtime/tests/test_e14_worker_control_plane_postgres.py).
[7]: E14 i18n, [`frontend/src/i18n.ts`](../frontend/src/i18n.ts) (31 E14 keys, 22 locales).
[8]: E13 baseline pattern, [`E13_PROPOSAL_MASTER_PLAN_EDITOR_IMPLEMENTATION_DELIVERY_REPORT.md`](E13_PROPOSAL_MASTER_PLAN_EDITOR_IMPLEMENTATION_DELIVERY_REPORT.md) and [`PROTEUS_E2X_P6_BASELINE_MANIFEST.md`](PROTEUS_E2X_P6_BASELINE_MANIFEST.md).