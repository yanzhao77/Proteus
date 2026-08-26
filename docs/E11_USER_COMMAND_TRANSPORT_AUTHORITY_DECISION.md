# E11 User Command Transport Authority Decision

> **Decision:** `DESIGN APPROVED — IMPLEMENTATION MAY BE AUTHORIZED SEPARATELY`
>
> **Non-decision:** No transport, endpoint, migration, role, grant, function, UI action or authority change is authorized by this document.

## 1. Authority decision

A future E11 user-command capability should use a **bounded Trusted Control Plane Proxy** that invokes existing Project semantic handlers. It must preserve, rather than reinterpret, the repository’s current authority rule: the Control Plane executes Project state transitions, while a verified OIDC creator may be recorded as the requester only after server-side creator-scope validation.

The design is approved only in the limited architectural sense that the existing command envelope, `requested_by` field, Project handler checks, receipt primitives, event/outbox path and E7 creator-scoped projection provide a coherent direction. Production readiness and implementation authorization remain explicitly absent because live PostgreSQL catalog evidence was unavailable and no real implementation tests were run.

## 2. Required actor chain

| Identity | Source | Permitted responsibility | Forbidden responsibility |
|---|---|---|---|
| Verified OIDC creator | Server-side session verification | Express bounded intent; own target; supply reason, expected version and idempotency key | Become Control Plane; choose scope; direct-write runtime; select handler; create a receipt |
| Product API | Server-side service | Validate typed input, derive creator scope, normalize request hash, expose status | Call store/DML directly; substitute executor; bypass semantic handler |
| Trusted Control Plane proxy | Service-to-service trusted authority | Build existing semantic envelope with `CONTROL_PLANE` executor; invoke allow-listed handler | Execute arbitrary commands; accept browser actor/scope; act as a second independent authority |
| Existing Project handler | Existing domain/application authority | Enforce command type, Control Plane executor, requester type, reason and lifecycle semantics | Accept an unvalidated direct browser invocation |
| E7 projection | Existing read model | Reconcile applied state for the creator-scoped UI | Make an authority decision or overwrite state optimistically |

## 3. Command permission decision matrix

| Command | Creator request | Admin request | Control Plane execution | Gate requirement | Current design status | Forbidden direct path |
|---|---|---|---|---|---|---|
| Retry | Not approved | Not approved | No public E11 primitive | Command-specific if later defined | `UNAVAILABLE` | Reusing Recovery internals or a frontend retry button |
| Reconcile | Not approved | Not approved | Existing finding replay is read-only | Not applicable | `READ_ONLY` | Treating `GET /reconcile-findings` as mutation |
| Reverify | Not approved | Not approved | Existing task/verification authority only | Command-specific if later defined | `UNAVAILABLE` | Calling verifier/runtime from Product API |
| Permitted cancel | Conditional, owned target only | Separately defined policy | Required | Existing authorization reference; no E12 shortcut | `DESIGN CANDIDATE` | Browser creates `CancelProject` envelope |
| Pause | Conditional, owned target only | Separately defined policy | Required | No implicit Gate; explicit lifecycle policy | `DESIGN CANDIDATE` | Product API direct store call |
| Resume | Conditional, owned target only | Separately defined policy | Required | No implicit Gate; explicit lifecycle policy | `DESIGN CANDIDATE` | Browser or API role as Control Plane |
| Acknowledge resolved incident | Not approved | Not approved | No verified generic primitive | Command-specific if later defined | `UNAVAILABLE` | Inventing state from E7 evidence |

## 4. Error and status matrix

