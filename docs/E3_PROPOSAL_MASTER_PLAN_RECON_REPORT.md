# E3 Proposal / Master Plan Authority Recon Report

> **Recon verdict: CONTINUE.** The current `master` baseline contains no Proposal or Master Plan authority and exposes no E3 mutation surface. E3 can therefore be introduced as an independent, pre-approval aggregate without changing E1/E2 invariants, P6 authority, or entering E4.

## 1. Baseline and Authority Chain

The clean E3 worktree is based on `origin/master` commit `0370e4644a625e097751cf980ef6092e5db2a8e1`, which is the merge commit of PR #15 and has PR #14 merge commit `482eee6b85850c49285e004d7a23a9a7e1a5d7d9` as a parent. The authoritative baseline manifest records E1 and E2 as passed, E2.x Live Provider Verification as **PASS — NON-PRODUCTION**, P6 Authority Gate as **CLOSED**, P6 Functional Revalidation as **PASS**, and E3/E4 as **NOT ENTERED**.

The permitted source chain is strictly:

```text
creator-owned EntryDraft current revision
  → authoritative READY EntryUnderstanding current revision
  → immutable EntryProposal revision
  → immutable EntryMasterPlan revision
  → STOP (E4 not entered)
```

No E3 code may write or invoke Project, Task/DAG, ExecutionRequest, Worker, Scheduler, Verifier, Human Gate, `planning_runs`, `candidate_actions`, GraphPatch, or VerificationPlan authority.

## 2. Existing Findings

| Recon question | Finding | E3 consequence |
| --- | --- | --- |
| Proposal authority exists? | No repository E3 Proposal aggregate, persistence table, API route, or frontend adapter exists. | Create an independent E3-local Proposal aggregate. |
| Master Plan authority exists? | No E3 Master Plan aggregate exists. Existing planner terms belong to protected P6/runtime code. | Create a separate E3-local Master Plan aggregate; do not reuse P6 planning. |
| E2 authoritative revision schema | `entry_understanding_revisions` has source Draft identity/revision number, interpreted intent, objective, constraints, requirements, ambiguities, open questions, confidence, and provenance. | Compiler reads the current revision only and attributes both source revision IDs. |
| E2 readiness | `READY` and `NEEDS_CLARIFICATION` are real states. Clarifications are stored as `OPEN`; answers are immutable append-only records and do not establish user acceptance. | Proposal accepts only READY Understanding with no open clarification; answered data remains source-attributed, not accepted by implication. |
| Assumptions | Assumptions have statement/basis/source revision but no accept/change transition model. | E3 emits them as `UNCONFIRMED_SOURCE_ASSUMPTION`, never as accepted facts. |
| Source freshness | E1 Draft and E2 Understanding have aggregate version plus immutable numbered revisions. | Store locks the creator-scoped source rows and requires latest source revision identities at write time. |
| Creator/OIDC | Product API requires verified OIDC subject and actor identity equality for E1/E2. | E3 reuses the same verified-subject gate; browser actor/creator fields are ignored. |
| Receipt pattern | E1/E2 use durable command receipt tables keyed by actor, command and idempotency key. | E3 adds an independent receipt table with fingerprint conflict/replay behavior. |
| Existing Project/Graph ports | Project/Graph/Verification and P6 planners are independent protected authorities. | Read-only Recon only; E3 must not import or invoke them. |

## 3. Reuse / Do Not Reuse Matrix

| Reuse | Do not reuse |
| --- | --- |
| E1 creator scope, immutable revision, expected-version, receipt and no-leak conventions | P6 planner, `planning_runs`, candidate actions, recovery runtime, scheduler, worker, execution, Human Gate and trial code |
| E2 current READY Understanding facts, clarification answers and assumptions as source-attributed input | E2 external provider or OpenAI-compatible adapter; E3 is deterministic and has no network/provider dependency |
| Product API facade, FastAPI verified dispatch, OIDC verifier and safe error envelope | Project/Task/Graph/Verification authority, E4 approval semantics or production binding |
| PostgreSQL connection/configuration and append-only trigger/grant patterns | Generic browser fetch clients, fixture authority state, localStorage authority, provider browser access |

## 4. State and Revision Model

E3 uses two independent creator-scoped aggregates linked one-to-one by source chain:

