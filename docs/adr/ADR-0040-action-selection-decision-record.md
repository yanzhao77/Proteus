# ADR-0040: Action Selection, Conflict Rules and Immutable DecisionRecord

- Status: ACCEPTED
- Phase: P1
- Related specifications: Core Runtime Design V1.2 §§11-14, 26, 30; Command/Event Protocol §§4-6; ADR-0036; ADR-0037; ADR-0038; ADR-0039

## Context

P1 needs to close the chain from current Situation through CandidateActions,
PolicyDecision and RiskAssessment into selected execution intent. Selection must
not become Scheduler, Worker routing, Human Gate, or mutable workflow state.

## Decision

P1 Slice 6 introduces the explicit `action_selection` actor and a
`SelectActions` command. The command carries command identity, idempotency key,
project, current PlanningRun, expected Situation version, expected Selection
version, weight profile, and explicit CandidateAction-to-ResourceAccount bindings
with expected account versions.

The command intentionally does not accept:

- caller-computed scores;
- caller-provided eligible or selected sets;
- caller-provided PolicyDecision or RiskAssessment results;
- caller-provided budget feasibility;
- generic status PATCH or mutable workflow instructions.

Selection reads authoritative upstream state and applies the fixed pipeline:

```text
Policy
-> Risk constraints
-> Budget feasibility
-> ActionScore
-> conflict/concurrency filtering
-> selected execution intent
```

`selection-conflict-rules/1.0` defines the first conflict model:

- max selected actions is `2`;
- clearly read-only actions may share targets;
- same mutable target conflicts;
- project-global mutation conflicts with other project mutation;
- unknown or missing write set fails closed as conflicting;
- ResourceAccount sharing is allowed only if the aggregate reservation is
  atomically feasible.

Selection persists immutable `decision_records`, candidate dispositions,
ActionScores, score dimensions and selected-action refs. The mutable
`selection_heads` row is only the current pointer/version for stale detection.
Every candidate is recorded exactly once as `FILTERED`, `ELIGIBLE_NOT_SELECTED`
or `SELECTED`. Empty selections still create a DecisionRecord with
`NO_ELIGIBLE_ACTION` or a more specific reason.

SelectedAction refs are immutable execution intent only. They are not
ExecutionRequest, queue item, lease, Worker assignment, Sandbox profile, or
Human Gate state.

## Consequences

- DENY cannot be overcome by high score.
- REQUIRE_HUMAN remains filtered until a real Human Gate authority exists; this
  slice does not forge Gate answers.
- Risk facts are mechanically checked against Policy constraints but never
  authorize the action.
- DecisionRecord is audit history, not mutable workflow state.
- Re-selection requires fresh expected Selection version unless the same
  canonical snapshot converges to an already active decision.
