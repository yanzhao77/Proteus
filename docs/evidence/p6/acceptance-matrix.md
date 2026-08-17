# P6 Autonomous Production Trial - Acceptance Matrix

Overall verdict: **PASS** (8/8)

| # | Acceptance item | Outcome | Detail |
|---|----------------|---------|--------|
| 1 | Happy path: Request->Situation->Planning->Policy/Risk->Selection->Capability->Execution->Failure->Diagnosis->Repair->Recovery->Verification PASS->Delivery ACCEPTED | **PASS** |  |
| 2 | Initial implementation genuinely fails and is recovered | **PASS** | happy path: worker pytest FAIL -> feedback -> diagnosis -> repair -> PASS |
| 3 | Worker SIGKILLed mid-run; lease relinquished, request requeued and re-run; independent verification PASS | **PASS** |  |
| 4 | Same project.create command + idempotency key -> identical receipt, one row | **PASS** |  |
| 5 | Produced artifact mutated on disk; independent verifier fails it closed (ARTIFACT_HASH_MISMATCH); task FAILED | **PASS** |  |
| 6 | Policy-required human gate pauses project (WAITING_FOR_HUMAN); authorized human decision resumes it | **PASS** |  |
| 7 | RecoveryController emit/plan/complete all ran | **PASS** | emit_execution_feedback + plan_recovery_attempt + complete_recovery_attempt on happy path |
| 8 | Project reached ACCEPTED with real guard facts | **PASS** | project evidence/policy/budget guard facts produced by real authority commands |
