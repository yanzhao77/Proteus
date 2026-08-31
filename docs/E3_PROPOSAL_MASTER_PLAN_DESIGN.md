# E3 Proposal / Master Plan Design

> **Scope:** E3 deterministically compiles existing creator-scoped E1/E2 authority facts into immutable, reviewable Proposal and Master Plan revisions. It ends before approval. **E4 is not entered.**

## 1. Authority Diagram

```text
verified OIDC subject
  │
  ├── EntryDraft current immutable revision (E1)
  └── READY EntryUnderstanding current immutable revision (E2)
           │
           ▼
  deterministic ProposalCompiler v1
           │
           ▼
  EntryProposal + immutable EntryProposalRevision
           │
           ▼
  deterministic MasterPlanCompiler v1
           │
           ▼
  EntryMasterPlan + immutable EntryMasterPlanRevision
           │
           └── review only; no approval, Project, Task, GraphPatch, VerificationPlan,
               ExecutionRequest, Worker, Scheduler, Human Gate, P6 or provider call
```

The only mutation actor is the verified OIDC subject. Product API actor headers/body are not a creator authority. E3 reuses `/production-drafts/{draft_id}` as a creator-scoped route family but implements no generic mutation endpoint and no approval route.

## 2. Typed Contracts

### Proposal revision canonical content

| Field group | Typed content |
| --- | --- |
| Statement and outcome | `product_statement`, `target_outcome` non-empty strings from E2 interpreted intent/objective |
| Scope | sorted `scope_in`, `scope_out` strings; unknown scope is an explicit review-required item |
| Requirements | source-attributed requirement objects (`key`, `statement`, `source`) |
| Source records | clarification answers with explicit `OPEN`/`ANSWERED` state and assumptions with `UNCONFIRMED_SOURCE_ASSUMPTION` status |
| Design | candidate architecture, phases, workforce/verification/delivery intents, complexity band, risks, unresolved items |
| Provenance | source Draft revision ID, source Understanding revision ID, source clarification/assumption IDs, compiler and schema version |

### Master Plan revision canonical content

| Field group | Typed content |
| --- | --- |
| Goal and constraints | goal, source-attributed requirements, constraints and architecture |
| Phases/nodes | ordered phases and typed nodes with stable keys, phase, requirement refs and verification refs |
| Dependencies | sorted explicit dependency edges with source/target keys |
| Intents | verification, delivery and workforce intents; workforce is advisory and never an allocated Worker |
| Provenance | Proposal revision/hash and source Draft/Understanding revisions, compiler/schema identifiers |

All payloads are parsed into dataclasses and strictly reject missing/invalid types. No unvalidated mapping is written to PostgreSQL.

## 3. Determinism and Content Hash

`canonical_json(value)` uses recursive normalized values, lexicographically ordered mapping keys, explicitly sorted unordered lists, compact UTF-8 JSON separators, and SHA-256. Content hashes include only reviewable canonical content and source identity. They deliberately exclude generated timestamps, database IDs, request IDs and command IDs.

`ProposalCompiler` and `MasterPlanCompiler` have no injected provider, no network dependency and no nondeterministic clock/UUID input. Stable compiler identifiers are `proposal-compiler-v1` and `master-plan-compiler-v1`; schema identifier is `e3-v1`.

## 4. Readiness, Validation and Freshness

Proposal creation requires a creator-owned `SUBMITTED` Draft with current revision plus a same-Draft, same-creator `READY` Understanding whose latest revision points to that current Draft revision. Any `OPEN` clarification, missing/foreign source, stale revision, archived/unsubmitted Draft or `NEEDS_CLARIFICATION` Understanding fails closed.

Plan creation requires a current creator-owned Proposal revision that remains tied to the current Draft/Understanding revision identities. The compiler validates a non-empty goal, unique node keys, valid references, no self-dependency, acyclic DAG, requirement coverage and valid verification references. No Project/Task/Execution identity may occur in canonical output.

