# E2 Entry Understanding — Recon Report

**日期：** 2026-08-18
**结论：** E2 需要新增独立的 Understanding authority、revision、clarification、assumption、generation receipt 与 producer adapter。E1 的 Draft、OIDC、Product API、PostgreSQL transaction、append-only record、idempotency、expected-version 和 frontend adapter patterns 可以复用；Project authority、Planner、Worker、Execution、Verifier、Human Gate 与 P6 runtime 明确不能复用。

## 1. Answers to Mandatory Recon Questions

| Question | Result | Evidence-based reuse decision |
| --- | --- | --- |
| A. Existing Understanding authority? | **No.** No `EntryUnderstanding` persistence, domain, API or read model exists. | Must create independent E2 authority. |
| B. Existing Clarification authority? | **No.** Human Gate exists but is approval/control-plane specific. | Do not reuse Human Gate for information-seeking clarification. Create E2 clarification authority. |
| C. Existing Assumption authority? | **No.** Situation, risk and planning facts are runtime/controller concepts. | Create a small E2 assumption relation, not a Project risk/plan fact. |
| D. Existing AI inference abstraction? | **No production entry-inference provider exists.** The repository contains planning/agent/worker abstractions for Control Plane runtime, not a generic LLM provider, prompt client or structured-entry producer. | Introduce a narrow E2 `UnderstandingProducer` protocol and a deterministic test producer. No live provider or secret/config integration is required in E2. |
| E. Suitable persistent command receipt? | Existing `command_receipts` is Project-keyed; E1 added a Draft-scoped receipt pattern. | Reuse E1 receipt semantics in an E2 Understanding-scoped persistent receipt table; do not misuse Project receipt. |
| F. Suitable version/concurrency model? | Yes. E1 Draft version, expected version and conflict semantics are directly applicable. | Understanding state/revision mutations must compare expected version and reject stale requests. |
| G. Can E1 authority pattern be reused? | Yes for scope, transactions, immutable records, Product API and error discipline. | Reuse shape, not E1 Draft tables as an Understanding implementation. |
| H. Required new components? | E2 domain, state machine, schema validator, producer protocol, persistence, read projection, semantic API routes and frontend Understanding UI. | Add only E2-specific components. |
| I. Modules that cannot be reused? | Project, Planner, Worker, Scheduler, Execution, Verifier, Gate transition, P6 Trial and its evidence. | Protected and semantically incorrect for pre-Project user understanding. |

## 2. Existing Reusable Primitives

| Primitive | Current source | Why it is safe to reuse |
| --- | --- | --- |
| Verified identity | E1/FH-1.x OIDC verifier and `VerifiedIdentity.subject`. | Supplies a trusted creator subject and fail-closed browser boundary. |
| Creator scope | E1 `entry_drafts.creator_subject` predicate. | E2 can first prove Draft ownership, then scope all Understanding objects through the same verified creator and source Draft. |
| API envelope | `ProductApiRequest`, `ProductApiFacade`, safe response filtering, allowlisted semantic route dispatch. | E2 semantic routes can remain inside the existing Product API surface. |
| Transaction/persistence | PostgreSQL `psycopg` transaction convention and numbered SQL migrations. | Supports atomic receipt → authority → revision/clarification/assumption persistence. |
| Append-only pattern | E1 immutable Draft revision/transition triggers; existing immutable runtime record patterns. | Understanding revisions and clarification answers should be append-only. |
| Durable idempotency | E1 creator+command+key+request-hash receipt model. | Handles replay and fingerprint conflict without memory state. |
| Concurrency | E1 expected-version model. | Prevents concurrent regeneration/answer overwrites. |
| Frontend boundary | `ProductionDraftApi`, `productApiAdapters`, product adapter selection and DEV fixture disclosure. | E2 expands this adapter rather than adding React fetch/authority logic. |

## 3. Existing Modules Not Suitable for E2

The Control Plane Planner is a Project/DAG action-selection component, not an entry-intent interpreter. Runtime Worker/Execution/Verifier abstractions require execution and P6 lifecycle facts. Human Gate represents privileged pause/resume decisions and is not a clarification dialogue. Situation/risk/policy schemas are control-plane evidence; they must not be rebranded as user intent/assumptions. No existing structured LLM output abstraction or provider integration was discovered, so E2 must not pretend an existing agent can produce Understanding.

## 4. Proposed E2 Boundary

E2 consumes a creator-owned, non-archived EntryDraft and a specific immutable Draft revision. A command invokes a narrow `UnderstandingProducer`, validates a typed output, validates source attribution/domain invariants, then atomically persists E2 authority. Producer output has no direct database authority and cannot create Project/P6 objects.

The minimal proposed E2 objects are `EntryUnderstanding` current state, immutable `EntryUnderstandingRevision`, `EntryClarification`, immutable `EntryClarificationAnswer`, `EntryAssumption`, persistent `EntryUnderstandingCommandReceipt` and transition/audit records. These are E2-local because no existing entities carry their semantics safely.

## 5. Protected Paths

E2 must not modify `hermes-runtime/src/hermes_runtime/trial/**`, `hermes-runtime/tests/test_p6_autonomous_trial.py`, `docs/P6_REPORT.md`, `docs/evidence/p6/**`, Scheduler, Worker, Verifier, Execution authority, Gate transition authority or E1 migration. The only permissible schema change is one new E2 migration after the actual E1 migration number.

## 6. Recon Decision

Proceed only with a narrow E2 producer protocol plus deterministic test producer, structured schema/domain validation and isolated E2 persistence. A live LLM/provider is not currently an established repository capability; therefore model/provider metadata must remain `NOT_AVAILABLE` unless a producer truthfully provides it. No Project/Production/Task/Execution bridge may be added.
