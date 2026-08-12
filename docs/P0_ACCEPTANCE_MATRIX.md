# Hermes Runtime V1.2 P0 Acceptance Matrix

Date: 2026-08-12

| Requirement | Implementation | Test evidence | PostgreSQL | Status |
| --- | --- | --- | --- | --- |
| Project | guarded semantic Commands and Event invariant | `test_project_*` | 14/16 | PASS |
| Task | Control Plane transitions and deferred PASS invariant | vertical/closure tests | 14/16 | PASS |
| AgentRun | admitted WORKER/VERIFIER identity and invalidation | closure core/permissions | 14/16 | PASS |
| Artifact | immutable hash and WorkerRun provenance | vertical/closure tests | 14/16 | PASS |
| Evidence | immutable Artifact/hash binding and safe reuse | vertical/closure tests | 14/16 | PASS |
| VerificationPlan | immutable versions, Checks and current Task pointer | closure Plan/concurrency | 14/16 | PASS |
| VerificationResult | Plan/Artifact/VerifierRun and structured Checks | closure aggregation | 14/16 | PASS |
| Event Log | immutable partition-local sequence | delivery/authority tests | 14/16 | PASS |
| Transactional Outbox | authority/Event/Outbox/Receipt transaction | fault injection | 14/16 | PASS |
| Idempotent Consumer | Inbox, contiguous checkpoint and gap drain | delivery tests | 14/16 | PASS |
| Project Guard | fail-closed facts and verified Tasks | Project tests | 14/16 | PASS |
| Agent write prohibition | application boundary and runtime roles | permission tests | 14/16 | PASS |
| Task DAG / READY | acyclic dependencies and authoritative readiness | Graph tests | 14/16 | PASS |
| Verification-only verdict | Claim stops at COMPLETION_CLAIMED; computed verdict | domain/closure tests | 14/16 | PASS |
| Replay duplicate safety | Inbox identity and idempotent Commands | delivery/vertical tests | 14/16 | PASS |

P0 excludes ExecutionRequest, Lease/fencing, full Worker lifecycle, Resource Accounting, Policy/Risk, Human Gate lifecycle, Sandbox compiler and external Agent execution. These are later phase gates, not hidden P0 passes.
