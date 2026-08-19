# E1 EntryDraft Core Delivery Report

**Status:** **COMPLETE**

E1 establishes the first authority-backed, creator-scoped software-production intent object. It stops at `Human Idea → EntryDraft → Revision`; it does not create a Project, Production, Task, Execution, Worker, Scheduler, Verifier, Gate transition, Plan, Approval Bridge, progress or P6 runtime fact.

## 1. Recon Findings

The repository already supplies OIDC `VerifiedIdentity`, the `ProductApiFacade`, semantic route allowlisting, PostgreSQL transaction access, append-only/immutable record triggers, actor attribution, Project version conflict semantics and durable Project command receipts. There was no EntryDraft entity, revision authority, creator scope, Draft read projection or frontend Draft product API implementation. The E1 solution reuses the existing architectural shapes but does not overload Project/P6 authority.

## 2. Architecture

```text
Browser
  → Product API /production-drafts semantic route
  → OIDC bearer verification
  → verified subject == user actor assertion
  → ProductApiFacade
  → PostgresEntryDraftStore transaction
  → EntryDraft authority + revision/transition/receipt persistence
  → creator-scoped Draft read projection
  → Product API response
  → typed frontend ProductApiDrafts adapter
```

Every Draft operation uses verified subject ownership. Draft IDs supplied by a browser do not grant authority. A different creator receives `ENTRY_DRAFT_NOT_AVAILABLE` or a `NOT_AVAILABLE` read envelope without existence, title, state, version or revision leakage.

## 3. Domain Model

| Object | Role | Key fields |
| --- | --- | --- |
| `EntryDraft` | Current independent pre-Production authority state. | ID, creator subject, title, raw input, state, version, latest revision, command ID, timestamps. |
| `EntryDraftRevision` | Immutable append-only content history. | Revision ID/number, title, raw input, creator, Draft version, timestamp. |
| `EntryDraftTransitionRecord` | Immutable lifecycle audit. | Draft/command IDs, previous/new state, version, actor, reason, idempotency key, timestamp. |
| `EntryDraftCommandReceipt` | Persistent E1 idempotency/replay record. | Creator, command type, idempotency key, request hash, applied/rejected status and server result. |

## 4. State Machine

| Current state | Allowed E1 transitions | Notes |
| --- | --- | --- |
| `DRAFT` | `SUBMITTED`, `ARCHIVED` | Revision append is allowed only while `DRAFT`. |
| `SUBMITTED` | `ARCHIVED` | E1 does not infer Understanding, Proposal or Approval. |
| `ARCHIVED` | None | Terminal. No restore authority exists. |

The initial creation transition `NULL → DRAFT` is recorded. Every valid lifecycle transition increments the Draft version. A revision also increments Draft version and revision number, while the old revision remains immutable.

## 5. Database Changes

Only one new migration exists: `hermes-runtime/migrations/0025_e1_entry_draft_core.sql`. It creates `entry_drafts`, `entry_draft_revisions`, `entry_draft_transition_records` and `entry_draft_command_receipts`; includes primary/foreign keys, creator/update indexes, lifecycle/version checks, unique revision and idempotency constraints, immutable revision/transition triggers, and least-privilege grants. No existing Project, Gate, Execution, Worker, Scheduler, P6 or migration schema was edited.

## 6. API Contract

| Route | Method | Authority semantics |
| --- | --- | --- |
| `/production-drafts` | `POST` | Creates creator-owned `DRAFT`; requires title, raw input, reason and idempotency key. |
| `/production-drafts` | `GET` | Returns only the verified creator’s source-derived Draft list. |
| `/production-drafts/{id}` | `GET` | Returns creator-scoped Draft detail and immutable revisions, or `NOT_AVAILABLE`. |
| `/production-drafts/{id}/revisions` | `POST` | Appends revision only for current `DRAFT`, with expected version. |
| `/production-drafts/{id}/submit` | `POST` | Applies `DRAFT → SUBMITTED` only with expected version. |
| `/production-drafts/{id}/archive` | `POST` | Applies `DRAFT/SUBMITTED → ARCHIVED` only with expected version. |
| `/factory-home/drafts` | `GET` | Now delegates to the real creator-scoped Draft list. |

All routes remain within `ProductApiFacade`; there is no generic SQL, generic command or direct Python authority route.

