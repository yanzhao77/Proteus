# E2 Entry Understanding Implementation V1

## Status

**PARTIAL.** E2 authority、source attribution、immutable revision、clarification、assumption、durable idempotency、optimistic concurrency、semantic Product API、OIDC boundary and frontend adapter are implemented and tested. The repository has no existing production LLM/inference provider; therefore the production bootstrap intentionally installs `UnavailableEntryUnderstandingApi`. A real browser/API deployment returns `NOT_IMPLEMENTED` rather than manufacturing an Understanding. This is the correct fail-closed state, not a successful live E2 producer.

## Architecture

```text
React Draft workspace
    → typed ProductionDraftApi
    → Product API semantic routes
    → OIDC verified identity + creator scope
    → PostgresEntryUnderstandingStore
    → UnderstandingProducer (injected producer only)
    → strict structured output validation
    → immutable E2 persistence
    → source-derived Product API projection
    → React
```

The producer cannot call Product API, database, Project authority or P6 runtime. The frontend cannot call a producer, Python authority or PostgreSQL. The default production composition provides no producer, so it fail-closes. The deterministic producer appears only in isolated E2 tests and is not a runtime fallback.

## Domain and Lifecycle

`EntryUnderstanding` is a distinct aggregate associated 1:1 with an E1 Draft. Its current state is `READY` or `NEEDS_CLARIFICATION`; a request-in-flight `GENERATING` state is rendered only as client command progress and is never persisted as a false server fact. Each successful generation creates a new immutable Understanding revision linked to the exact source Draft revision and raw input. Old revisions remain historical; no output is overwritten.

Generation is legal only for a verified creator’s E1 Draft in `SUBMITTED` state. An unsubmitted, archived or foreign Draft cannot produce Understanding. E2 does not change Draft state.

## Clarifications and Assumptions

Clarifications are independent E2 authority records with `OPEN` or `ANSWERED` state. An answer is append-only, then a new producer invocation must pass validation before a new Understanding revision is persisted. A clarification is not a Human Gate and cannot approve/reject a Project.

Assumptions are immutable rows linked to an Understanding revision. Explicit user requirements are retained in the immutable revision field `explicit_requirements`; they are not merged with assumptions. `provider_metadata` and `confidence` remain nullable and are never fabricated.

## Database

`0026_e2_entry_understanding.sql` is the sole E2 migration. It adds `entry_understandings`, immutable `entry_understanding_revisions`, `entry_clarifications`, immutable `entry_clarification_answers`, immutable `entry_understanding_assumptions`, immutable transition records and durable `entry_understanding_command_receipts`. It uses FK, check, unique, creator/scope index, version, append-only trigger and least-privilege patterns. No E1 migration or Project/P6 schema was edited.

## API

The only new semantic routes are:

| Route | Method | Result |
| --- | --- | --- |
| `/production-drafts/{id}/understanding` | `POST` | Generate/re-generate validated Understanding. |
| `/production-drafts/{id}/understanding` | `GET` | Read current source-derived Understanding. |
| `/production-drafts/{id}/understanding/revisions` | `GET` | Read immutable revision history. |
| `/production-drafts/{id}/understanding/clarifications` | `GET` | Read current clarification facts. |
| `/production-drafts/{id}/understanding/clarifications/{id}/answer` | `POST` | Append answer, validate producer output and create a new revision. |

All routes are allowlisted by `ProductApiFacade`, OIDC protected by existing FastAPI dispatch, creator scoped, typed and no-leak. There is no generic CRUD/SQL/command route.

## Identity, Idempotency and Concurrency

The verified OIDC subject must match the user actor. The store predicates every E2 access by creator and source Draft; a foreign Understanding is returned as `NOT_AVAILABLE` with `item: null`. Receipts key on creator, command, idempotency key and canonical request hash. Receipt lookup happens **before producer invocation** so a replay cannot invoke a second producer run. Changed payload under the same key conflicts. `expected_version` protects regeneration/answer writes from stale overwrites.

## Frontend

`ProductionDraftApi` now has typed `getUnderstanding`, `requestUnderstanding` and `answerClarification` methods. `/drafts/:id` reads original Draft plus E2 server projection, renders readiness/unavailable/error/generating command feedback, displays explicit requirements, ambiguities, assumptions, open questions and clarifications, and reloads from the server only after a successful command receipt. It does not use fixture Understanding data, local inference, client-side ownership or Project-plan terminology.

## Verification

| Check | Result |
| --- | --- |
| E2 PostgreSQL authority/API tests | **PASS — 6 tests.** |
| E2 + E1 + FH-1/FH-1.x + FastAPI/OIDC/Product API/Workspace focused backend suite | **PASS — 47 tests.** |
| Frontend Vitest | **PASS — 33 tests.** |
| Frontend build | **PASS.** |
| Frontend lint | **PASS — 0 warnings / 0 errors.** |
| P6 standalone autonomous acceptance | **PASS — 1 test, 92.508 seconds.** |
| `git diff --check` | **PASS.** |
| Protected paths | **PASS — no protected trial/P6 report/evidence path modifications.** |

The P6 run displayed two pre-existing runner output handle `ResourceWarning` notices but completed with `OK`; no P6 file was changed.

## Required Next Work

A future dedicated provider integration phase must introduce a trustworthy production producer configuration and secret/credential policy. It must not bypass E2 validation or insert LLM output directly. Until then, `api_main` remains intentionally `NOT_IMPLEMENTED` for live Understanding generation. E3 must not begin Proposal/Plan/Project behavior; the appropriate next semantic phase after provider integration is further Understanding/Clarification hardening only.
