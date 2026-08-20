# E4 Approval Bridge Implementation Progress

## Implemented foundation

The E4 recon report, deterministic approval/lowering domain module, domain tests, and unique `0030_e4_approval_bridge.sql` migration are present in this isolated worktree. The domain module defines typed approval source/request/preview structures, server-computed acknowledgement references, canonical blueprint hashing, stable bridge/Project/task/verification/child-command identity derivation, and the append-only bridge status vocabulary.

The lowering rule is frozen and tested as follows: E3 dependency `source -> target` lowers to the existing Graph semantic `AddTaskDependency(task_id=target, depends_on_task_id=source)`. The bridge has no Worker, Scheduler, Execution, Planner, provider, or P6 invocation.

## Confirmed child authority interfaces

Existing command types are defined in `application/commands.py`: `CreateProject`, `ApplyWorkGraphPatch`, and `CreateVerificationPlan`. Their `CommandEnvelope` requires command ID, command type, idempotency key, expected version, actor, reason, and project ID. Existing ControlPlane handlers own command validation and child-store receipt/event/outbox behavior. E4 will call those ports only; E4 PostgreSQL code will not write projects, tasks, graph, verification, event, outbox, scheduler, or P6 tables.

## Remaining implementation work

The next implementation slices are the E4 PostgreSQL bridge store, recoverable saga service, child receipt/source reconciliation adapters, Product API/FastAPI/OIDC routes, frontend approval panel, PostgreSQL fault-injection tests, fresh migration, Full Runtime/P6/frontend validation, delivery report, manifest reseal, and an OPEN E4 PR.

## Current checkpoint

Focused E4 domain tests pass: 4 tests validate deterministic preview/hash/ID derivation, explicit server-computed acknowledgement enforcement, creator/hash/source fail-closed behavior, and the frozen dependency lowering direction. The only changed paths are E4-new documents, domain/application modules, migration 0030, and E4 tests. No protected authority path has been modified.

## API composition checkpoint

`api_main.build_app()` composes E3 through `PostgresEntryProposalMasterPlanStore` only when database and OIDC verifier are available; otherwise it is fail-closed. FastAPI exposes the E3 Master Plan nested family through `_draft_dispatch`, which uses `_verified_dispatch`. E4 routes will extend that same nested `proposal/master-plan` family and must use `_draft_dispatch`, not a Factory Home path or unverified dispatch.

## Frontend recon checkpoint

`ProductApiDrafts` already owns the nested Master Plan API family. `MasterPlanDeck` currently renders a correct E3-only placeholder declaring that E4 is not implemented. E4 UI work must replace this placeholder with typed approval preview/status calls, explicit server-listed acknowledgement inputs, a deliberate approve action, and authoritative materialized Project ID. It must not add Worker, Scheduler, Execution, provider, Portfolio, or Live Workspace controls.

## Verification checkpoint

Current backend focused coverage is 8 passing unittest cases across deterministic lowering, acknowledgement enforcement, dependency direction, saga child-port mapping, OIDC creator binding, approval payload allowlisting, and preview no-side-effect behavior. Full E4 acceptance remains pending: durable child reconciliation implementation, PostgreSQL fault injection/permissions tests, frontend approval UI and adapter tests, fresh 0001→0030 migration, P6/Full Runtime/frontend regressions, delivery report, manifest reseal, and OPEN PR audit.

## Fresh migration checkpoint

A random local disposable PostgreSQL database applied migrations `0001` through `0030` successfully. It contained exactly five `entry_approval_*` tables. The E4 append-only tables exposed three immutable triggers; `hermes_control_plane_runtime` had zero direct INSERT/UPDATE/DELETE grants on `projects`, `tasks`, and `verification_plans`. The disposable database was dropped immediately after verification. No DSN, password, token, or provider material was recorded.

## Frontend baseline

Before E4 UI changes, the isolated worktree reused the original worktree frontend `node_modules` through a task-only symlink. Frontend tests passed 35/35, lint reported 0 warnings/0 errors, and production build passed. The symlink is untracked and will be removed before delivery.

## Current integration checkpoint

The typed E4 bridge is now wired through Product API, FastAPI verified draft dispatch, fail-closed API composition, and a Draft Workspace approval panel. Local focused backend coverage is 8 passing tests; frontend build passes. The E3 FastAPI test was narrowed from a global no-approve assertion to its own E3 route set, allowing E4 approval routes to be covered by E4-specific tests. Formal PostgreSQL source-seed, saga reconciliation/fault injection, full regression, delivery reseal, and PR work remain pending.
