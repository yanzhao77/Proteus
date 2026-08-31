# E11 User Command Transport Authority Recon Report

> **Status:** `DESIGN-ONLY / IMPLEMENTATION NOT AUTHORIZED`
>
> **Authority conclusion:** E11 remains **PARTIAL / ACCEPTANCE GAP**. This report neither implements nor authorizes a user command transport.
>
> **Current status update (2026-08-31):** This document is a historical design artifact. E11 is now **PASS / COMPLETE** (PR #31 merged). E13 Proposal / Master Plan Editor is **PASS / COMPLETE** (PR #34 merged). See `docs/PROTEUS_E2X_P6_BASELINE_MANIFEST.md` §11 for current authority.

## 1. Scope and verified baseline

This report records a read-only audit of the authority boundaries relevant to a possible future E11 User Command Transport. The audit started from remote `master` commit `85af422a758b8483b2d82d525c5920eb5f8f4d2d`, the merge commit of PR #28. PR #28 has one changed file, `docs/PROTEUS_E2X_P6_BASELINE_MANIFEST.md`, and its merge ancestry is the verified status-correction baseline.

The checked manifest contains **211 non-self entries**, with **0 missing** and **0 mismatch** in the remote-master archive. Its sole current-status section declares E9 `PASS / ACCEPTANCE COMPLETE`, E11 `PARTIAL / ACCEPTANCE GAP`, E9–E11 Wave A `NOT COMPLETE`, and E12–E16 `NOT ENTERED`. An earlier E11 row is explicitly marked as a historical Wave A delivery snapshot rather than current acceptance authority.

| Baseline item | Observed result |
|---|---|
| Remote master | `85af422a758b8483b2d82d525c5920eb5f8f4d2d` |
| PR #28 | Merged; one manifest file only |
| Migration head | `0032_p6_execution_prepare_structured_secret_guard.sql` |
| E11 operational state | `PARTIAL / ACCEPTANCE GAP` |
| P6 authority state | Closed; unchanged by this design audit |
| Database evidence | `DATABASE EVIDENCE UNAVAILABLE` — no safe read-only catalog connection was available; no database was created or queried |

No Product API mutation, Project command, Recovery command, Gate decision, provider call, database write, migration, role/ACL change, or implementation test was executed.

## 2. Public Product API and HTTP inventory

The current FastAPI surface is concentrated in the session, health, read-model, human-gate, Factory Home, Live Production, and Production Draft families. Its complete decorator inventory was read from `hermes_runtime/infrastructure/fastapi_app.py`.[1]

| Surface family | Public routes | Classification | E11 authority finding |
|---|---|---|---|
| Session and health | `POST/GET/DELETE /session`, `GET /livez`, `GET /readyz` | Session / operational support | Not Project authority commands. |
| Project, decision and observations | `GET /projects/{project_id}/status`, `GET /decisions/{decision_id}/explain`, `GET /docker-processes/{process_id}/observations` | `READ_ONLY` | Returns existing facts only. |
| Reconcile findings | `GET /projects/{project_id}/reconcile-findings` | `READ_ONLY` | Replays finding/read-model evidence; it is not a reconcile authority command. |
| Human gate | `GET /human-gates/{gate_request_id}`, `POST /human-gates/{gate_request_id}/decisions` | Read-only plus `E12_ONLY` mutation | The decision route belongs to E12 and is prohibited as an E11 workaround. |
| Factory Home / Live Production | `GET /factory-home` and its productions, live, live-feed, gates, drafts and status variants | `READ_ONLY` | Creator-scoped source-derived projections. No pause, resume, retry, cancel, reverify or acknowledgement route exists. |
| Production Draft | Draft, revision, submit, archive, Understanding, clarification, Proposal, Master Plan and Approval routes | `USER_CALLABLE` only for E1–E4 semantics | Existing creator-scoped draft/approval workflow; not Project Operations transport. |
| UI HTML paths | `/home`, `/new`, `/drafts/{id}`, `/productions`, `/productions/{id}`, `/gates`, human-gate UI paths | Presentation | Do not establish authority beyond their backing API routes. |

The public facade dispatch confirms that `GET /projects/{project_id}/reconcile-findings` calls `replay_reconcile_findings`, while E4 approval reconciliation is a distinct Production Draft approval route. The latter must not be generalized as a Project reconcile command.[2]

### Mutation inventory

Existing public mutations are limited to Production Draft lifecycle, Understanding, clarification answer, Proposal, Master Plan, Approval, E4 approval reconciliation, session creation/deletion, and the E12 human-gate decision route. Production Draft mutations carry creator identity, expected-version and idempotency contracts in their own bounded workflow. They do not expose a creator-scoped Project Operations command.

Accordingly, the following E11 intents are currently **UNAVAILABLE** from the public Product API: Project retry, Project reconcile, Project reverify, permitted Project cancel, Project pause, Project resume, and acknowledge-resolved-incident. The absence is intentional from an authority perspective, not a UI omission.

## 3. Application, domain and Control Plane inventory

The repository contains `PauseProject`, `ResumeProject`, and `CancelProject` command types. Each includes a `CommandEnvelope` and a separate `requested_by` actor; cancel additionally carries an `authorization_ref`.[3] The envelope itself includes `command_id`, `command_type`, `idempotency_key`, `expected_version`, authoritative `actor`, `reason`, and `project_id`.

The Project handler is decisive: it requires `command.envelope.actor.actor_type == CONTROL_PLANE` before Project state is committed. It then validates `requested_by` against command-specific requester types. The relevant stable rejection codes include `CONTROL_PLANE_AUTHORITY_REQUIRED`, `PROJECT_REQUESTER_NOT_AUTHORIZED`, `COMMAND_REASON_REQUIRED`, `PROJECT_COMMAND_SEMANTICS_MISMATCH`, and `CANCELLATION_AUTHORIZATION_REQUIRED`.[4]

| Existing semantic handler | Authoritative executor | Requester treatment | Public Product API reachability | Recon classification |
|---|---|---|---|---|
| `create_project` | Control Plane envelope required | User, Main Hermes or Control Plane requesters are validated | Reached indirectly by existing E4 bridge, not by E11 transport | Existing authority primitive |
| `request_project_transition` | Control Plane envelope required | User, Main Hermes, Control Plane or Recovery Controller requesters are validated | No generic E11 public route | Existing authority primitive |
| `pause_project` | Control Plane envelope required | User, Main Hermes, Control Plane, Recovery Controller or System Operator requesters are validated | No public Project Operations mutation | Candidate only after separate implementation review |
| `resume_project` | Control Plane envelope required | Same bounded requester set as pause | No public Project Operations mutation | Candidate only after separate implementation review |
| `cancel_project` | Control Plane envelope required | User or System Operator requester; verified authorization reference also required | No public Project Operations mutation | Candidate only after separate implementation review |
| Task verification / work graph transitions | Control Plane envelope required | Separate task-level semantics | No E11 public route | Not a direct substitute for Project Operations |
| Recovery/replay/reconcile primitives | Runtime-specific or recovery-specific authority | Not creator-scoped Product API capability | No public E11 semantic route | Not a direct substitute |

This existing separation supports a future **requested-by / executed-by** chain. It does **not** permit a browser, OIDC actor, API role, or frontend to become `CONTROL_PLANE`.

## 4. Receipt, idempotency, version, event and projection evidence

The static Project store implementation contains command-hash, receipt-claim, receipt-completion, rejection-persistence, expected-version checking, and event/outbox append primitives. The project migrations record authoritative actor and requester fields separately in immutable `project_transition_records`.[5] Static migration evidence also shows receipt and idempotency mechanisms in the runtime schema, including unique project/idempotency constraints for the execution path.[6]

E7 projections are creator-scoped. Static read-model and test evidence shows bounded live feeds, snapshot watermarks, cursor-ahead and cursor-expired stale responses, and project-ID probing that fails closed for an unscoped identity.[7] A future transport must therefore treat a receipt or event as intermediate evidence only; it must wait for authority application and projection reconciliation before presenting an applied UI state.

## 5. Static role and function evidence; catalog limitation

Static migrations define and harden runtime roles, owners, security-definer functions, grants, revocations and `search_path` settings. For example, execution migrations introduce owner/runtime roles, execution receipt references and hardened security-definer functions; recovery migrations later narrow recovery runtime write privilege while preserving the owner-mediated recovery path.[6] Project transition migrations also revoke public table access and preserve actor/requester columns in immutable records.[5]

This is **source-level evidence only**. No safe live PostgreSQL catalog connection, DSN, or allowable container was present. Therefore this report does not claim observed `pg_proc`, `pg_roles`, ACL, owner, `prosecdef`, or `proconfig` values in a running database. Catalog verification remains a mandatory implementation prerequisite.

## 6. Recon result and non-actions

The evidence supports a future design in which a verified OIDC creator can request a bounded command, while a trusted Control Plane identity remains the only authoritative executor. It does not support a direct browser-to-runtime path, a browser-selected creator scope, direct store access, direct DML, a hidden E12 Gate decision, or a second independent authority broker.

This recon performed no implementation. It does not make E11 complete, does not expose a user command, and claims no implementation-test result.

## References

[1]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/src/hermes_runtime/infrastructure/fastapi_app.py
[2]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/src/hermes_runtime/application/product_api.py
[3]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/src/hermes_runtime/application/commands.py
[4]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/src/hermes_runtime/application/handlers.py
[5]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/migrations/0003_project_state_authority.sql
[6]: https://github.com/yanzhao77/Proteus/tree/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/migrations
[7]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/src/hermes_runtime/infrastructure/postgres_live_production_read_model.py
