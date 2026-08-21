# E4 Approval Bridge Design

## Scope

E4 is a server-owned approval bridge from a current, approved E3 Master Plan to existing ControlPlane authority commands. It has no authority to start runtime services or modify child authority tables. E4 freezes source identity, compiles a deterministic blueprint, creates an approval receipt, and invokes existing Project, Graph, and Verification command ports using deterministic child identities.

## Approval and preview contract

A preview binds the current Draft, Understanding, Proposal, and Master Plan revisions and hashes to a `compiled_blueprint_hash`. The compiler and policy versions are included in the preview. An approval request contains only verified OIDC subject, reason, idempotency key, expected Draft/Plan versions, exact source revisions/hashes, blueprint hash, acknowledgement set, and correlation. Client-provided actor, Project, task, child-command, runtime, and ControlPlane identity fields are rejected.

The acknowledgement set is server-computed. Every `UNCONFIRMED_SOURCE_ASSUMPTION` and all architecture, verification, or delivery intent marked `REVIEW_REQUIRED` produce a required acknowledgement reference. Approval rejects missing, surplus, or stale acknowledgements.

## Lowering

The compiler has no network, provider, clock, or randomness input. A stable bridge namespace derives bridge, Project, task, verification-plan, decision, child-command, and child-idempotency identities from the frozen Plan revision and blueprint hash. E3 nodes lower to Graph tasks. Plan dependency `source -> target` is frozen as an execution-precedence edge: the target task uses `AddTaskDependency(task_id=target, depends_on_task_id=source)`. This convention is explicitly tested against existing Graph store semantics.

Verification configuration is server-owned E4 v1 policy. Each lowered task receives one VerificationPlan; the browser does not select runner, profile, timeout, or execution properties. Insufficient plan verification intent is represented as a required acknowledgement and documented policy fallback, never as an inferred user field.

## Bridge state machine

`PROCESSING -> PROJECT_CREATED -> GRAPH_APPLIED -> VERIFICATION_APPLYING -> MATERIALIZED` is the normal flow. `RECONCILIATION_REQUIRED` records child receipt/source fact mismatch or unknown divergence; `FAILED_TERMINAL` records terminal child rejection. Each transition and step result is append-only. The bridge header contains a current status for access, but history is authoritative.

Before its first child command the bridge rechecks frozen source freshness. Once Project creation succeeds, later Draft/Plan changes cannot change its frozen snapshot; recovery uses the original child identities. A timeout/unknown result triggers deterministic receipt/source reconciliation rather than a new child identity. No raw rollback, delete, receipt rewrite, or synthetic materialization is permitted.

## Storage and privilege

Migration 0030 adds only E4 bridge headers, approval receipts, step records, transition records, and materialized bindings. It does not create Project/Task/Verification/event/outbox/scheduler tables. E4 runtime writes only E4 tables. Existing ControlPlane stores retain child transaction, receipt, event, and outbox ownership. Immutable E4 receipt, step, and transition records are protected by database triggers and least-privilege grants.

## API and UI

The single nested Master Plan family contains approval preview, approve, approval status, and reconcile. Unknown fields are rejected. OIDC verified subject controls creator-only scope; foreign creator reads are no-leak. `202` is only processing. A Project ID appears only in `MATERIALIZED`. The Draft Workspace presents preview, explicit acknowledgement checkboxes, deliberate approval, processing/reconcile/terminal status, and authoritative Project ID without runtime controls.
