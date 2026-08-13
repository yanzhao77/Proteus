# ADR-0038: Deterministic Risk Model Authority

- Status: ACCEPTED
- Phase: P1
- Related specifications: Core Runtime Design V1.2 §§12, 14, 26, 28, 30; Command/Event Protocol §§4-6; ADR-0036; ADR-0037

## Context

Risk evaluates impact, not authorization. If Risk emits ALLOW/DENY, edits Policy,
or treats unverified mitigations as complete, it can silently bypass the Policy
authority and create false execution safety.

## Decision

`risk-model/1.0` and `risk-rules/1.0` define a deterministic integer model over
ten factors:

- `environment`
- `data_impact`
- `irreversibility`
- `privilege`
- `blast_radius`
- `network_exposure`
- `secret_exposure`
- `supply_chain`
- `rollback_confidence`
- `worker_or_tool_trust`

All factor scores, weights, final score and residual risk use `0..10000` basis
points. Risk level is mechanically mapped:

```text
LOW      [0, 2500)
MEDIUM   [2500, 5500)
HIGH     [5500, 8000)
CRITICAL [8000, 10000]
```

Missing key inputs use conservative defaults; for example unknown environment is
not treated as zero risk. Mitigations lower residual risk only when represented
by verified authoritative refs supplied to the Risk command. Required mitigations
are not considered completed merely because the model lists them.

RiskAssessment binds to exact current PlanningRun/CandidateAction, Situation
version, AnalysisContext hash, optional Diagnosis input hash, Candidate registry
version and Risk Model version.

## Consequences

- RiskAssessment never outputs ALLOW, DENY, REQUIRE_HUMAN, eligible, selected,
  queued, leased or execution authorization.
- Risk cannot alter PolicyDecision or loosen Policy constraints.
- Policy DENY remains DENY regardless of Risk score.
- Budget feasibility, ActionScore and final risk-vs-policy-boundary filtering
  remain Slice 6 concerns.