## 7. Identity and Authorization

Factory/Draft endpoints use the existing OIDC verifier. Missing/invalid bearer authentication fails before Draft authority. The verified JWT subject must equal the user actor; a conflicting browser `X-Hermes-Actor-*` header is rejected. `PostgresEntryDraftStore` predicates every list/detail/mutation on `creator_subject = verified subject`; it never accepts a browser-provided creator, Project ID or local-storage identity.

## 8. Revision, Idempotency and Concurrency

Revisions are append-only and protected by an immutable trigger. E1 has no in-memory idempotency: the same `(creator_subject, command_type, idempotency_key, request_hash)` replays the server result, while reusing the key with a different fingerprint returns `ENTRY_DRAFT_IDEMPOTENCY_CONFLICT`. Mutations require the current `expected_version`; stale requests return `ENTRY_DRAFT_VERSION_CONFLICT` and cannot silently overwrite Draft state.

## 9. Frontend Integration

The independent React frontend reuses `ProductionDraftApi` and `productApiAdapters`; no second fetch layer or direct authority call was added. `/new` accepts title and raw idea, sends a command with an idempotency key and navigates only after a server-returned Draft. `/drafts` displays only server-returned creator-scoped records. `/drafts/:id` remains read-driven. DEV fixtures remain DEV-only and now explicitly refuse every Draft mutation; production bundles cannot select fixture adapters.

## 10. Files Changed

| Path | Change |
| --- | --- |
| `hermes-runtime/migrations/0025_e1_entry_draft_core.sql` | New E1-only database migration. |
| `hermes-runtime/src/hermes_runtime/domain/entry_draft.py` | E1 state and transition rules. |
| `hermes-runtime/src/hermes_runtime/infrastructure/postgres_entry_draft.py` | Transactional authority, read projection, revisions, receipts and scope predicate. |
| `hermes-runtime/src/hermes_runtime/application/entry_draft_api.py` | E1 API protocol/unavailable fallback. |
| `hermes-runtime/src/hermes_runtime/application/product_api.py` | Allowlisted semantic Draft GET/POST routes. |
| `hermes-runtime/src/hermes_runtime/infrastructure/fastapi_app.py` | OIDC-gated Draft HTTP transport and safe error mapping. |
| `hermes-runtime/src/hermes_runtime/api_main.py` | E1 store composition behind existing DB + OIDC fail-closed bootstrap. |
| `hermes-runtime/tests/test_entry_draft_core.py` | PostgreSQL authority/API no-leak coverage. |
| `frontend/src/models.ts`, `frontend/src/api/*`, `frontend/src/App.tsx` | Real Draft adapter/types and truthful `/new`, `/drafts`, `/drafts/:id` behavior. |

## 11. Verification

| Check | Result |
| --- | --- |
| E1 PostgreSQL authority/API integration | **PASS — 6 tests.** Covers create/read/scope, immutable revision, idempotent replay/conflict, optimistic conflict, lifecycle/archive rejection, Product API creator/no-leak contract. |
| E1 + FH-1/FH-1.x/FastAPI/OIDC/Product API/Workspace focused backend suite | **PASS — 41 tests.** |
| Frontend Vitest | **PASS — 33 tests.** |
| Frontend production build | **PASS.** |
| Frontend lint | **PASS — 0 warnings / 0 errors.** |
| P6 standalone autonomous production acceptance | **PASS — 1 test, 90.677 s.** |
| `git diff --check` | **PASS.** |
| Protected path diff | **PASS — no trial/P6 acceptance/P6 evidence/P6 report change.** |

The P6 run emitted two existing `ResourceWarning` notices involving `trial/harness.py` runner output file handles. The unchanged acceptance test passed and no P6 file was touched.

## 12. Known Limitations

Creator-only Draft visibility is deliberately not general RBAC, collaboration, administrator access or Project membership. E1 does not produce Understanding, Clarification, Proposal, Master Plan, Approval, Project, Production or runtime facts. Real browser bearer-token acquisition is still a deployment/identity-shell responsibility; React remains a consumer of the Product API, not an identity authority.

## 13. Recommended Next Phase

Proceed to **E2 Entry Understanding** only after an explicit authority design for understanding output, clarification and assumption facts. Do not start Approval Bridge, Project creation, mutation beyond E1 lifecycle or Live Production Workspace from E1 alone.