At write time the PostgreSQL store locks source aggregate rows, rechecks latest revision identities and checks expected aggregate version. Old immutable revisions remain readable but cannot produce a current child revision once source freshness changes.

## 5. Revision, Idempotency and Concurrency

Each aggregate has an incrementing version and immutable numbered revisions. A durable E3 receipt has `(actor_subject, command_type, idempotency_key)` uniqueness, a request fingerprint, result payload/error code and status.

| Condition | Result |
| --- | --- |
| Same actor/key/command/fingerprint | return recorded result; no new revision |
| Same actor/key/command, different fingerprint | stable idempotency conflict |
| Expected aggregate version mismatch | stable version conflict |
| Concurrent duplicate delivery | uniqueness/row locks permit at most one logical revision |
| Compiler/readiness failure | persist safe failed receipt without creating Proposal/Plan revision |

## 6. PostgreSQL Schema and Least Privilege

Migration `0029_e3_proposal_master_plan.sql` adds only `entry_proposals`, `entry_proposal_revisions`, `entry_master_plans`, `entry_master_plan_revisions` and `entry_proposal_plan_command_receipts`, their indexes and immutable triggers. The control-plane runtime has only the E3 write permissions it needs; the read-only runtime receives only SELECT; P6/recovery roles receive no direct E3 mutation grant. The migration does not alter migrations `0001`–`0028` or Project/P6 authority.

## 7. API, OIDC and Error Matrix

| Route | Method | Result |
| --- | --- | --- |
| `/production-drafts/{draft_id}/proposal` | GET/POST | current/history-safe Proposal read or deterministic generation |
| `/production-drafts/{draft_id}/proposal/revisions` | GET | Proposal revision history |
| `/production-drafts/{draft_id}/proposal/master-plan` | GET/POST | current/history-safe Master Plan read or deterministic generation |
| `/production-drafts/{draft_id}/proposal/master-plan/revisions` | GET | Master Plan revision history |

Mutations accept only `reason`, `idempotency_key`, `expected_version`; unknown fields reject. Readiness/domain/schema failures map to 422, stale/version/idempotency conflicts to 409, unavailable authority to 503, no-leak unavailable reads to existing availability semantics, and unexpected errors to a safe 500 envelope. Stable code families are `ENTRY_PROPOSAL_*` and `ENTRY_PLAN_*`.

## 8. Frontend Boundary

The Draft Workspace receives typed Proposal/Master Plan read/mutation methods through the existing production `productApiAdapters`. It renders real API states: empty, loading, error, conflict/replay, current revision and minimal history. The Plan panel explicitly labels the result as a **pre-approval review artifact** and renders no Approve, Start Production, Project, Worker or provider control. No fixture authority state, localStorage authority or direct browser provider call is introduced.

## 9. E4 Handoff Boundary

The Master Plan typed payload intentionally has enough stable nodes, dependencies, requirements and verification intent for a future E4 lowering process. This E3 code does not import, call, or materialize GraphPatch/VerificationPlan/Project authority. An E4 implementation must use a separate approved command and separate authority review.

## 10. Test Strategy

Focused tests cover compiler canonicalization/hash, typed validation/DAG/coverage, E3 store revisions/receipts/conflicts/freshness/no-leak, Product API/FastAPI/OIDC envelopes, frontend states/request shapes and static/dynamic absence of Project/P6 effects. Full regression and fresh migration are recorded separately; no E2.x provider smoke is ever rerun.


## Final Acceptance Update

This document is an E3 delivery artifact. Final acceptance completed at `2026-08-20T06:37:49Z` on base `0b79573e7e4d94e443cbfcb37c32ef463eb7d4b8`: formal PostgreSQL authority tests, P6 focused suites, fresh migration, Full Runtime and frontend verification passed. The sole repository-wide current verification authority is `docs/PROTEUS_E2X_P6_BASELINE_MANIFEST.md`; E3 is **PASS / COMPLETE**, E4 is **PASS / COMPLETE**.
