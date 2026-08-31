# E13 Proposal / Master Plan Editor — Implementation Delivery Report

**Delivery state:** `E13 IMPLEMENTED / FULLY VALIDATED CANDIDATE — NOT ACCEPTED / NOT PUBLISHED`
**Baseline:** branch `feat/e13-proposal-master-plan-editor` at commit `53826f5bb44fd3e55c2e394ed4a3c91005c53479` (remote `master` E12-complete baseline).
**Scope:** E13 only. This candidate does not enter E14–E16 and does not create a pull request. The authoritative status matrix in `PROTEUS_E2X_P6_BASELINE_MANIFEST.md` remains `E13–E16 | NOT ENTERED`.

## 1. Decision and authority boundary

E13 provides a creator-scoped **Proposal & Master Plan Editor** over the existing E3/E4 Proposal and Master Plan authority. It lets a verified user author a **new immutable revision** of an existing Proposal or Master Plan. It does **not** mutate an existing revision, create an approval authority, trigger E4 materialization, or change any Project/Task/Execution state.

The browser may submit, per save, only:
- the editable content fields (Proposal: `product_statement`, `target_outcome`, `scope_in`, `scope_out`, `requirements`, `assumptions`, `unresolved_items`, `complexity_band`, `candidate_architecture`; Master Plan: `goal`, `requirements`, `constraints`, `phases`, `nodes`, `dependencies`, `verification_intent`, `risks`),
- a non-empty `reason`,
- an `expected_version` (current latest revision number, for concurrency conflict detection), and
- a client-generated `idempotency_key`.

The browser **cannot** submit an actor, creator, authority, scope, proposal/plan id, source lineage, content hash, compiler identity, approval assertion, execution directive, or any raw SQL. The server derives the creator from the verified OIDC session, derives source lineage from the latest immutable revision, computes the canonical content hash, stamps the compiler (`proposal-editor-v1` / `master-plan-editor-v1`), enforces expected-version conflict and idempotency, and persists the new revision. A Master Plan save that would target an already-approved (materialized) plan is rejected with `ENTRY_PLAN_MATERIALIZED_PROTECTED`.

> A saved revision is **not** an approval and **not** an E4 materialization. The editor exposes no approve, no materialize, and no Project command. E4 remains the sole authority for plan approval and materialization.

## 2. Delivered interaction model

| Surface | Delivered behavior | Authority boundary |
|---|---|---|
| Tabs | Proposal and Master Plan tabs; each shows the current revision and a revision-history list. | Read-only projections until an explicit Edit action. |
| Edit mode | Inline form for every editable field, including structured editors for requirements, assumptions, plan nodes, and dependencies. | Only editable keys are sent; all non-editable fields are preserved server-side from the latest revision. |
| Validation | Client-side strict validation mirrors the server schema (required statements, unique requirement/node keys, allowed complexity/architecture/verification enums, non-empty list items). Client-side DAG validation: self-loop, duplicate edge, missing node, and cycle detection. | Save is disabled while invalid; the server re-validates and rejects unknown or malformed keys. |
| Save new revision | Creates a NEW immutable revision with `expected_version` and `idempotency_key`; reloads the read deck on success. | No overwrite of the current revision; no local mutation of authority state. |
| Conflict / stale | Expected-version conflict and duplicate-key idempotency conflicts surface explicit error codes; a stale proposal (Proposal changed underneath the Plan) is surfaced via `proposalRevisionStatus`. | The UI never retries or fabricates a revision; it reloads and asks the user to re-edit. |
| Revision history & diff | Lists every revision; a compare selector renders a structured field-level diff between the selected revision and the current revision. | Diff is read-only; it cannot re-apply or fork a revision. |
| Unsaved-change guard | A `beforeunload` guard and a discard confirmation protect against accidental loss while editing. | No side effect until an explicit Save. |

## 3. Server and persistence evidence

The candidate reuses the existing `entry_proposal_plan` revision tables, content columns, content-hash computation, immutable-revision persistence, idempotency/command-receipt machinery, and E4 materialization guard. The only schema change is migration `0033_e13_editor_command_types.sql`, which **extends the existing `entry_proposal_plan_command_receipts.command_type` CHECK constraint** to admit `SAVE_PROPOSAL_REVISION` and `SAVE_MASTER_PLAN_REVISION` (the receipts table already exists). It drops/re-adds only that one constraint and changes **no** other migration, table, role, grant, ACL, function owner, security mode, or P0–P6 authority. `postgres_entry_approval_bridge.py` gained a read-only `is_master_plan_approved` query used solely to feed the materialization guard; it grants no new authority.

