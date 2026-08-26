# E11 User Command Transport PostgreSQL Implementation Acceptance Matrix

> **Purpose:** This is a future implementation acceptance specification. No command transport has been implemented and no implementation test was run in this design stage.

## 1. Test environment and evidence rule

A future implementation must be evaluated in a fresh disposable PostgreSQL environment built through the repository migration chain applicable at that time. The implementation review must preserve the historical chain through `0032` and may use only a separately authorized forward migration if schema evidence proves one is required. Tests must use verified OIDC identities, server-derived creator scope and a trusted Control Plane executor. Fixture actor override, browser-selected scope, direct store calls and direct DML are invalid evidence.

Every state-changing scenario must collect only sanitized identifiers, stable codes, receipt status, authority revision, projection revision and event/receipt references. It must not expose user content, token material, DSNs, headers, prompts or credentials.

## 2. Permission and authority matrix

| Test case | Required setup | Expected result | Evidence |
|---|---|---|---|
| API role direct runtime write | Verified API/OIDC role attempts table-level mutation through no approved proxy | Denied; no authority transition | Permission-denied stable code; unchanged receipt/event/project state |
| OIDC actor impersonates Control Plane | Request attempts browser-provided executor/actor override | Denied before proxy dispatch | Actor-mismatch stable code; no receipt side effect unless rejection receipt policy requires one |
| Valid trusted proxy | Proxy identity invokes an approved existing semantic handler | Accepted only for an approved command and valid requester | Separate `requested_by` and `executed_by` audit chain |
| Proxy command allow-list | Proxy submits a command not in the approved E11 set | Denied | Command-not-allowed stable code; no direct handler escape |
| Runtime least privilege | Runtime role accesses an unapproved authority object | Denied | Catalog/permission evidence and no DML side effect |
| Function hardening | Relevant function owner, ACL, `SECURITY DEFINER` and `search_path` are inspected | Matches approved baseline | Sanitized catalog metadata |
| E12 exclusion | E11 route attempts to invoke human-gate decision path | Denied or route absent | No gate decision receipt/event from E11 request |

## 3. Creator scope and target binding matrix

| Case | Required result |
|---|---|
| Valid creator and owned Project | Request may reach receipt-first proxy flow only if command eligibility passes. |
| Foreign creator / project-ID probing | `NOT_FOUND` or scope-safe denial; no disclosure of foreign Project facts. |
| Missing verified scope | Rejected before receipt claim or marked as rejected according to the durable receipt policy. |
| Browser-supplied scope list | Ignored/rejected; server derives scope from verified OIDC subject. |
| Target substitution after request construction | Rejected by canonical target validation and request hash. |
| Cross-creator same idempotency key | Conflict or isolated key scope; never replays another creator’s receipt. |
| Admin scope | Separately modeled and tested; it cannot silently inherit creator scope or bypass Control Plane execution. |

## 4. Receipt, replay and crash matrix

| Scenario | Expected protocol result |
|---|---|
| First valid submission | Receipt is claimed durably before authority work; response is `RECEIPT_ACCEPTED` or `AWAITING_AUTHORITY`, never falsely `APPLIED`. |
| Same key / same canonical body | Existing receipt is returned; no duplicate semantic handler invocation, event or transition. |
| Same key / different body | Stable idempotency conflict; no second side effect. |
| Crash before receipt completion | Restart locates deterministic receipt state or safely accepts a first durable claim; no ambiguous duplicate execution. |
| Crash after receipt before authority apply | Restart resumes or reports pending based on durable receipt status; no blind new command. |
| Crash after authority apply before projection | Receipt/event proves authority result; UI remains pending/uncertain until projection reconciliation. |
| Authority rejection | Receipt carries sanitized rejection code and no applied transition/event is fabricated. |
| Database timeout / uncertain outcome | Same key is reused for status lookup; no automatically generated replacement key. |

## 5. Expected-version and concurrency matrix

| Scenario | Expected result |
|---|---|
| Current expected version | Eligible command can proceed through semantic handler. |
| Stale expected version | Stable conflict/rejection; no last-write-wins. |
| Concurrent same key | One receipt and one semantic outcome; all callers converge on same result. |
| Concurrent different keys, same target | Command-specific serialization/eligibility result; all outcomes audit distinct command IDs. |
| Concurrent incompatible commands | One may apply only if lifecycle rules permit; rejected command has stable terminal/eligibility/version evidence. |
| Terminal Project state | Command-specific terminal rejection; never silently reopens or mutates terminal state. |

## 6. Projection, event and reconciliation matrix

| Scenario | Required behavior |
|---|---|
| Authority applied and projection current | Snapshot/current-state response contains matching authoritative and projection revision evidence. |
| Projection delayed | API reports non-final authority status; UI waits or refreshes creator-scoped snapshot. |
| Event missing, duplicate or reordered | Bounded feed reports stale/uncertain according to E7 semantics; snapshot rehydrates state. |
| Cursor gap/ahead/expired | No new authority fact is invented; stable stale reason and snapshot recovery path are returned. |
| Process restart | Durable receipt/event and snapshot reconciliation restore correct state. |
| Foreign creator reads status | Creator-scoped projection fails closed. |
| Terminal reconciliation | Final applied/rejected terminal state is reflected consistently in receipt and snapshot. |

## 7. Command-specific acceptance policy

| Intent | May be exposed after implementation review? | Mandatory semantic proof before exposure |
|---|---|---|
| Retry | No current approval | Explicit existing handler or separately approved semantic command; failed/recoverable lifecycle; source revision; idempotency. |
| Reconcile | No current approval | Must not reuse read-only findings or E4 approval reconcile; define authoritative target and result. |
| Reverify | No current approval | Immutable verification target, verifier authority, eligibility and terminal policy. |
| Permitted cancel | Conditional candidate | Existing `CancelProject`; verified authorization reference; owned target; allowed state; reason/version/idempotency. |
| Pause | Conditional candidate | Existing `PauseProject`; pausable state; creator scope; reason/version/idempotency. |
| Resume | Conditional candidate | Existing `ResumeProject`; resumable state; creator scope; reason/version/idempotency. |
| Acknowledge resolved incident | No current approval | Existing semantic primitive and audit policy; cannot be fabricated from read models. |

## 8. Security, audit and non-leakage matrix

The implementation test suite must prove actor override, target substitution, reason tampering, expected-version tampering, idempotency body tampering, sensitive-data leakage, unauthorized command, direct DML denial and E12 misuse. Every accepted operation must preserve an actor chain where the verified OIDC creator is `requested_by` and the trusted Control Plane is `executed_by`. Every user-visible failure must use a sanitized stable error code.

## 9. Completion criterion

The future implementation may not mark E11 complete merely because an endpoint returns `202`, a receipt exists, an event is delivered or a UI button appears. Completion requires the entire applicable matrix to pass against real disposable PostgreSQL, with creator scope, actor separation, receipt-first replay, expected-version conflict behavior, event/outbox, E7 projection reconciliation and direct-DML denial all verified.

## References

[1]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/src/hermes_runtime/application/handlers.py
[2]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/src/hermes_runtime/infrastructure/postgres_project.py
[3]: https://github.com/yanzhao77/Proteus/blob/85af422a758b8483b2d82d525c5920eb5f8f4d2d/hermes-runtime/src/hermes_runtime/infrastructure/postgres_live_production_read_model.py
