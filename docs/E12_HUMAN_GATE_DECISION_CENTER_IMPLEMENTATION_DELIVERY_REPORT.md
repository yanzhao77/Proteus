# E12 Human Gate Decision Center — Implementation Delivery Report

**Delivery state:** `IMPLEMENTED / VALIDATED CANDIDATE — NOT ACCEPTED / NOT PUBLISHED`
**Baseline:** remote `master` commit `adbecd3674b33aefe63fb4b2dd34c1faf7d726c5`
**Scope:** E12 only. This candidate does not enter E13–E16 and does not create a pull request.

## 1. Decision and authority boundary

E12 provides a creator-scoped **Gate Inbox** and **Gate Detail** surface over the existing Human Gate authority. It does not create an approval authority, change a Gate state machine, or invoke E11 Project pause/resume/cancel semantics. The browser may submit only an `APPROVE` or `REJECT` decision with a non-empty reason, the expected Gate version, and client-generated idempotency metadata. It cannot submit an actor, approver identity, authorization assertion, project scope, Gate state, direct-resume flag, raw SQL, or arbitrary action.

The server derives the user identity from the verified opaque OIDC session, derives creator visibility from existing creator-scoped Project facts, reads the existing Gate request and admitted authorization assertion, and delegates to the existing `HumanGateProductFacade`. The durable authority remains responsible for decision validation, expected-version checking, idempotency, receipt construction, decision event, outbox message, and audit facts.

> A Gate decision receipt is **not** a Project resume, Project state transition, or E11 semantic command. The UI renders the existing completion claim `GATE_DECISION_RECEIPT_IS_NOT_PROJECT_RESUME` and does not expose a direct resume action.

## 2. Delivered interaction model

| Surface | Delivered behavior | Authority boundary |
|---|---|---|
| Gate Inbox | Lists only existing creator-scoped `REQUESTED` Gate facts, with project/gate filter and safe freshness metadata. | Read-only source-derived projection; no decision payload is formed in the Inbox. |
| Gate Detail | Shows safe Gate request facts: Project, action, reason, risk/evidence availability, expiry, version, and read-only audit rows. | Detail is creator-scoped and does not reveal request secrets, assertions, raw evidence, or internal authority objects. |
| Decision panel | Presents Approve and Reject only while the Gate is `REQUESTED`; decision reason is mandatory and bounded to 500 characters. | Uses the existing Human Gate decision transport; no actor, scope, assertion, authorization reference, or Gate state is client-selectable. |
| Receipt and refresh | Shows receipt metadata and its explicit non-resume claim, then re-reads the safe Gate Detail. | The receipt does not mutate local Gate state. Updated `APPROVED`/`REJECTED` state and audit arrive only from a source-derived detail read. |
| Duplicate prevention | Buttons are disabled during submission and after a receipt; after detail refresh, decision controls are removed for a non-pending Gate. | No retry loop or second decision command is created by the UI. |
| Explain / Audit | A local read-only panel exposes safe audit metadata after refresh. | It never opens an execution or Project command pathway. |

## 3. Server and persistence evidence

The candidate adds a trusted `UserHumanGateTransport` pattern analogous to E11’s verified-user transport while preserving the independent Human Gate authority. Its Product API and FastAPI routes are session-derived and fail closed when the transport, verified identity, creator scope, admissible Gate request, or approver assertion is unavailable. The legacy read-only Human Gate HTML renderer remains available for compatibility; legacy unauthenticated write routes now fail closed rather than accepting a client actor.

Authentic PostgreSQL 16 validation applied the repository’s existing migration chain and used the existing Human Gate persistence contract. The focused tests cover creator scope denial, verified-user identity mismatch, absent assertion, action allowlist rejection, mandatory reason, expected-version conflict, same-key same-payload replay, same-key different-payload conflict, receipt recovery, event/outbox persistence, and post-decision pending-Inbox removal. No migration, schema, database role, grant, ACL, function owner, security mode, or hardened search path was changed.

## 4. Browser E2E evidence

