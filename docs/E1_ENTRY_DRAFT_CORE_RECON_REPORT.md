# E1 EntryDraft Core — Recon Report

**日期：** 2026-08-18
**结论：** E1 可以作为独立 Draft authority 实施；不得复用 Project authority，也不需要修改 P6 runtime。仓库已有 OIDC、Product API、SQL migration、command receipt、version、transition/audit 和 source-derived read model 的可复用模式，但没有 EntryDraft entity、Draft revision、Draft lifecycle、Draft scope、Draft idempotency 或 Draft frontend read/write contract。

## 1. Existing Authority Primitives

| Primitive | Existing implementation | E1 reuse decision |
| --- | --- | --- |
| Verified identity | `infrastructure/oidc.py`: `OidcTokenVerifier → VerifiedIdentity(subject, Actor(USER, subject))`. | Reuse unchanged for all Draft GET/mutation routes. |
| Browser trust boundary | FH-1.x Factory Home OIDC dispatch rejects missing/invalid bearer tokens and actor mismatch. | Reuse the same OIDC-only pattern; `X-Hermes-Actor-*` never grants Draft access. |
| Product API | `ProductApiRequest`, `ProductApiFacade`, safe response filtering, allowlisted semantic routes. | Extend the existing façade; do not create a second API protocol. |
| Actor attribution | Actor type/id flow and transition/audit records. | Persist verified subject as Draft creator/transition actor. |
| Optimistic concurrency | Project authority receives `expected_version` and rejects mismatches. | Reuse semantic rule and error shape for Draft mutation. |
| Idempotency | Project-scoped `command_receipts` stores command ID, idempotency key, request hash and result status. | Reuse the receipt semantics, but not Project-scoped table directly: Draft has no Project ID. Implement the smallest Draft-scoped persistent receipt table in the E1 migration. |
| Transition/audit | `project_transition_records` and `audit_records` patterns record prior/new state, actor, reason/version and append-only facts. | Create an E1 Draft transition record in the same SQL migration rather than overload Project records or add a global audit subsystem. |
| PostgreSQL infrastructure | Existing infrastructure modules use `psycopg`, transaction context, `dict_row`, prepared authoritative SQL. | Use the same connection/transaction style. |
| Source-derived read models | FH-1 `FactoryHomeReadModel`/Postgres adapter. | Keep Draft read model separate; Factory Home will consume a Draft summary only. |

## 2. Existing Persistence and Migration Primitives

The repository uses append-only, numbered SQL migrations. `0001_p0_completion_verification.sql` introduces `command_receipts`, `audit_records` and immutable event patterns; `0003_project_state_authority.sql` introduces `project_transition_records`. Migrations are the existing schema mechanism, so E1 may add exactly one new numbered migration for Draft-only tables, indexes, constraints and triggers. Existing Project, Gate, Execution, Worker, Scheduler and P6 tables/functions must remain untouched.

No suitable existing Draft/Proposal/Intent/Entry entity exists. P6 `SoftwareRequest` and planning/verification objects are runtime-specific and must not be repurposed as a user-owned pre-Production Draft.

## 3. Existing API Command Conventions

Mutations are semantic product commands, not generic CRUD. The convention carries actor attribution, idempotency key, expected version, request fingerprint/hash, validation, safe response envelope and no raw authority object exposure. E1 routes should therefore use the existing Product API façade with OIDC verified subject, exact command-specific validators and stable error codes.

## 4. Existing Identity and Scope Mechanism

FH-1.x established OIDC verified identity and fail-closed bootstrap. `PostgresCreatorActorProjectScope` is Project-specific and derives Project visibility from initial `project_transition_records`; Draft must **not** reuse that Project scope. Draft scope must be a separate creator predicate: `entry_drafts.creator_subject = VerifiedIdentity.subject`.

## 5. Existing Frontend Draft Contract

`frontend/src/models.ts` already declares `ProductionDraftApi`, `DraftViewModel` and command metadata. `productApiAdapters.ts` currently returns `NOT_IMPLEMENTED` for Draft operations; React routes already include `/new` and `/drafts/:id`, but `/drafts` listing and authentic, server-result-driven Draft states are incomplete. The frontend’s typed adapter boundary, DEV-only fixture isolation and “React is not authority” rules are reusable.

## 6. Missing Components

| Layer | Missing E1 component |
| --- | --- |
| Domain | `EntryDraft`, `EntryDraftRevision`, `EntryDraftState` and allowed transition rules. |
| Persistence | Draft tables, append-only revisions, append-only transitions and persistent Draft command receipts. |
| Authority | Transactional create/revise/submit/archive authority with version and creator checks. |
| Read model | Creator-scoped list/detail/revision projection. |
| API | OIDC-protected `POST/GET /production-drafts` semantic Product API routes. |
| Frontend | Real Draft adapter, `/new` submit/error/conflict UI, `/drafts` list and truthful detail/revision display. |
| Tests | Draft lifecycle, scope isolation, idempotency, conflict, no-leak and API/frontend contracts. |

## 7. Proposed E1 Boundaries

E1 implements only `DRAFT → SUBMITTED → ARCHIVED`, with direct `DRAFT → ARCHIVED` also allowed. `SUBMITTED → ARCHIVED` is allowed; `ARCHIVED` is terminal. There is no Understanding, Proposal, Plan, Approval, Project/Production, Task, Execution, Gate, Worker, Scheduler, Verifier, SSE, progress or telemetry authority.

Each mutation must use a verified OIDC subject, persistent idempotency receipt and expected version. A revision is append-only; old revisions never update. Responses must be creator scoped, source-derived, version-aware and include `as_of` / freshness fields without fabricated facts.

## 8. Protected Paths

E1 must not modify `hermes-runtime/src/hermes_runtime/trial/**`, `hermes-runtime/tests/test_p6_autonomous_trial.py`, `docs/P6_REPORT.md`, `docs/evidence/p6/**`, existing P6 migrations, Scheduler, Worker, Verifier, Execution authority or Gate transition logic. The only permitted migration is a new E1 Draft Core migration.

## 9. Recon Decision

Proceed with a new isolated EntryDraft authority and one E1 migration. The implementation will reuse OIDC verification, Product API envelope/command conventions, SQL transaction style, optimistic-version semantics and audit-transition shape; it will not overload existing Project/P6 authority. No current architectural conflict blocks E1.
