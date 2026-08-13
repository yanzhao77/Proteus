# ADR-0034: Canonical Situation Fingerprint and Guarded Lifecycle

- Status: ACCEPTED
- Phase: P1
- Related specifications: Core Runtime Design V1.2 §§8, 21, 26, 28, 30

## Context

At-least-once delivery and concurrent consumers can present duplicate or equivalent
facts. A Python lookup followed by insert cannot guarantee one active Situation and
does not preserve lifecycle history.

## Decision

`situation-fingerprint/1.0` computes SHA-256 over Project ID, Situation type,
optional Task ID, sorted/deduplicated affected components and structured causal
failure. Event ID, timestamps, Evidence ordering and random identifiers are excluded.

PostgreSQL enforces one `OPEN` row per `(project_id, fingerprint)` with a partial
unique index. The authority function also takes a transaction-scoped advisory lock
for `(project_id, task_id, situation_type)`, so equivalent updates and semantic
supersedes serialize without a process-local lock.

An equivalent fact updates the current row, increments its expected version and
merges stable references. A changed fingerprint in the same lifecycle scope creates
a new `OPEN` row and atomically marks the prior row `SUPERSEDED`. Each change appends
an immutable `situation_versions` snapshot. `RESOLVED` is only entered by an explicit,
authorized, idempotent command and ordinary analysis cannot reopen it.

Situation, Situation Event, Outbox, Consumer Inbox/effect and contiguous Checkpoint
commit in one PostgreSQL transaction. Delivery remains at least once; this decision
does not claim distributed exactly once.

## Consequences

- Duplicate delivery cannot create a second effect or version.
- Concurrent equivalent Events converge on one active Situation without lost refs.
- `SUPERSEDED` and `RESOLVED` retain distinct meanings.
- The analyzer emits facts only; it does not diagnose, plan, reserve resources,
  create an ExecutionRequest or mutate Project/Task state.