| Scenario | API status class | Stable error/status | Same-key retry | Authority side effect | Projection behavior | UI behavior |
|---|---|---|---|---|---|---|
| Valid creator, eligible target | Accepted/pending | `RECEIPT_ACCEPTED` or `AWAITING_AUTHORITY` | Reuse same key | Receipt first; execution pending | Poll/read snapshot | Show pending, not applied |
| Foreign creator / target not owned | Rejected/not available | Scope-safe stable code | No new key needed | None | No foreign facts | Show unavailable/denied |
| Missing/expired verified identity | Unauthorized | Identity stable code | No | None | None | Re-authenticate |
| Actor mismatch | Forbidden | `CONTROL_PLANE_AUTHORITY_REQUIRED` or actor-mismatch code | No | Rejection only per durable policy | None | Never retry as browser actor |
| Command not eligible / terminal | Conflict/rejected | Command eligibility/terminal code | Same key returns rejection | No transition | Refresh snapshot | Disable or explain unavailable action |
| Stale expected version | Conflict | Expected-version conflict | Corrected request needs new canonical body/key policy | None | Refresh source projection | Require user review |
| Same key, same body | Replay | Current receipt status | Yes, same key | No duplicate | Rehydrate status | Resume pending/applied/rejected state |
| Same key, different body | Conflict | Idempotency conflict | No | None | None | Require explicit new request |
| Authority rejected | Rejected | Sanitized authority code | Same key returns same receipt | No applied transition | Reconcile read model | Show rejected receipt |
| Authority applied, projection delayed | Pending/uncertain | `APPLIED` authority with stale projection | Same key status lookup | One transition only | Snapshot/feed reconciliation | Do not paint final state yet |
| Event cursor gap/reorder/restart | Stale/uncertain | Existing bounded feed stale reason | Same key remains status handle | No new command | Snapshot rehydrate | Show stale/pending, not success |
| Control Plane unavailable / DB timeout | Uncertain | Sanitized infrastructure code | Reuse same key | Must determine receipt before retry | Reconcile after recovery | No blind re-submit |
| Gate required/superseded | Rejected or workflow-specific | Gate stable code | Existing receipt behavior | No E12 call from E11 | Read gate status only | Link/read state; no hidden decision |

## 5. Migration and compatibility decision

The design stage makes **no schema decision and no migration**. Static source evidence suggests that command envelopes, requester/actor records, receipts, idempotency, expected-version checking, immutable transitions, event/outbox and E7 projections are reusable. However, `DATABASE EVIDENCE UNAVAILABLE` prevents proof that current production-like catalog metadata can support every required delegation detail.

If a future implementation proposes a migration, it must be separately authorized and explain why the existing receipt/event/projection structures cannot carry the required command status, actor chain, creator scope, correlation or reconciliation data. The proposal must enumerate table/column, role, grant, owner, ACL, immutability, replay, migration ordering and rollback effects. It must not modify migrations `0001–0032`.

## 6. Implementation prerequisites and go/no-go

| Prerequisite | Required before implementation authorization |
|---|---|
| Live catalog evidence | Safe disposable PostgreSQL `SELECT` audit of relevant roles, ACLs, owners, function properties and constraints. |
| Scope proof | Server-derived OIDC creator scope and target binding demonstrated with own/foreign Project tests. |
| Proxy boundary | Trusted service identity, allow-list and non-impersonation behavior documented and tested. |
| Existing semantic handler reuse | Each exposed command maps to an existing handler or a separately approved semantic design; no generic direct transition endpoint. |
| Receipt-first semantics | Same-key replay/conflict, crash, timeout and no-duplicate behavior demonstrated. |
| Projection proof | E7 snapshot/live-feed reconciliation shown for pending, applied, stale, gap, duplicate, reorder and restart conditions. |
| Security proof | Direct DML denial, actor override denial, E12 exclusion and sensitive-data non-leakage demonstrated. |
| Release / rollback | Feature boundary and idempotent disable/rollback plan that preserves durable audit evidence. |

The recommended design is therefore **go for separate implementation authorization only**, not go for immediate coding. A future authorization must specify the exact bounded command subset, transport implementation scope, any needed migration, all PostgreSQL tests, and explicit prohibition on E12 expansion.

## 7. Risks and rollback strategy

The primary risks are actor confusion, creator-scope bypass, receipt/projection disagreement, idempotency collision, lifecycle overexposure, a hidden E12 decision path, and accidental creation of a second authority broker. The primary mitigation is to prefer a narrow allow-listed proxy over direct runtime access or a new broker.

Rollback must disable the new Product API command entry surface while retaining receipts, events and existing Project authority records. It must never rewrite historical transitions, erase audit records, widen runtime privilege, or alter E4 durable identity. Existing E7 read projection remains the source of displayed Project state during rollback.

## References

[1]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/src/hermes_runtime/application/handlers.py
[2]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/src/hermes_runtime/application/product_api.py
[3]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/migrations/0003_project_state_authority.sql
