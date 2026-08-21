# E5 Product API / Read Model Design

## Scope

E5 completes the **read-only Product API composition** required for Factory Home. It does not create a Production aggregate, lifecycle state machine, event store, scheduler, worker manager, execution command, verification authority, or browser-owned state. A user-facing Production is an existing Project viewed through a creator-scoped projection.

## Recon and reuse matrix

| Area | Existing capability | E5 disposition |
| --- | --- | --- |
| Product boundary | `ProductApiFacade` and verified FastAPI factory dispatch | Reused as the sole product read boundary. |
| Creator ownership | E4 `entry_approval_bridges` plus immutable `entry_approval_materialized_bindings` | Used as the primary materialized Project ownership fact; legacy initial user Project transition remains a conservative secondary fact. |
| Portfolio and Gate | `PostgresFactoryHomeReadModel`, `projects`, `human_gate_requests` | Completed as source-derived, creator-scoped projections. |
| Draft resume | E1 `PostgresEntryDraftStore.list/get` | Reused without duplicate draft projection. |
| Factory Status | No separate Factory lifecycle authority exists | Returned explicitly as `DEGRADED` with `UNKNOWN` module states; no health is inferred. |
| Production composition | `api_main.build_app()` PostgreSQL/OIDC composition | Configured `PostgresFactoryHomeReadModel` receives the real E1 Draft reader only when database and verified OIDC are configured. |
| Migration | Existing 0001–0030 schema and E4 ownership index | **No migration.** Existing source facts and indexes are sufficient. |

## Read contract

All Factory Home modules remain independent availability envelopes with `availability`, `reason`, `as_of`, `freshness`, `source`, and `source_version`. A degraded Portfolio or Gate source cannot erase the other module. The Production card has `progress: null` and `progress_basis: "NOT_AVAILABLE"`: E5 does not infer completion from worker claims, time, browser cache, or task state.

Creator scope requires a verified OIDC subject identical to the actor ID. It first selects E4 bridges owned by that subject with `MATERIALIZED` status and then accepts only the existing initial user Project transition as a legacy ownership fact. An absent or mismatched identity returns no scope. A project ID is never sufficient to grant access.

Gate results are summaries of real `human_gate_requests`; they expose a review link only. E5 adds no Gate decision or resume command. Draft listing delegates directly to E1 through the existing Product API path, so browser resume is sourced from server facts rather than local state.

## Boundary audit

The E5 read-model adapter contains SELECT-only PostgreSQL queries. It does not submit Project, Task, dependency, VerificationPlan, Worker, Scheduler, Execution, Gate, Evidence, or Recovery writes. `api_main` uses the same existing ControlPlane-backed E4 composition and only changes the read-model constructor wiring.
