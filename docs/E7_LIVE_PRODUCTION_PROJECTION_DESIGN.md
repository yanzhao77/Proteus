# E7 Live Production Projection Design

## Scope

E7 creates a **read-only, source-derived Live Production projection**. A Live Production remains the existing E4-materialized Project. E7 does not create a Production authority, lifecycle state machine, event store, intervention plane, runtime pause/resume/stop capability, retry path, worker reassignment path, Task mutation, Plan mutation, or direct Gate decision.

## API contract

| Endpoint | Semantics | Authentication and scope |
| --- | --- | --- |
| `GET /factory-home/productions/{project_id}/live` | Returns a bounded point-in-time snapshot with a snapshot watermark. | Existing FastAPI verified OIDC dispatch; E4 creator scope determines visibility. |
| `GET /factory-home/productions/{project_id}/live-feed?after={cursor}&limit={n}` | Returns an ordered bounded page after an existing `event_log.sequence` cursor; `limit` is capped at 100. | Same verified OIDC dispatch and creator scope. |

The event endpoint is named `live-feed`, not a generic events API. Generic event endpoints remain unavailable. A cursor ahead of the current watermark is explicitly `STALE`; a cursor predating the retained first Project event is `STALE` with an expired-cursor reason. The client must rehydrate from snapshot before treating the projection as current.

## Projection sources

| Projection area | Existing authority source | E7 presentation rule |
| --- | --- | --- |
| Identity, master plan and materialization map | E4 bridge and immutable materialized binding | An E4 `MATERIALIZED` binding is required. |
| Project state and version | `projects` | Direct source fact. |
| Workflow | `tasks`, `task_dependencies`, frozen E4 blueprint | Task nodes and DAG edges carry source identity/version; blueprint does not cause browser-created tasks. |
| Execution / run / lease | execution current state, `agent_runs`, `execution_leases` | Fencing token is not selected or exposed. Completion claim never becomes verified completion. |
| Verification / evidence | verification plan/result and evidence/artifact facts | Invalidated evidence is explicit; it is never represented as green PASS. |
| Gates / waiting | human gate and waiting records | Summary and existing detail navigation only; no decision command. |
| Recovery | reconcile findings scoped to Project | Summary only. |
| Incremental updates | existing `event_log` | Allowlisted envelope excludes raw payload and uses existing numeric sequence; no second event table. |

The adapter returns only stable identifiers, selected statuses, versions, timestamps, safe artifact metadata, safe event metadata and explicit availability/freshness. It does not expose lease or fencing values, credentials, authorization headers, DSNs, raw worker environment, raw event payload, artifact location, or raw Draft idea content.

## Browser reconciliation

The browser loads snapshot first and retains its watermark. It then requests the bounded feed after that watermark, deduplicates by `event_id`, and displays a read-only timeline. A non-current feed changes connection state to `STALE` and increments a rehydration generation, which causes a new snapshot request. The browser does not store or update authority state. Pending controls are omitted rather than rendered as successful runtime actions.
