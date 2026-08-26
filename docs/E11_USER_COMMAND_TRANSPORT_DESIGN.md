# E11 User Command Transport Design

> **Design state:** `DESIGN COMPLETE / IMPLEMENTATION NOT AUTHORIZED`
>
> **Recommended architecture:** Product API → Trusted Control Plane Proxy → Existing Project Semantic Handler.
>
> **E11 status remains:** `PARTIAL / ACCEPTANCE GAP`.

## 1. Decision question

The question is not whether an OIDC user may become a runtime authority. It is whether a verified creator may express a bounded Project Operations **intent** that is independently authorized, executed and recorded by the existing Control Plane. The answer is **yes, conditionally**, only if a future implementation preserves the existing two-actor model, reuses existing semantic handlers and receipt/event/projection mechanisms, and passes the implementation prerequisites in this document.

The proposed transport must establish this invariant:

```text
requested_by = verified OIDC creator, derived server-side from the authenticated session
executed_by  = trusted Control Plane authority, represented by the existing command envelope actor
```

These identities are deliberately different. A request is not an authority transition, an HTTP `202` is not `APPLIED`, and a receipt or event alone is not a final UI state.

## 2. Candidate architecture comparison

| Candidate | Description | Authority result | Decision |
|---|---|---|---|
| A. Direct Product API invocation as OIDC user | Product API invokes Runtime/Project handler with the browser user as authoritative actor. | Collapses requester and executor; risks direct runtime authority and actor confusion; can pressure API-role privilege expansion. | **Rejected.** |
| B. Trusted Control Plane proxy | Product API validates a server-derived creator scope, submits a typed semantic request to a trusted Control Plane proxy, which invokes an existing Project handler as `CONTROL_PLANE`. | Preserves authoritative executor, supports separate requester audit chain, and can reuse command receipts, events/outbox and E7 reconciliation. | **Recommended, conditionally.** |
| C. Independent delegation/command broker | Adds a new delegation service/object between Product API and runtime. | Risks a second authority plane, new service identity/ACL/migration surface, and duplicate replay/reconciliation logic. | **Rejected by default.** Reconsider only if an implementation review proves the existing Control Plane cannot provide a bounded proxy. |

### Recommended flow

```text
OIDC user
  → verified session identity
  → server-derived creator scope
  → typed Product API semantic request
  → trusted Control Plane proxy
  → existing Project semantic handler
  → CommandReceipt / authority transition
  → event + outbox
  → E7 snapshot and bounded live-feed reconciliation
  → Product API status response
  → UI applied state
```

The Product API must not call store methods, perform direct DML, manufacture a receipt, accept a client-selected creator scope, set a `CONTROL_PLANE` actor from browser input, or use the E12 Gate decision route as a substitute command channel.

## 3. Minimum future request and response contract

A future implementation must use a typed, server-side contract. The browser submits only user intent fields that are explicitly allowed for the selected semantic command. The service derives identity and scope.

| Request field | Source and rule |
|---|---|
| `command_id` | Server-generated or server-validated immutable identifier. |
| `command_type` | Fixed enum selected by the endpoint; never an arbitrary client handler name. |
| `target_type`, `target_id` | Route/server validated; target must be in verified creator scope. |
| `requested_by` | Derived from the verified OIDC session only. |
| `creator_scope` | Derived server-side; never accepted as a browser-selected list. |
| `reason` | Required non-empty bounded string; persisted through existing semantic handler rules. |
| `idempotency_key` | Client supplied within a bounded namespace; tied to requester, command type and target. |
| `expected_version` | Required for state-changing Project commands; no implicit last-write-wins. |
| `source_revision` | Required when the selected command semantics depend on an immutable source/recovery revision. |
| `correlation_id` | Server-generated or validated tracing identifier, not an authority override. |
| `requested_at` | Server timestamp. |

| Response field | Meaning |
|---|---|
| `receipt_id` / `command_id` | Identifier for a receipt, never a declaration that the transition applied. |
| `idempotency_key` | Echoed only as the same-key replay identity. |
| `status` | One of `RECEIPT_ACCEPTED`, `AWAITING_AUTHORITY`, `APPLIED`, `REJECTED`, `UNCERTAIN`, `TERMINAL_FAILURE`. |
| `accepted_at` | Receipt acceptance timestamp, not transition completion time. |
| `rejection_code` | Sanitized stable code only. |
| `status_url` | Read-only status/projection endpoint. |
| `authority_revision` | Version after verified authority transition, when applied. |
| `projection_revision` | E7 projection watermark/revision used to establish the displayed state. |
| `current_state` | Source-derived state after reconciliation. |

The same idempotency key with the same canonical body must replay the same receipt/result. The same key with a different canonical body must return a stable conflict. An expected-version conflict must reject rather than write over current state.

## 4. Command eligibility design

The future transport must not expose every internal command. The matrix below is a design decision, not current behavior.

