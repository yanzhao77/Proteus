# P1 Slice 3 Diagnosis Engine Acceptance Matrix

Scope: deterministic Diagnosis Engine only. Planner, Policy, Risk, Action
Selection, ExecutionRequest, Scheduler, Human Gate, LLM diagnosis and vector
history matching are intentionally out of scope.

| Requirement | Evidence | Result |
| --- | --- | --- |
| Exact Situation version binding | `RunDiagnosis.situation_version`; `hermes_apply_diagnosis` locks `situations` and rejects stale versions | PASS |
| Frozen AnalysisContext hash binding | `RunDiagnosis.analysis_context_hash`; DB rejects mismatch | PASS |
| Observed-sequence boundary | Evidence `observed_at_sequence`; future Evidence rejected | PASS |
| Deterministic rule registry | `diagnosis-rules/1.0` in `domain/diagnosis.py`; stable input hash tests | PASS |
| `UNKNOWN + root_cause NULL` | Domain and PostgreSQL tests persist unknown without fake root cause | PASS |
| Supporting/Contradicting Evidence refs | `diagnosis_evidence(relation, reason_code)` and domain contradiction downgrade | PASS |
| Finding normalization | `CanonicalFinding` stores stable finding code/source/check/artifact refs | PASS |
| Immutable Diagnosis history | immutable triggers on Diagnosis tables | PASS |
| Idempotent retry | same idempotency key/payload returns same Diagnosis | PASS |
| Idempotency conflict | same key/different payload rejects with `DIAGNOSIS_IDEMPOTENCY_CONFLICT` | PASS |
| Concurrent duplicate Diagnosis | two connections create one equivalent Diagnosis | PASS |
| Current pointer safety | `current_diagnoses` updated only in guarded authority function | PASS |
| Diagnosis does not mutate other authority | tests compare Situation/Task before/after; permissions deny direct mutation | PASS |
| Event/Outbox/Receipt atomically committed | successful test checks Diagnosis, Event, Outbox, CommandReceipt | PASS |
| Fault injection rollback | seven pre-commit fault points roll back all Diagnosis effects | PASS |
| PostgreSQL permissions | dedicated `hermes_diagnosis_owner/runtime`, no PUBLIC execute, direct writes denied | PASS |
| PostgreSQL 14 full regression | `Ran 200 tests ... OK` | PASS |
| PostgreSQL 16 full regression | `Ran 200 tests ... OK` | PASS |

Implemented rules in `diagnosis-rules/1.0`:

- `rule.artifact_hash_mismatch.v1`
- `rule.test_assertion_failure.v1`
- `rule.build_failure.v1`
- `rule.dependency_unavailable.v1`

Known GAP, explicitly deferred:

- embedding/vector history matching;
- LLM/root-cause synthesis;
- full Evidence retention/invalidation lifecycle beyond minimal observed-sequence metadata;
- Planner conversion of Hypotheses/Evidence Requests into CandidateAction;
- Policy/Risk/ExecutionRequest/Scheduler/Human Gate integration.