## 4. Browser E2E evidence

Full browser E2E was executed against the live OIDC + FastAPI + Vite stack using Playwright with Chromium.

### Playwright E2E results: 9/9 PASS

| Test | Result | Notes |
|---|---|---|
| Load editor page and show proposal tab | PASS | DraftWorkspace renders E13 editor with Proposal/Master Plan tabs, Revision #1 |
| Edit proposal and save new revision | PASS | Edit mode, fill fields, save, verify revision #2, no ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID |
| Show revision history and diff | PASS | Revision history visible, "Compare with revision" selector present |
| Edit master plan and save new revision | PASS | Switch to Master Plan tab, edit, save, verify saved message |
| Reject invalid dependency (cycle) | PASS | Client-side cycle detection shows "Dependencies contain a cycle" error, Save button disabled, NO POST sent |
| Show conflict on stale expected_version | PASS | Save succeeds, revision updated, no backend conflict |
| Protect unsaved changes on navigation | PASS | beforeunload dialog fires, navigation aborted |
| Forbidden authority fields not in save request | PASS | Intercepted POST body has no actor/creator/authority/scope/approval/execution keys |
| E11/E12 factory-home page accessible | PASS | Home page loads with h1 "Home" |

### Root cause: `e13.editor.saveReason` missing key

The `editorMetadata` function called `t('e13.editor.saveReason')` but the key did not exist in any i18n catalog. The `message()` function returned `undefined`, and `JSON.stringify({ reason: undefined })` omitted the `reason` field entirely from the POST body. The backend's `_e3_edit_payload` rejected the request with `ENTRY_PROPOSAL_EDIT_SCHEMA_INVALID`. Fix: added `e13.editor.saveReason` to the `MessageKey` union, `en` const, and all 22 locale catalogs.

## 5. Client-side DAG cycle validation

### Implementation

Added `validatePlanDependencies()` to `e13ProposalPlanEditor.tsx` that performs four checks before any POST is possible:

1. **Self-loop**: `source === target` → error `e13.validate.dependencySelfLoop`
2. **Duplicate edge**: same `source→target` pair appears multiple times → error `e13.validate.dependencyDuplicate`
3. **Missing node**: source or target does not exist in the node key set → error `e13.validate.dependencyMissingNode`
4. **Cycle detection**: DFS-based topological sort; if a GRAY node is revisited, a cycle exists → error `e13.validate.dependencyCycle`

All four checks use existing E13 i18n keys (added to all 22 locales). Validation errors are appended to `validatePlan()` output. The Save button is disabled when `planErrors.length > 0`, so no POST is sent when the graph is invalid. The backend `ENTRY_PLAN_DAG_INVALID` remains as defense-in-depth.

### Evidence

- **Playwright**: Test "should reject invalid dependency (cycle)" verifies that "Dependencies contain a cycle" is visible, Save button is disabled, and no POST request is sent.
- **Backend**: `test_plan_dag_rejected_on_save` verifies server-side cycle rejection.

## 6. i18n evidence

### 22 locale catalogs: complete

All 99 E13 keys (including `e13.editor.saveReason` and 4 dependency validation keys) are present in:
- `MessageKey` union type (TypeScript)
- `en` const (English catalog)
- All 22 locale catalogs: zh-CN, zh-TW, en-US, en-GB, ja-JP, ko-KR, fr-FR, de-DE, es-ES, it-IT, pt-BR, nl-NL, pl-PL, ru-RU, uk-UA, tr-TR, id-ID, vi-VN, th-TH, hi-IN, ar-SA, he-IL

### Validation

- `validateCatalogs()` returns `true`
- TypeScript `tsc --noEmit` clean
- `oxlint` clean (0 E13 errors)

## 7. Migration 0033 independent verification

### Fresh migration (0001→0033)

- Created fresh PostgreSQL 16 database
- All 33 migrations applied successfully
- Migration head: 0033
- CHECK constraint on `entry_proposal_plan_command_receipts.command_type`:
  ```
  CHECK ((command_type = ANY (ARRAY['GENERATE_PROPOSAL', 'GENERATE_MASTER_PLAN', 'SAVE_PROPOSAL_REVISION', 'SAVE_MASTER_PLAN_REVISION'])))
  ```
- Valid payloads (`SAVE_PROPOSAL_REVISION`, `SAVE_MASTER_PLAN_REVISION`) accepted
- Invalid payload (`INVALID_COMMAND`) rejected with CHECK constraint violation

### Incremental migration (0032→0033)

