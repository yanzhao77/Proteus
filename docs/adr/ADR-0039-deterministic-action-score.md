# ADR-0039: Deterministic ActionScore and Conservative Defaults

- Status: ACCEPTED
- Phase: P1
- Related specifications: Core Runtime Design V1.2 §§13, 14, 26, 30; Command/Event Protocol §§4-6; ADR-0036; ADR-0037; ADR-0038

## Context

Action Selection must rank current CandidateActions without becoming an
authorization authority. If scoring accepts caller-provided scores, uses floats,
uses hidden history, or ranks DENY/REQUIRE_HUMAN candidates, it can override
Policy and Risk boundaries.

## Decision

`selection-weight-profile/1.0` and `selection-normalizer/1.0` define the first
deterministic ActionScore model. The model uses integer basis points only, clamps
all normalized dimensions to `0..10000`, and records raw dimensions,
normalized dimensions, weights, contributions, score input hash and explanation
reason codes.

The eight dimensions are:

- `expected_progress`
- `confidence`
- `evidence_gain`
- `reversibility`
- `risk`
- `cost`
- `time`
- `historical_success`

The first profile weights are:

| Dimension | Weight |
| --- | ---: |
| `expected_progress` | `1800` |
| `confidence` | `1200` |
| `evidence_gain` | `1600` |
| `reversibility` | `900` |
| `risk` | `-1600` |
| `cost` | `-900` |
| `time` | `-600` |
| `historical_success` | `400` |

The score formula is:

```text
contribution[dimension] = normalized_basis_points * weight / 10000
final_score = clamp(sum(contribution), 0, 10000)
```

`time` is normalized from the `execution_time_ms` estimate against a one-hour
profile ceiling. `cost` is normalized from the maximum per-dimension ratio
between the candidate estimate and the locked ResourceAccount limit. Risk uses
RiskAssessment residual risk basis points as a negative factor.

There is no formal historical-success authority in P1 Slice 6. The profile
therefore uses `DEFAULT_NO_HISTORY = 3500` basis points, records
`DEFAULT_NO_HISTORY` in score metadata, and keeps the weight intentionally low.
It does not invent or silently zero historical data.

Tie-break ordering is stable:

```text
higher final score
-> lower residual risk
-> higher reversibility
-> lower normalized cost
-> stable action_id
```

Policy DENY and REQUIRE_HUMAN candidates are filtered before score creation.

## Consequences

- Caller-provided score, selected refs, eligibility or `budget_ok` are ignored by
  design because the command does not accept them.
- Identical input snapshots produce identical ActionScore IDs, score input hashes
  and ranking order.
- ActionScore is evidence for Selection, not authorization and not execution
  state.
- A future historical-success authority must replace `DEFAULT_NO_HISTORY` through
  a new versioned profile.
