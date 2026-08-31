# E11 User Command Transport — Post-Command E7 Projection Reconciliation Delivery

**Delivery state:** `IMPLEMENTATION CANDIDATE — PR #30 OPEN — NOT MERGED — NOT FINAL ACCEPTANCE`
**Scope:** This delivery closes the identified client-side reconciliation gap in the existing E11 implementation candidate. It does not create a new Project authority, semantic command, database migration, role, ACL, provider call, or E12 capability.

## 1. Purpose and authority boundary

The E11 command receipt is an authoritative record that the existing Control Plane accepted, rejected, or applied a semantic Project command. It is **not** a claim that the E7 Live Production projection has caught up. This delivery therefore implements the required client transition:

> `receipt accepted → creator-scoped E7 read reconciliation → applied UI state only after source-derived version confirmation`

The browser continues to submit only existing `pause` and `resume` Project semantics. The existing server-side allowlist remains `pause`, `resume`, and `cancel`; the browser provides no `cancel` control. No browser payload can select executor, requester, creator scope, raw SQL, Project state, event, or outbox data.

| Concern | Implemented rule |
| --- | --- |
| Command authority | Unchanged: the verified OIDC session, server-derived creator scope, and existing trusted Control Plane proxy determine authority. |
| Projection authority | Unchanged: only existing creator-scoped E7 snapshot and bounded live-feed reads supply the UI facts. |
| Applied criterion | A `CURRENT` E7 snapshot with the expected projection schema and numeric `project.version >= receipt.target_version`. |
| Event-feed role | Corroboration and stale/gap detection only; an event is never treated as an applied projection fact without the qualifying snapshot. |
| Boundedness | At most four attempts, with fixed bounded delay. No command resubmission or unbounded polling occurs. |
| Navigation/reload | The receipt id is stored in the query string. A fresh Operations mount uses the existing creator-scoped receipt GET, then only read APIs to reconcile it. |

## 2. State machine and failure behavior

The Operations workspace records only transient UI coordination state. While a command is `submitting`, `receipt_accepted`, or `reconciling`, both controls are disabled, preventing a second local command submission. The source snapshot remains the displayed Project fact until a qualifying replacement snapshot is read.

| State | Meaning | Permitted effect |
| --- | --- | --- |
| `submitting` | The receipt POST is in flight. | Disable command controls; do not change Project snapshot. |
| `receipt_accepted` / `reconciling` | A receipt exists but E7 is not yet confirmed. | Perform bounded, abortable creator-scoped snapshot/feed reads only. |
| `applied` | The expected source-derived Project version is visible in a current E7 snapshot. | Replace the displayed snapshot with that source-derived snapshot. |
| `rejected` | The authoritative receipt is rejected. | Present the stable rejection code; never reconcile it as applied. |
| `uncertain` | Timeout, malformed snapshot, unavailable/stale feed, schema mismatch, or read failure. | Preserve the prior snapshot and receipt correlation only; require a later normal read/navigation recovery. |
| `terminal_failure` | Command POST did not yield a usable receipt. | Present its stable code; make no read-derived applied claim. |

Every reconciliation has an `AbortController`. Unmounting Operations, a new command, or a receipt replacement aborts outstanding reads and increments an epoch token; stale asynchronous completions cannot overwrite a newer reconciliation state. E7 cursor anomalies and schema mismatches lead to snapshot rehydrate or `uncertain`, never command retry.

## 3. Changed implementation surfaces

| Surface | Change |
| --- | --- |
| `frontend/src/e11Reconciliation.ts` | Pure bounded reconciliation helper. It validates E7 schema/version facts, treats feeds as non-authoritative corroboration, and produces `applied` or safe uncertain results. |
| `frontend/src/App.tsx` | Adds explicit receipt/reconciliation states, control disabling, URL receipt recovery, abort/epoch cleanup, and source-snapshot replacement only after confirmation. It does not add cancel UI or optimistic Project mutation. |
| `frontend/src/models.ts` | Adds typed receipt action, E7 `asOf`, optional `AbortSignal` read inputs, and receipt GET capability to the existing frontend contracts. |
| `frontend/src/api/productApiAdapters.ts` | Maps the existing receipt GET and E7 fields, sends cookie-backed read requests with `AbortSignal`, preserves stable read error codes, and safely rejects malformed snapshots. |
| Tests | Add pure reconciliation, Operations interaction, adapter-error, and real PostgreSQL E11→E7 source-read tests. |

## 4. Verification evidence

All database evidence used the existing disposable PostgreSQL 16 migration baseline. No schema, role, grant, ACL, function ownership, or hardened search-path change was made.

| Verification | Result |
| --- | --- |
| E11 reconciliation helper | 8/8 tests passed: immediate/delayed confirmation, timeout, read failure, stale/duplicate feed recovery, schema rejection, and abort. |
| Operations component | 3/3 tests passed: receipt pending then E7-only applied update, duplicate-click prevention, receipt query recovery with reads only, and unmount abort. |
| Product API adapter | 9/9 tests passed: cookie credentialed receipt GET, abort signal, stable 401/403/404/409/422/429/5xx-style codes, timeout, malformed snapshot, and stale cursor behavior. |
| Full frontend matrix | 11 files / 80 tests passed; TypeScript `--noEmit`, Vite production build, and oxlint all passed. |
| E11/E7 backend focused matrix | Passed: public boundary, user transport, E11 FastAPI, E10 OIDC, E7 Product API, E11 PostgreSQL, E11→E7 PostgreSQL, and E7 PostgreSQL. The PostgreSQL subset completed 64 tests successfully. |
| Full runtime | `722 run / 12 skipped / 0 failures` in `666.583s`. |
| Browser attempt | Environment-blocked: the sandbox browser could not reach the remote isolated development host preview. No browser command request was issued. Rendered command/reconciliation behavior is covered by the Operations component tests and production build above. |

## 5. Acceptance and non-goals

This candidate now satisfies the post-command E7 reconciliation behavior that was missing from the first PR #30 review: the UI has an explicit pending/reconciling state, a bounded creator-scoped read loop, source-derived applied confirmation, safe rehydrate/uncertain handling, repeat-click prevention, abort cleanup, and reload receipt recovery.

It does **not** change the overarching acceptance authority. E11 remains `PARTIAL / ACCEPTANCE GAP` until PR review, a separately authorized standard merge, and post-merge verification occur. E9–E11 Wave A remains `NOT COMPLETE`, and E12–E16 remain `NOT ENTERED`.

> **Current status update (2026-08-31):** This document is a historical delivery artifact. E11 is now **PASS / COMPLETE** (PR #31 merged). E13 Proposal / Master Plan Editor is **PASS / COMPLETE** (PR #34 merged). See `docs/PROTEUS_E2X_P6_BASELINE_MANIFEST.md` §11 for current authority.
