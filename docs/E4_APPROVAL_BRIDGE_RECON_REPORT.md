# E4 Approval Bridge Recon Report

**Status:** Recon complete — no authority conflict identified.

## Authority boundary

E4 is an application bridge, not a new Project, Task, Graph, Verification, runtime, or P6 authority. It may call the existing `CreateProject`, `ApplyWorkGraphPatch`, and `CreateVerificationPlan` command ports and may read their command receipts and source facts. It must not write their tables directly, alter their state-transition rules, manufacture child receipts, or invoke Planner, Worker, Scheduler, Execution, Recovery, Human Gate, or P6 trial code.

The current E3 Master Plan is an immutable, `pre_approval_only` aggregate. Its source records Draft, Understanding, Proposal, and Plan revision identities and hashes. E4 must bind an approval to all current revisions, the Master Plan content hash, a server-compiled blueprint hash, and a server-computed acknowledgement set. Draft, Proposal, Understanding, and Plan freshness must be rechecked before any child command is submitted.

## Existing child-command semantics

The existing PostgreSQL Project and Graph stores own their own command receipts. `PostgresProjectStore.create_project()` and `PostgresGraphStore.apply_work_graph_patch()` are the applicable durable command surfaces; Graph processing treats a dependency operation as `(task_id, depends_on_task_id)`, where the task waits on the referenced dependency. E4 will freeze this direction in lowering tests before materialization.

Graph operations remain existing authority operations. E4 may lower a plan node only into the supported Graph task-add operation and each plan dependency only into the existing `AddTaskDependency` semantic. Child command envelope IDs, idempotency keys, Project ID, task IDs, verification IDs, and decision IDs must be deterministic derivations from the frozen bridge/plan identity. Existing child stores remain responsible for receipt replay, events, outbox, and source state.

## Reconciliation requirements

Bridge recovery cannot infer success from a timeout. It must query the deterministic child receipt and source facts. A matching receipt/source fact advances the bridge; a missing receipt is the only case in which the same deterministic child command may be reissued. A conflicting receipt, identity, payload hash, or source fact enters `RECONCILIATION_REQUIRED` or `FAILED_TERMINAL` without deleting or rolling back Project, Task, or Verification data.

## PostgreSQL design decision

Migration `0030_e4_approval_bridge.sql` may introduce only E4 bridge headers, immutable approval receipts, append-only step records, append-only transition history, and a final materialized binding. The bridge header cannot require a Project FK before Project creation. E4 tables are private to the E4 runtime role; browser/API roles receive no direct Project, Task, Graph, Verification, P6, or E4-table DML. Immutable approval, step, and transition facts require database trigger protection.

## API and UI boundary

Product API/FastAPI may expose one nested Master Plan family for approval preview, approve, status, and reconcile. OIDC verified subject is the sole creator/approver identity. Body/header actor fields are never trusted. A preview is read-only. `202` means processing only; a Project ID may be returned only after all child receipts/source facts reconcile and the bridge is `MATERIALIZED`.

The Draft Workspace may show server-computed acknowledgements, a preview, explicit approval confirmation, processing/reconciliation/terminal state, and authoritative Project ID only when materialized. It must not default acknowledgements, auto-approve, start runtime, or fabricate Portfolio/Live Production views.

## Recon verdict

No P0–P6, E1–E3 invariant, migration `0001–0029`, or P6 trial driver change is required by this design. E4 can proceed with one new migration, new bridge modules, E4-specific tests, and adapter calls to existing child authority ports.

## Required proof obligations

The implementation must prove deterministic lowering, frozen snapshot freshness, acknowledgement enforcement, dependency direction, one-bridge/one-Project concurrency, child receipt reconciliation, fault recovery at every child boundary, absence of direct Project/Task/Verification DML in E4 store, immutable bridge facts, no runtime/P6 side effects, and creator/OIDC/no-leak API behavior.
