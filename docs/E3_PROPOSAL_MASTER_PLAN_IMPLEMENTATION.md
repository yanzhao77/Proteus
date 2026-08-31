# E3 Proposal / Master Plan Implementation

## 1. Implementation Verdict

E3 is implemented as a **server-side deterministic, pre-approval-only authority**. It compiles current creator-scoped E1 Draft and E2 READY Understanding facts into immutable Proposal and Master Plan revisions. It performs no model/provider call and does not enter E4.

## 2. Exact Implementation Files

| Area | Files |
| --- | --- |
| Domain/compiler | `domain/entry_proposal_master_plan.py` |
| Application contract | `application/entry_proposal_master_plan_api.py` |
| PostgreSQL authority | `infrastructure/postgres_entry_proposal_master_plan.py`; `migrations/0029_e3_proposal_master_plan.sql` |
| Runtime composition | `api_main.py`; `application/product_api.py`; `infrastructure/fastapi_app.py` |
| Frontend | `frontend/src/models.ts`; `frontend/src/api/productApiAdapters.ts`; `frontend/src/api/adapters.ts`; `frontend/src/api/fixtureAdapters.ts`; `frontend/src/App.tsx` |
| Tests | E3 domain, Product API, FastAPI and frontend adapter test files |

## 3. Domain and Compiler

The E3 domain defines typed `ProposalSource`, `SourceClarification`, `SourceAssumption`, `ProposalCandidate` and `MasterPlanCandidate` inputs/outputs. `ProposalCompiler` is represented by `compile_proposal` with identifier `proposal-compiler-v1`; `MasterPlanCompiler` is represented by `compile_master_plan` with identifier `master-plan-compiler-v1`. Both use schema `e3-v1`.

Canonical content is normalized recursively and encoded as compact UTF-8 JSON with stable mapping key ordering. SHA-256 hashes cover canonical review content and source identity while excluding database identity, command identity and timestamps. Proposal compilation rejects a non-SUBMITTED Draft, non-READY Understanding, stale source revision, empty objective/requirements and OPEN clarification. Assumptions are output with `UNCONFIRMED_SOURCE_ASSUMPTION`, never as accepted facts.

Master Plan compilation rejects unresolved review items and validates non-empty goals, unique node keys, valid dependency endpoints, no self-dependency, DAG acyclicity, requirement coverage, verification coverage and forbidden runtime identity terms. The output is explicitly marked `pre_approval_only` and contains no Project/Task/Execution/P6 identity.

## 4. PostgreSQL Authority and Migration

`0029_e3_proposal_master_plan.sql` is the only E3 migration. It creates the independent E3 tables `entry_proposals`, `entry_proposal_revisions`, `entry_master_plans`, `entry_master_plan_revisions` and `entry_proposal_plan_command_receipts`.

Proposal and Master Plan revisions are append-only and protected by separate immutable triggers. The store locks creator-scoped E1/E2 source aggregates, verifies current revision identity and rechecks expected aggregate version before write. It persists source attribution, compiler/schema values, canonical content and hash. A unique durable receipt key over actor, command and idempotency key implements successful replay and fingerprint conflicts. The store contains only E1/E2/E3 SQL and has no Project/P6 DML.

## 5. Product API, FastAPI and OIDC

The Product API receives a new explicit E3 allowlist under the existing Draft route family. It supports only current/history read and deterministic mutation routes for `/proposal` and `/proposal/master-plan`. E3 mutations require the existing verified OIDC subject gate plus `reason`, `idempotency_key` and `expected_version`; unknown fields reject before authority invocation. The body actor cannot override `identity.subject`.

FastAPI registers only the six E3 read/mutation routes. It maps E3 validation/readiness/domain failures to 422, stale/version/idempotency conflicts to 409, no-leak unavailable results to existing availability semantics, and unavailable authority to 503. There is no approve route, generic mutation route or E4 wiring.

## 6. Frontend Delivery

The existing `ProductionDraftApi` and production `productApiAdapters` now expose typed Proposal and Master Plan read/generate methods. The Draft Workspace renders compact, source-derived Proposal and Plan panels with empty/loading/error/replay/conflict-compatible adapter states, current revision/hash/source metadata, assumptions marked honestly, review-required status and minimal revision count visibility.

The Master Plan panel says it is a pre-approval review artifact and explicitly states that E4 is not implemented. No Approve, Start Production, Project, Worker, provider, localStorage authority or fixture success is added. Pending and development-fixture adapters expose fail-closed E3 methods only to preserve type contract safety.

## 7. Stable Error Codes

| Family | Codes implemented |
| --- | --- |
| Proposal | `ENTRY_PROPOSAL_NOT_AVAILABLE`, `ENTRY_PROPOSAL_SOURCE_NOT_READY`, `ENTRY_PROPOSAL_SOURCE_STALE`, `ENTRY_PROPOSAL_VERSION_CONFLICT`, `ENTRY_PROPOSAL_IDEMPOTENCY_CONFLICT`, `ENTRY_PROPOSAL_SCHEMA_INVALID`, `ENTRY_PROPOSAL_COMPILER_FAILED`, `ENTRY_PROPOSAL_AUTHORITY_UNAVAILABLE` |
| Master Plan | `ENTRY_PLAN_NOT_AVAILABLE`, `ENTRY_PLAN_SOURCE_NOT_READY`, `ENTRY_PLAN_SOURCE_STALE`, `ENTRY_PLAN_VERSION_CONFLICT`, `ENTRY_PLAN_IDEMPOTENCY_CONFLICT`, `ENTRY_PLAN_SCHEMA_INVALID`, `ENTRY_PLAN_DOMAIN_INVALID`, `ENTRY_PLAN_DAG_INVALID`, `ENTRY_PLAN_REQUIREMENT_COVERAGE_INVALID`, `ENTRY_PLAN_COMPILER_FAILED`, `ENTRY_PLAN_AUTHORITY_UNAVAILABLE` |

## 8. Runtime Composition and Protected Paths

`api_main` composes the real `PostgresEntryProposalMasterPlanStore` only when the existing database and OIDC verifier are configured; otherwise `UnavailableEntryProposalMasterPlanApi` fails closed. No provider configuration, Docker topology, E2.x smoke runner, E1/E2 migration, Project, P6 runtime, Recovery, scheduler, worker, verifier or Human Gate transition authority changed.

## 9. Deviations from the Initial Design

There is no semantic deviation. The `ProposalCompiler` and `MasterPlanCompiler` are functions rather than stateful classes, matching the repository’s lightweight Python domain convention. The E3 persistence runner used a temporary Python/psycopg installation inside a disposable local PostgreSQL test container because host-side access would require inspecting a prohibited DSN. This did not modify repository dependencies, Compose configuration or application images.


## Final Acceptance Update

This document is an E3 delivery artifact. Final acceptance completed at `2026-08-20T06:37:49Z` on base `0b79573e7e4d94e443cbfcb37c32ef463eb7d4b8`: formal PostgreSQL authority tests, P6 focused suites, fresh migration, Full Runtime and frontend verification passed. The sole repository-wide current verification authority is `docs/PROTEUS_E2X_P6_BASELINE_MANIFEST.md`; E3 is **PASS / COMPLETE**, E4 is **PASS / COMPLETE**.