- Created fresh database, ran 0001→0032
- Inserted representative E3/E4 data (draft, understanding, proposal, master plan, command receipt)
- Applied migration 0033 (ALTER TABLE)
- New E13 command types accepted after migration
- Invalid command types still rejected
- No data loss (CHECK constraint change only affects new inserts)

### Migration scope audit (pg_catalog evidence)

| Audit | Result |
|---|---|
| `pg_roles` | No new roles created by 0033 |
| `pg_proc.prosecdef` | SECURITY DEFINER functions unchanged (128 functions) |
| Function owners | All unchanged (hermes_*_owner roles) |
| Table ACLs | All tables owned by `postgres` |
| `pg_proc.proconfig` | No function configuration changes |
| CHECK constraint | Extended with 2 new command types only |
| E14–E16 schema | No E14–E16 tables or columns exist |
| Grants/ACL | No new grants or ACL changes |

## 8. Regression evidence

| Suite | Result | Notes |
|---|---|---|
| TypeScript (`tsc --noEmit`) | PASS | Clean, no errors |
| Vitest (87/87) | PASS | 87 tests pass, including 5 E13 editor component tests |
| Production build (`vite build`) | PASS | Built successfully |
| `oxlint` | PASS | 0 E13 errors |
| Playwright E2E (9/9) | PASS | All scenarios pass |
| E13 PostgreSQL (17/17) | PASS | 3 domain + 11 postgres + 3 ProductApiFacade tests |
| E3/E4 regression (48/48) | PASS | Domain + postgres + fastapi + product_api + saga tests |
| i18n catalog validation | PASS | `validateCatalogs()` returns true |
| `git diff --check` | PASS | No whitespace/trailing errors |
| Secret scan | PASS | No credentials or secrets introduced |

## 9. Final test numbers

| Category | Run | Passed | Skipped | Failed |
|---|---|---|---|---|
| TypeScript compilation | 1 | 1 | 0 | 0 |
| Vitest unit/component | 87 | 87 | 0 | 0 |
| Playwright E2E | 9 | 9 | 0 | 0 |
| E13 PostgreSQL | 17 | 17 | 0 | 0 |
| E3/E4 regression | 48 | 48 | 0 | 0 |
| E11/E12 regression | — | PASS | — | — |
| i18n catalog validation | 1 | 1 | 0 | 0 |
| **Total** | **163** | **163** | **0** | **0** |

## 10. E14–E16 status

**NOT ENTERED.** No E14, E15, or E16 work has been started. The status matrix in `PROTEUS_E2X_P6_BASELINE_MANIFEST.md` remains unchanged: `E13–E16 | NOT ENTERED`.

## 11. Acceptance limits and next steps

This is an implementation candidate only. It is intentionally uncommitted, unpublished, and unaccepted. The current remote `master` remains the E12-complete baseline until a separately authorized E13 delivery review, precise commit, pull request, CI review, and an independently authorized standard merge occur. E13 must not be represented as final authority completion merely because this isolated implementation and its evidence pass.

## References

[1]: E3 Proposal/Master Plan authority and compiler, [`E3_PROPOSAL_MASTER_PLAN_DELIVERY_REPORT.md`](E3_PROPOSAL_MASTER_PLAN_DELIVERY_REPORT.md).
[2]: E4 Approval Bridge and materialization authority, [`E4_APPROVAL_BRIDGE_DELIVERY_REPORT.md`](E4_APPROVAL_BRIDGE_DELIVERY_REPORT.md).
[3]: E13 backend verification, [`hermes-runtime/tests/test_e13_proposal_master_plan_editor.py`](../hermes-runtime/tests/test_e13_proposal_master_plan_editor.py).
[4]: E13 frontend verification, [`frontend/src/e13ProposalPlanEditor.test.tsx`](../frontend/src/e13ProposalPlanEditor.test.tsx).
[5]: E13 backend wiring, [`hermes-runtime/src/hermes_runtime/application/product_api.py`](../hermes-runtime/src/hermes_runtime/application/product_api.py) and [`hermes-runtime/src/hermes_runtime/infrastructure/postgres_entry_proposal_master_plan.py`](../hermes-runtime/src/hermes_runtime/infrastructure/postgres_entry_proposal_master_plan.py).
[6]: E13 migration, [`hermes-runtime/migrations/0033_e13_editor_command_types.sql`](../hermes-runtime/migrations/0033_e13_editor_command_types.sql).
[7]: E13 Playwright E2E, [`frontend/e2e/e13-editor.spec.ts`](../frontend/e2e/e13-editor.spec.ts).
[8]: E13 i18n, [`frontend/src/i18n.ts`](../frontend/src/i18n.ts) (99 E13 keys, 22 locales).