| Aggregate | Stable identity | Immutable revision | Currentness basis |
| --- | --- | --- | --- |
| `EntryProposal` | one per Draft/creator | `EntryProposalRevision` | latest revision number and current Draft/Understanding source identities |
| `EntryMasterPlan` | one per Proposal/creator | `EntryMasterPlanRevision` | latest revision number and current Proposal/source identities |

Both revisions persist typed canonical content, schema/compiler identifiers, source references, SHA-256 canonical content hash, and immutable provenance. Envelope timestamps, database IDs and request IDs are excluded from the content hash.

## 5. Migration Decision

Disk inspection confirms `0028_p6_recovery_runtime_least_privilege.sql` is the maximum migration. E3 therefore requires exactly one new migration: `0029_e3_proposal_master_plan.sql`.

The migration will create only E3 tables, immutable revision triggers, indexes and least-privilege grants to the existing control-plane/read-only runtime roles. It will not modify migrations `0001`–`0028`, Project/P6 tables, old grants, Docker topology or provider configuration.

## 6. API and Stable Errors

The E3 surface will extend only the existing `/production-drafts/{draft_id}` Product API family:

| Route | Purpose |
| --- | --- |
| `GET /proposal` and `GET /proposal/revisions` | creator-scoped current/read history |
| `POST /proposal` | deterministic create/regenerate Proposal |
| `GET /proposal/master-plan` and `GET /proposal/master-plan/revisions` | creator-scoped Plan read/history |
| `POST /proposal/master-plan` | deterministic create/regenerate Master Plan |

Mutations require verified creator identity, `reason`, `idempotency_key`, `expected_version`, and exact allowlisted fields. Readiness/schema/domain failures are 422; source/version/idempotency conflicts are 409; unavailable authority is 503; unknown errors are safely enveloped. Foreign or missing entities use no-leak availability results.

## 7. Security Risks and Controls

| Risk | Control |
| --- | --- |
| Browser actor spoofing | OIDC `identity.subject` is the sole actor source; actor headers/body cannot override it. |
| Stale source revision | Creator-scoped `FOR UPDATE` source verification during mutation; current revision IDs are persisted and rechecked. |
| Fake planning/approval | Compiler uses only deterministic transforms and explicit unavailable/review-required values. No E4 route or approval control exists. |
| Side effects into Project/P6 | New store queries only E1/E2 source and E3 tables; tests include static/DB negative proofs. |
| Hash instability | Canonical JSON sort/separator/UTF-8 SHA-256 rule; sorted collections and explicit typed schema. |
| Sensitive leakage | No provider call/config in E3; safe response filtering and scoped secret scans. |

## 8. Required Files

New implementation files are expected under `domain/entry_proposal_master_plan.py`, `application/entry_proposal_master_plan_api.py`, `infrastructure/postgres_entry_proposal_master_plan.py`, `migrations/0029_e3_proposal_master_plan.sql`, focused E3 tests, and the four required E3 documents.

Permitted integration modifications are limited to `application/product_api.py`, `infrastructure/fastapi_app.py`, `api_main.py`, and existing typed frontend models/adapters/Draft Workspace/tests. The baseline manifest will be updated only after all required verification passes.

## 9. Acceptance Plan and Stop Conditions

Acceptance requires deterministic compiler/hash tests; PostgreSQL append-only, replay, conflict, freshness, no-leak and rollback tests; Product API/FastAPI/OIDC tests; frontend contract/UI tests; migration bootstrap; P6 and Full Runtime regression; protected-path/no-secret audits; and an OPEN, unmerged feature PR.

Immediate stop is required if implementation needs an E1/E2 invariant change, migration `0001`–`0028` change, provider/OIDC secret access, E4 approval, Project/Task/VerificationPlan/P6 persistence, weakened identity/idempotency/no-leak behavior, an unresolvable protected-path regression, or inability to prove no Project/P6 side effect.

## 10. Recon Decision

**No authority conflict was found.** E3 may proceed as an independent deterministic, pre-approval-only authority with one new E3 migration and minimal integration extensions. E4 remains explicitly out of scope.


## Final Acceptance Update

This document is an E3 delivery artifact. Final acceptance completed at `2026-08-20T06:37:49Z` on base `0b79573e7e4d94e443cbfcb37c32ef463eb7d4b8`: formal PostgreSQL authority tests, P6 focused suites, fresh migration, Full Runtime and frontend verification passed. The sole repository-wide current verification authority is `docs/PROTEUS_E2X_P6_BASELINE_MANIFEST.md`; E3 is **PASS / COMPLETE**, E4 is **NOT ENTERED**.
