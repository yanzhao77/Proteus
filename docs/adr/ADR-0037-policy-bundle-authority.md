# ADR-0037: Policy Bundle Authority and Constraint Merge

- Status: ACCEPTED
- Phase: P1
- Related specifications: Core Runtime Design V1.2 §§11, 14, 23, 26, 28, 30; Command/Event Protocol §§4-6; ADR-0036

## Context

Policy evaluates whether a current CandidateAction may proceed to later Risk,
Budget and Selection checks, must be denied, or needs human authorization. If
Policy defaults to allow, lets lower-priority rules override emergency/system
denies, or stores free-text constraints as machine authorization, later Selection
could execute actions outside V1.2 authority boundaries.

## Decision

`policy-bundle/1.0` and `policy-rules/1.0` define the first deterministic Policy
Bundle. The modeled hierarchy is:

```text
runtime_emergency -> system -> project -> user -> task -> tool_sandbox
```

Merge semantics are conservative:

1. all applicable rules participate;
2. any DENY wins;
3. otherwise any REQUIRE_HUMAN wins;
4. ALLOW is possible only when all mandatory rules allow;
5. constraints are intersected and can only tighten;
6. no applicable rule fails closed to DENY;
7. emergency freeze cannot be overridden.

PolicyDecision binds to exact current PlanningRun/CandidateAction, Situation
version, AnalysisContext hash, optional Diagnosis input hash, Candidate registry
version and Policy Bundle version. `ALLOW` only means the Candidate may enter
later Risk/Budget/Selection checks; it is not execution authorization.

`REQUIRE_HUMAN` records an authorization gap but does not create a Human Gate.

## Consequences

- Planner confidence/progress/evidence gain cannot override DENY.
- Policy runtime cannot mutate CandidateAction, PlanningRun, Project, Task,
  Situation, ResourceAccount, Human Gate or execution state.
- Policy constraints are typed (`network_access`, `filesystem_write`,
  `secret_access`, `production_access`, `max_risk_level`, and related limits).
- Unknown mandatory constraints fail closed.
- Budget feasibility, ActionScore, Selection, DecisionRecord, Human Gate lifecycle
  and ExecutionRequest remain future slices.
