# ADR-0035: Deterministic Diagnosis Rule Authority

- Status: ACCEPTED
- Phase: P1
- Related specifications: Core Runtime Design V1.2 §§9, 19-21, 25-28, 30; Command/Event Protocol §§4-6

## Context

Diagnosis answers why an `OPEN` Situation failed, or whether the cause is still
unknown. If Diagnosis reads mutable latest state, copies worker self-report, or
uses unconstrained text inference, it can fabricate a root cause and mislead later
Planner work.

## Decision

`diagnosis-rules/1.0` is a deterministic rule registry over normalized structured
Findings and authoritative Evidence references. Each Diagnosis binds exactly to
one `situation_id`, current `situation_version`, immutable `analysis_context_id`,
`analysis_context_hash`, `observed_at_sequence`, rule-set version and `input_hash`.
Only facts visible at or before the AnalysisContext observed sequence may
contribute to input hash or confidence.

The PostgreSQL Diagnosis authority stores immutable `diagnoses`,
`diagnosis_findings`, `diagnosis_evidence`, `diagnosis_hypotheses` and
`diagnosis_evidence_requests`. A guarded `current_diagnoses` pointer may advance
only through `hermes_apply_diagnosis`. A successful command commits Diagnosis,
Evidence relations, Hypotheses, Evidence Requests, `diagnosis.completed` Event,
Outbox message and CommandReceipt in one local transaction.

`UNKNOWN` with `root_cause = NULL` is a valid result. `CONFIRMED` requires a known
structured Finding and direct valid Evidence in the same Project/Task/Artifact
scope. `PROBABLE` is allowed only for rules that explicitly tolerate missing
direct Evidence and must emit Hypotheses/Evidence Requests. Contradicting Evidence
forces conservative downgrade to `UNKNOWN` in this rule set.

## Consequences

- Diagnosis does not modify Situation, Project, Task, Artifact or Evidence.
- Worker self-report cannot become a supporting Diagnosis fact.
- Duplicate and concurrent equivalent diagnosis requests converge on one immutable
  Diagnosis row.
- Evidence content is not copied into Diagnosis; only stable references and reason
  codes are persisted.
- LLM diagnosis, vector history matching, Planner, Policy, Risk, ExecutionRequest
  and Human Gate remain future slices.
