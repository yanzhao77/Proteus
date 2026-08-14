# Hermes Runtime V1.2 P3 Completion Summary

Date: 2026-08-14

Status: P3-1 through P3-6 runtime authority complete on branch
`codex/p3-4-6-production-hardening`.

## Completed objective

P3 turns the P0-P2 execution authority chain into an operationally governable
runtime. The completed scope covers:

- Human Gate Request/Decision/Application with immutable ResumeContext.
- Project waiting/resume with current guard re-check.
- Checkpoint, Replay and Reconcile authority without Event-fold authority
  overwrite.
- Append-only Quarantine review/adoption/redrive and Evidence invalidation.
- Immutable Decision Explain, Audit and Trace snapshots.
- Docker target 1.0 production execution adapter with process lifecycle,
  artifact/output/usage handling and side-effect receipts.
- Cross-slice E2E hardening that proves Docker/Worker/Human Gate/Explain/side
  effects remain outside Task PASS authority.

## Authority boundaries

- Worker and Docker Adapter cannot mark Task `PASSED` or `FAILED`.
- Verification remains the only formal PASS/FAIL producer.
- Control Plane guarded Commands remain the only Task/Project state transition
  writers.
- Explain, risk, score, metrics and traces are audit/observability facts, not
  authorization facts.
- Replay rebuilds projections/read models and never rewrites normal authority
  tables by Event fold.
- Quarantine adoption/redrive and Evidence invalidation produce guarded
  follow-up facts; they cannot bypass current Policy, Lease, Fencing, Evidence
  or version guards.
- External side-effect receipts are external facts. Uncertainty produces
  reconcile findings rather than hidden authority repair.

## Docker target verified boundary

Docker target 1.0 compiles structured run plans with:

- non-root user;
- read-only root filesystem;
- deny-by-default network;
- `cap-drop=ALL`;
- `no-new-privileges`;
- tmpfs for writable runtime paths;
- pids, memory, CPU, timeout and output limits;
- environment allowlist and secret-handle discipline;
- declared artifact export paths only;
- deterministic container names/labels carrying request/run/lease/fencing refs.

On Docker Desktop/macOS this proves the local Docker VM boundary and adapter
contract. It is not a claim of multi-tenant cloud sandbox hardening.

## Acceptance matrix

`docs/P3_OPERATIONAL_GOVERNANCE_ACCEPTANCE_MATRIX.md` now marks blocking P3
rows through P3-5 as `PASS` with implementation, migration and test evidence.
P3-6 closes completion through cross-slice tests and this summary rather than a
new durable authority migration.

## Validation evidence

Final exact command results are recorded in the P3-6 commit and PR body:

- no-DB discovery;
- PostgreSQL 16 + Docker full regression;
- PostgreSQL 14 + Docker full regression;
- Docker integration subset;
- compileall;
- `git diff --check`;
- migration continuity, security, secret, PUBLIC EXECUTE, dangerous GRANT,
  generic repair/PATCH, skip-gap and Docker leak scans.

## Deferred productization

The following remain intentionally out of P3 runtime completion:

- Web UI and public FastAPI surface;
- production IdP, user directory, signature verification and multi-approver
  product policy;
- Kubernetes, Redis, Kafka, Raft or multi-region active-active deployment;
- real cloud production credentials or third-party irreversible side-effect
  integrations;
- browser/VM/GPU execution targets beyond Docker target 1.0;
- production observability backend and alerting platform;
- external artifact object store and secret-handle provider.