A disposable sandbox-local PostgreSQL database, a real FastAPI application, a real React production build, a synthetic local RS256 OIDC verifier, and an opaque HttpOnly session were used for two browser checks. The first check confirmed the baseline flow and revealed that the audit panel retained the pre-decision detail snapshot. That finding was fixed before acceptance: on successful receipt, Gate Detail now performs a read-only safe-detail refresh, transitions to the source-derived `APPROVED` version, renders the audit entry, and removes the Approve/Reject controls.

The final browser E2E used a **new** disposable database and a new pending Gate. Following an explicitly confirmed single Approve action, the page displayed an `APPLIED` receipt with `HUMAN_GATE_APPROVED`, retained the non-resume completion claim, refreshed to `APPROVED` at Gate version 2, removed both decision controls, and showed one `CURRENT` Approve audit row. The refreshed Inbox reported no pending Gate. A read-only database audit confirmed one `human_gate.approved` event and one linked outbox message, with the decision persisted by the verified user. All local browser services, synthetic identity materials, browser state, temporary archives, and disposable databases were deleted after validation.

## 5. Verification matrix

| Verification | Result | Notes |
|---|---|---|
| E12 transport unit tests | PASS | Verified identity, creator scope, admitted assertion, allowlist, mandatory reason, versions, receipts, and fail-closed conditions. |
| E12 FastAPI/OIDC tests | PASS | Verified opaque-session identity derivation, creator-scoped list/detail, strict authority-field rejection, and decision endpoint behavior. |
| E12 real PostgreSQL transport tests | PASS | Verified durable decision, receipt/replay/conflict, event/outbox, audit, stale-version rejection, and Inbox removal without schema or ACL changes. |
| E11/E12/Human Gate focused backend regressions | PASS | Existing read-only renderer compatibility and fail-closed legacy mutation behavior remain covered. |
| Full runtime discovery | PASS | `735 run / 12 skipped / 0 failures` in `431.843s` on fresh PostgreSQL 16 with the repository’s controlled Golden Todo prerequisites. |
| Frontend TypeScript | PASS | `tsc --noEmit` and production build passed. |
| Frontend regression | PASS | `82/82` Vitest tests passed, including receipt refresh, audit rendering, decision-control removal, required reason, authority payload exclusion, and no cancel control. |
| Frontend static analysis | PASS | oxlint completed with `0 warnings / 0 errors`. |
| Final browser E2E | PASS | Real local OIDC session, Approve receipt, safe detail refresh, audit entry, control removal, and Inbox removal. |
| Boundary and source audit | PASS | No E13–E16, migration, schema, role, grant, ACL, E4 identity, P0–P6 authority-state or provider configuration change. |

## 6. Acceptance limits and next steps

This is an implementation candidate only. It is intentionally uncommitted, unpublished, and unaccepted. The current remote `master` remains the E11-complete baseline until a separately authorized E12 delivery review, precise commit, pull request, CI review, and an independently authorized standard merge occur. E12 must not be represented as final authority completion merely because this isolated implementation and its evidence pass.

No E13, E14, E15, or E16 work has been started.

## References

[1]: E11 trusted transport delivery and reconciliation evidence, [`E11_USER_COMMAND_TRANSPORT_IMPLEMENTATION_DELIVERY_REPORT.md`](E11_USER_COMMAND_TRANSPORT_IMPLEMENTATION_DELIVERY_REPORT.md).
[2]: Existing Human Gate authority and Product API contracts, [`hermes-runtime/src/hermes_runtime/application/human_gate.py`](../hermes-runtime/src/hermes_runtime/application/human_gate.py) and [`human_gate_product.py`](../hermes-runtime/src/hermes_runtime/application/human_gate_product.py).
[3]: E12 implementation verification, [`test_user_human_gate_transport.py`](../hermes-runtime/tests/test_user_human_gate_transport.py), [`test_e12_fastapi_transport.py`](../hermes-runtime/tests/test_e12_fastapi_transport.py), and [`test_e12_human_gate_postgres.py`](../hermes-runtime/tests/test_e12_human_gate_postgres.py).
