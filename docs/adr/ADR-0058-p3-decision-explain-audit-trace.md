# ADR-0058: P3 Immutable Decision Explain, Audit and Trace

## Status

ACCEPTED

## Phase

P3-0

## Context

V1.2 requires every Decision to be traceable and explainable. Recomputing an
explanation later with new model, rule, policy or compiler versions would create
false history.

## Decision

P3 Explain uses immutable snapshots or immutable references to versioned facts
captured at decision time. It must answer why a Situation was produced, why a
Diagnosis and Action were selected, which alternatives were rejected, how Policy,
Risk and Budget affected selection, why a WorkerTemplate was chosen, why Human
Gate was required, who approved/rejected, which Evidence and model/rule/compiler
versions were used, which Command/Event changed state, how resources settled,
which Lease/token/Run produced a Result and how quarantine was handled.

Every explain/audit record carries correlation ID, causation ID, trace ID,
project/task/decision/request/run refs, redaction class, retention policy and
query authorization scope. Metrics are not authority. Missing trace links are
reported as missing and cannot be fabricated.

## Consequences

Auditors can reproduce the decision lineage as it was known at the time.
Observability backends such as OpenTelemetry remain an implementation choice,
not a P3-0 architectural dependency.

## Evidence

- [P3 Operational Governance Spec §10](../specs/Hermes_P3_Operational_Governance_Normative_Spec_V1.0.md#10-decision-explain-audit-and-trace)
- [P3 Acceptance Matrix](../P3_OPERATIONAL_GOVERNANCE_ACCEPTANCE_MATRIX.md)
