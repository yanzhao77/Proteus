# ADR-0061: P3-2 PostgreSQL Checkpoint Replay and Reconcile Runtime Authority

## Status

ACCEPTED

## Phase

P3-2

## Context

ADR-0055 defined the P3 Checkpoint, Replay and Reconcile boundary. P3-2 needs a
runtime implementation that can recover consumer/read-model continuity after
checkpoint loss, corruption, gaps and replay failures without converting Hermes
into a full Event Sourcing system.

The existing P0/P1/P2 stack already owns authoritative Project, Task,
Verification, Lease, Worker execution and Resource Accounting writes through
guarded semantic Commands. Replay/Reconcile must therefore be an operational
authority overlay on Event Log, Outbox, Inbox and Checkpoint facts, not a new
authority writer.

## Decision

Implement P3-2 in PostgreSQL migration
`0019_checkpoint_replay_reconcile.sql` with three narrow authority surfaces:

- `hermes_replay_runtime` may request, execute and activate replay sessions.
- `hermes_reconcile_runtime` may observe mismatches and create immutable
  dry-run/apply plans.
- `hermes_reconcile_apply_runtime` may apply only whitelisted repair actions.

Consumer checkpoints are extended with stream, generation, consumer version,
schema version, projection digest, checkpoint hash and checkpoint version. A
checkpoint trigger recomputes canonical hashes and rejects rewind. Immutable
checkpoint history records preserve the audit chain.

Replay creates isolated target generations and shadow projection rows. It
processes retained Event ranges by stable partition sequence, fails closed on
gaps or unsupported schema, and atomically activates a verified generation by
switching a generation pointer. Replay never folds historical Events into
Project, Task, Accounting, Lease, Verification, ExecutionRequest or Worker
authority tables.

Reconcile is separated into:

```text
Observe -> Finding -> Plan -> Authorized Apply
```

Findings cover checkpoint corruption/ahead, Event gaps, missing Outbox, Inbox
effect mismatches, effect-without-checkpoint, unsupported schema and pending
DLQ. Plans bind finding IDs, finding versions, observed versions, proposed
repair actions, actor, authorization, expiry and canonical plan hash.

The initial apply implementation permits only the safe checkpoint repair:

```text
ADVANCE_CHECKPOINT_IF_EFFECT_CONTIGUOUS
```

It advances a checkpoint only when Inbox/effect continuity proves every
intermediate sequence has already committed. Other whitelisted actions remain
planned/blocked until their owning guarded Commands are implemented.

## Consequences

FI-12A through FI-12G are now testable as operational recovery scenarios:
checkpoint damage/loss, duplicate Event, Event gap, reconcile dry-run/apply and
authority protection. Reconcile can surface and plan broader mismatches without
pretending unsupported repairs succeeded.

External irreversible side-effect reconciliation, stale Result quarantine
adoption/redrive, Evidence invalidation propagation, Decision Explain query
models and production sandbox/process management remain later P3 slices.

## Evidence

- [`0019_checkpoint_replay_reconcile.sql`](../../hermes-runtime/migrations/0019_checkpoint_replay_reconcile.sql)
- [`replay_reconcile.py`](../../hermes-runtime/src/hermes_runtime/domain/replay_reconcile.py)
- [`application/replay_reconcile.py`](../../hermes-runtime/src/hermes_runtime/application/replay_reconcile.py)
- [`postgres_replay_reconcile.py`](../../hermes-runtime/src/hermes_runtime/infrastructure/postgres_replay_reconcile.py)
- [`test_replay_reconcile_domain.py`](../../hermes-runtime/tests/test_replay_reconcile_domain.py)
- [`test_replay_reconcile_postgres.py`](../../hermes-runtime/tests/test_replay_reconcile_postgres.py)
- [`test_replay_reconcile_permissions.py`](../../hermes-runtime/tests/test_replay_reconcile_permissions.py)
