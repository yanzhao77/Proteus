# Hermes Runtime V1.2 P1 Slice 1 Acceptance Matrix

Date: 2026-08-12

| Requirement | Implementation | Test evidence | PostgreSQL 14/16 | Status |
| --- | --- | --- | --- | --- |
| ResourceAccount authority | versioned Account and per-dimension balances | Accounting integration | PASS/PASS | PASS |
| Twelve dimensions/units | enum, fixed units, DB checks | domain + migration | PASS/PASS | PASS |
| Currency semantics | ISO uppercase currency for `llm_cost_minor` | domain/integration | PASS/PASS | PASS |
| Atomic Reservation | Account/balance row locks and expected version | CT-005 + multi-dimension | PASS/PASS | PASS |
| Owner binding | decision/action/preparation identity | owner validation | PASS/PASS | PASS |
| UsageRecord | immutable sample identity and amounts | Usage/permission tests | PASS/PASS | PASS |
| Settlement | full actual consumption and full reserved release | FI-17 + over-limit | PASS/PASS | PASS |
| Thresholds | integer basis points, zero limit, warn/gate/hard stop | domain/integration | PASS/PASS | PASS |
| Hard stop | blocks new ordinary Reservation; recovery remains legal | over-limit/reconcile | PASS/PASS | PASS |
| Budget Fact bridge | Account/version-bound producer; stale Fact invalidated | Budget Fact integration | PASS/PASS | PASS |
| Event/Outbox/Receipt | same transaction as Accounting authority | fault/idempotency tests | PASS/PASS | PASS |
| Runtime permissions | dedicated owner and guarded functions | Accounting permissions | PASS/PASS | PASS |
| CT-005 | one concurrent reserve succeeds; final reserved=70 | two connections + barrier | PASS/PASS | PASS |
| FI-16 Accounting | preparation failure rolls back; no queued Event | injected failure | PASS/PASS | PASS |
| FI-17 Accounting | crash/retry and two reconcilers settle once | fault + concurrency | PASS/PASS | PASS |
| Orphan reconcile | failed preparation released exactly once | recovery controller | PASS/PASS | PASS |
| P0 regression | original 130 tests unchanged | full discovery | 130/130 | PASS |

## Scope Boundary

This slice does not implement Situation, Diagnosis, Planner, Policy, Risk, Selection, complete Decision Record, ExecutionRequest, Scheduler, Lease/fencing, Worker lifecycle, Capability Registry, Sandbox compiler, Human Gate, external Agent execution, FastAPI or distributed infrastructure.

FI-16 is complete only for same-transaction preparation/reservation rollback and explicit orphan release. FI-17 is complete only for Usage/Settlement recovery. Real ExecutionRequest/Lease/Run completion coupling remains a declared P2/P3 gate, not an unreported gap in this Accounting slice.
