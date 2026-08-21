# E4 Approval Bridge Implementation

## Completed architecture

E4 is a durable application bridge over existing authority. `DurableApprovalBridgeOrchestrator` composes `PostgresEntryApprovalBridgeStore`, `ApprovalBridgeSaga`, and the real `ControlPlane`/`PostgresProjectStore` child adapter. It accepts a creator-scoped approval receipt, routes both approval and reconciliation into the same saga, and returns only `PROCESSING`, `MATERIALIZED`, or a stable terminal outcome. FastAPI composition creates this real stack only when PostgreSQL and OIDC verification are configured; otherwise the E4 surface remains fail-closed.

The E4 domain freezes the current E3 `master-plan-compiler-v1` / `e3-v1` Master Plan. Its deterministic blueprint derives the bridge, Project, GraphPatch, task, VerificationPlan and child command IDs. Graph lowering preserves the established direction: E3 `source -> target` becomes `AddTaskDependency(task_id=target, depends_on_task_id=source)`. New graph-created tasks start at the existing authority version of `1`; each frozen VerificationPlan envelope therefore carries `expected_version=1`, the existing `verification_plan.create` command type, and schema-valid `evidence_level='E4'`.

## Durable state and reconciliation

Migration `0030_e4_approval_bridge.sql` remains the sole E4 migration. It owns only E4 receipt, bridge, append-only step, append-only transition and materialized-binding records. The approval receipt and frozen bridge are written in one transaction before child invocation. The saga invokes each deterministic child command via the real ControlPlane, records the authoritative child receipt as an E4 step, and continues in order: Project, GraphPatch, then one VerificationPlan per frozen task.

A fault-injecting test adapter invokes each real child port first and throws only after the child transaction returns. A newly built orchestrator/store then reconciles the same bridge and deterministic child receipt identity. This validates process-crash recovery after the E4 receipt, Project, GraphPatch, first VerificationPlan and second VerificationPlan boundaries. Replays and concurrent fresh reconciliations converge with one Project, the frozen task/dependency set, one VerificationPlan per task, four child command receipts, one binding and no duplicate E4 steps. Repeated materialization transition insertion is idempotent.

Explicit child `CommandRejected` outcomes are separate from unknown interruption. A real duplicate Project identity is mapped by `PostgresProjectStore` to `PROJECT_ALREADY_EXISTS`; the orchestrator appends `FAILED_TERMINAL` and future reconcile calls fail closed rather than retrying or compensating with direct child-table writes.

## Database contract

The E4 bridge header allows only state-machine fields to change. A 0030 trigger rejects replacement of frozen source identity, hashes, approval/creator identity, compiled blueprint, acknowledgements, intended Project or child command IDs. The approval receipt supports its required first in-transaction `NULL -> result_payload` fill and rejects all later rewrite or deletion. Existing append-only triggers protect step, transition and materialized-binding facts. The E4 26-scenario real PostgreSQL matrix verifies all five protections. `hermes_control_plane_runtime` has no direct INSERT/UPDATE/DELETE grant on `projects`, `tasks`, `task_dependencies`, or `verification_plans`, and direct Project insertion under that role is denied.

## Completed verification

| Gate | Result |
| --- | --- |
| Real PostgreSQL durable matrix | 26 passed |
| E4 domain/saga/Product API/FastAPI | 9 passed |
| Fresh disposable migration 0001→0030 | PASS |
| P6 Recovery permissions/runtime role | 9 passed |
| Full Runtime | 634 run, 12 skipped, 0 failures |
| Frontend Vitest / build / lint | 35 passed / PASS / 0 warnings and errors |

No migration `0001`–`0029`, E1/E2/E2.x/E3 authority semantic, P6 role/grant/function/trial, provider integration, or E5+ path was changed. The E4 implementation is ready for manifest reseal, exact staging, PR #20 update and CI review.