| Command | Current semantic primitive | Creator request proposal | Control Plane execution | Gate / state policy | UI exposure in future E11 |
|---|---|---|---|---|---|
| Retry | No verified public Project retry primitive identified | **Not approved** until semantic owner defines eligibility | N/A | Must define failed/recoverable state and source revision | Hidden; show unavailable reason, not a successful action |
| Reconcile | Existing finding replay is read-only; reconciliation internals are not public Project command | **Not approved** | N/A | Must not reuse E4 approval reconcile | Hidden |
| Reverify | Existing verification authority is task-level/Control Plane bounded | **Not approved** | N/A | Requires immutable verification target and lifecycle rule | Hidden |
| Permitted cancel | `CancelProject` exists | Candidate after explicit creator-scope and authorization-ref design | Existing Control Plane envelope | Require allowed non-terminal state, reason and authorization reference | Possible only after implementation approval |
| Pause | `PauseProject` exists | Candidate after explicit creator-scope design | Existing Control Plane envelope | Require pausable state, reason and expected version | Possible only after implementation approval |
| Resume | `ResumeProject` exists | Candidate after explicit creator-scope design | Existing Control Plane envelope | Require resumable state and expected version | Possible only after implementation approval |
| Acknowledge resolved incident | No verified generic primitive identified | **Not approved** | N/A | Must not invent a recovery bypass | Hidden |

Admin and creator scope are separate policies. A future implementation must not infer that an admin can perform every creator command, or that every creator request is automatically eligible. The Control Plane remains the only authoritative executor for Project transition commands.

## 5. State, replay and reconciliation semantics

The receipt-first protocol must handle partial completion without fabricating success.

| Condition | Required behavior |
|---|---|
| Receipt claimed, authority not yet applied | Return `RECEIPT_ACCEPTED` or `AWAITING_AUTHORITY`; UI renders pending status. |
| Same key, same body | Reuse the existing receipt and return its durable status. |
| Same key, different body | Reject with a stable idempotency conflict; no second side effect. |
| Current expected version differs | Reject with an expected-version conflict; UI refreshes source-derived projection. |
| Authority rejected | Return `REJECTED` with stable code; preserve receipt/audit evidence. |
| Authority applied, projection delayed | Return non-final authority evidence and poll/read the bounded E7 projection until watermark/revision confirms state. |
| Event cursor gap, duplicate or reorder | Treat as stale/uncertain; rehydrate from creator-scoped snapshot rather than optimistic state. |
| Process restart | Resume from durable receipt, event/outbox and snapshot; never re-execute blindly. |
| Control Plane unavailable or database timeout | Return `UNCERTAIN` only when durable result cannot be determined; same key remains the recovery handle. |

## 6. UI integration boundary

Future E11 UI behavior is strictly constrained to:

```text
user intent → local validation → typed Product API command → receipt status
→ authority status → creator-scoped projection reconciliation → applied UI state
```

The UI must not directly mutate Project or Task state, call a Runtime handler, choose creator scope, create a receipt, decide retry eligibility, conceal an unavailable command as success, or overlay optimistic state above an E7 projection. The E12 Gate decision route cannot be embedded as an E11 hidden command.

## 7. Security threat model and rollback

| Threat | Required mitigation |
|---|---|
| Actor override | Ignore browser actor fields; derive requester from verified session and executor from trusted Control Plane identity. |
| Target substitution | Server checks target membership in creator scope before proxy dispatch. |
| Reason, version or body tampering | Canonical receipt request hash; expected-version and server-side schema validation. |
| Idempotency collision | Scope key by requester, command type and target; reject same-key/different-body. |
| Direct DML or store path | Product API role must remain unable to write runtime authority tables directly. |
| E12 misuse | Route-level and test-level exclusion of human-gate decision as E11 command transport. |
| Projection lag | Explicit pending/uncertain state and bounded snapshot rehydration. |
| Secret leakage | Persist and return sanitized stable codes, hashes and identifiers only; do not place payloads or credentials in receipts/UI. |

Rollback is transport-level: disable the new Product API command route before changing existing semantic handler or receipt data. Existing Control Plane, E7 read projections and E12 gate flows remain untouched. Any implementation must be separately released behind an explicit feature/route boundary and must have a tested idempotent rollback that does not erase receipts or audit evidence.

## 8. Migration decision and implementation prerequisites

**Migration decision: `NO MIGRATION DECISION AUTHORIZED IN THIS DESIGN STAGE`.** The static audit identifies reusable receipt, idempotency, expected-version, actor/requester, event/outbox and projection primitives. It does not prove that the present schema can record every future transport field, in particular correlation/status linkage and any additional creator-scope receipt rule, because live catalog evidence was unavailable.

A future implementation proposal may conclude either `No migration required` or `Migration required — separate implementation authorization required`. It must not create a migration until the following prerequisites pass:

1. A safe disposable PostgreSQL catalog audit confirms live owners, ACLs, `SECURITY DEFINER` properties and hardened `search_path` settings.
2. The Product API role is proven unable to direct-write runtime authority tables and unable to impersonate Control Plane.
3. The trusted proxy has a bounded service-to-service identity and can invoke only approved existing semantic commands.
4. Creator scope is server-derived from verified OIDC identity and independently checked against the target Project.
5. Each enabled command has lifecycle eligibility, terminal-state behavior, reason, expected-version, idempotency, receipt, event/outbox and projection reconciliation rules.
6. E12 remains excluded and no second broker/authority plane is introduced.
7. A separately authorized real-PostgreSQL implementation test matrix passes.

## 9. Go / no-go conclusion

**DESIGN APPROVED — IMPLEMENTATION MAY BE AUTHORIZED SEPARATELY.** This is a conditional design approval for the trusted Control Plane proxy pattern only. It is not authorization to implement a transport, create a migration, change role/ACL/function properties, add an endpoint, expose UI actions or enter E12.

## References

[1]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/src/hermes_runtime/application/handlers.py
[2]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/src/hermes_runtime/application/commands.py
[3]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/src/hermes_runtime/infrastructure/postgres_project.py
[4]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/src/hermes_runtime/infrastructure/postgres_live_production_read_model.py
