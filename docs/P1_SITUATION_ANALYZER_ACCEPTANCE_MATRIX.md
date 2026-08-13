# P1 Slice 2 Situation Analyzer Acceptance Matrix

Status: PASS

Scope: deterministic Situation analysis only. Diagnosis, Planner, Policy/Risk,
Selection, ExecutionRequest, Scheduler, Worker heartbeat and Human Gate are excluded.

| Requirement | Evidence | Result |
| --- | --- | --- |
| Explicit versioned trigger catalog | `domain/situation.py`; unsupported catalog entries fail closed | PASS |
| Deterministic classification | Verification FAIL, READY, budget thresholds, Feedback and structured conflicts domain tests | PASS |
| No Diagnosis/root-cause inference | Domain output has no root-cause field; unknown failure remains explicit | PASS |
| Immutable AnalysisContext | `analysis_contexts` immutable trigger and stable-reference columns | PASS |
| Observed-sequence boundary | Context stores partition/sequence; authority checks use Event-carried immutable facts | PASS |
| Future/mismatched facts fail closed | Event payload identity, Project/Task and Verification Evidence checks | PASS |
| Stable context hash | Canonical semantic JSON plus `situation-rules/1.0`; unstable fields excluded | PASS |
| Canonical fingerprint | `situation-fingerprint/1.0`, SHA-256, Project/type/Task/components/failure | PASS |
| One active equivalent Situation | Partial unique `(project_id, fingerprint) WHERE status='OPEN'` | PASS |
| Create/update/supersede | PostgreSQL lifecycle tests and immutable `situation_versions` | PASS |
| Resolve does not reopen | Explicit authorized idempotent Resolve test | PASS |
| Duplicate Event idempotency | Inbox returns original Context/effect; concurrent duplicate test | PASS |
| Concurrent equivalent facts | PostgreSQL advisory lock plus convergence test | PASS |
| Gap-safe checkpoint | Gap park/drain test; checkpoint advances only contiguously | PASS |
| Atomic Event/Outbox/Inbox/checkpoint | Five pre-commit fault injections roll back every Situation effect | PASS |
| Runtime permission boundary | Worker/Verifier/Accounting/Control/Situation direct writes denied | PASS |
| Definer hardening | Dedicated `hermes_situation_owner` NOLOGIN; fixed `pg_catalog` search path; PUBLIC execute revoked | PASS |
| Cross-authority isolation | Situation runtime cannot mutate Project, Task or ResourceAccount | PASS |
| PostgreSQL 14 compatibility | Full discovery, 175 tests | PASS |
| PostgreSQL 16 compatibility | Full discovery, 175 tests | PASS |
| Original regression suite | Original 151 tests pass on both versions | PASS |

## Production Trigger Support

Supported using current authoritative producers:

- `verification.recorded` with authoritative `FAIL`;
- `task.readiness_recomputed` with a transition to `READY`;
- `budget.reserved`, `budget.settled`, `budget.released` at WARN/GATE/HARD_STOP;
- `feedback.created` bound to its immutable Feedback record.

Structured conflict rules are implemented but remain unavailable until a formal
producer emits the catalog Event. `policy.evaluated`, `resource.missing` and
`agent.stalled` intentionally fail closed because P1/P2 authorities do not yet exist.

## Open Questions

- Define a production reconcile policy for historical Events whose referenced
  authority records predate versioned snapshots.
- Define debounce/aggregation policy before admitting future high-frequency triggers.
- Introduce formal structured conflict producers before claiming that classification
  as production-complete.
