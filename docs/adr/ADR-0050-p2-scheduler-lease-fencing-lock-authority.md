# ADR-0050: P2 Scheduler Lease, Fencing and Lock Authority

## Status

ACCEPTED

## Phase

P2-3

## Context

P2-2 stores immutable `QUEUED` ExecutionRequest and Queue snapshots. Those rows
prove admission and enqueue facts, but their `request_state` and `queue_state`
columns are intentionally immutable. P2-3 needs real cluster scheduling:
multiple Scheduler instances must atomically claim eligible Queue items, acquire
all execution lock scopes, receive a monotonic fencing token, renew ownership,
allow PostgreSQL-clock expiry takeover and safely relinquish/requeue without
touching Worker lifecycle or Result admission.

## Decision

P2-3 adds a separate Scheduler authority instead of mutating the immutable P2-2
snapshot tables.

Current scheduling state lives in:

- `execution_request_current_states`;
- `execution_queue_current_states`;
- `execution_leases` plus `execution_lease_state_history`;
- `execution_fencing_counters`;
- `execution_lock_ownerships`;
- `scheduler_instances` and `scheduler_lease_profiles`.

The default MVP Lease profile is versioned as `p2-default` / `1`:

- `initial_ttl_ms = 30000`;
- `renew_interval_ms = 10000`;
- `max_extension_ms = 30000`;
- `max_lifetime_ms = 300000`;
- `takeover_after_expiry_ms = 0`;
- `requeue_backoff_ms = 0`;
- `max_acquisition_batch = 1`.

All durations are integer milliseconds, bounded by database checks and recorded
on the granted Lease through `profile_id/profile_version`. Scheduler callers may
choose an existing profile but cannot supply arbitrary TTLs or fencing tokens.

Scheduler holder identity is admitted through `scheduler.register` and is not
free text at claim time. A current holder is the tuple:

```text
project_id + scheduler_id + scheduler_session_id + actor_type=scheduler + actor_id
```

Queue claim ordering is best effort, not strict global fairness:

```text
priority DESC -> available_at ASC -> enqueued_at ASC -> queue_item_id ASC
```

The claim transaction uses `FOR UPDATE SKIP LOCKED` only on Scheduler current
queue rows. If a head item is locked by another transaction or has active lock
scope conflicts, the Scheduler may scan the next eligible item. Starvation
monitoring and operational remediation remain P3.

Fencing tokens are allocated only by PostgreSQL in `execution_fencing_counters`.
They are monotonic per ExecutionRequest, renew keeps the same token, rollback
does not commit a token, requeue does not reset the counter, and overflow fails
closed. P2-3 exposes `hermes_validate_current_lease(...)` only as a validation
primitive for P2-4; it does not admit Worker Results.

Execution locks use the ADR-0045 vocabulary exactly:

- `repository`;
- `workspace`;
- `branch_ref`;
- `artifact_namespace`;
- `external_environment`;
- `deployment_target`.

Locks are acquired in canonical kind order and stable scope order in the same
transaction as Lease grant. Ownership is bound to `lease_id` and
`fencing_token`; lock expiry never exceeds Lease expiry. Expired or relinquished
locks no longer block a later legal Lease; takeover replaces expired ownership
atomically.

`scheduler.acquire_lease`, `scheduler.renew_lease` and
`scheduler.relinquish_lease` all write authoritative state, Event Log, Outbox
and CommandReceipt in one PostgreSQL transaction. Relinquish returns the current
request and queue state to `QUEUED`/`PENDING` and keeps the P1
ResourceReservation active and bound; it does not settle or release resources.

P2-3 intentionally does not implement Worker spawn, P2 AgentRun lifecycle,
`RUNNING`, Result/Usage/CompletionClaim admission, stale Result quarantine,
business retry, Human Gate, real Docker/Process sandbox, Kafka, Redis or
Kubernetes.

## Consequences

- P2-2 immutable snapshots remain valid audit facts while Scheduler current
  tables own `QUEUED <-> LEASED` authority.
- CT-002 is closed by two independent Scheduler connections competing for the
  same Queue item and observing exactly one current Lease owner/token.
- `P2-LOCK-001` is closed for actual scope conflict detection, atomic all-lock
  acquisition, expiry/takeover and relinquish release.
- FI-10 and FI-11 are closed only for Scheduler/Lease expiry, stale owner/token
  renew rejection, takeover and pre-commit crash rollback. Result/Usage
  rejection/quarantine remains P2-4/P3.
- CT-003 remains partial: token generation and validation are present, but stale
  Result durable quarantine and Task-state isolation are later slices.

## Evidence

- `hermes-runtime/migrations/0015_scheduler_lease_fencing.sql`
- `hermes-runtime/src/hermes_runtime/domain/scheduler.py`
- `hermes-runtime/src/hermes_runtime/application/scheduling.py`
- `hermes-runtime/src/hermes_runtime/infrastructure/postgres_scheduler.py`
- `hermes-runtime/tests/test_scheduler_domain.py`
- `hermes-runtime/tests/test_scheduler_postgres.py`
- `hermes-runtime/tests/test_scheduler_permissions.py`
