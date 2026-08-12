# ADR-0026: Partition-Local Event Sequence and Contiguous Consumer Checkpoint

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Command/Event Protocol §§10-12,15](../specs/Hermes_Command_Event_Protocol_V1.0.md#10-delivery-semantics)

## Context

The initial P0 schema used one global PostgreSQL identity as `event_log.sequence`. Consumers then advanced a per-Project checkpoint with `GREATEST(last_sequence, received_sequence)`. Events from other Projects created false gaps, while out-of-order delivery could silently move a checkpoint past a missing Event.

## Decision

Protocol ordering uses `UNIQUE(partition_key, sequence)`. A row-locked `event_partition_sequences` counter allocates the next sequence inside the authoritative Event transaction. The former global identity remains only as `global_sequence`, an internal migration-order key with no delivery-order semantics.

Consumer checkpoints mean `(consumer_id, partition_key, last_contiguous_sequence)`. Only `checkpoint + 1` may apply an effect and advance the checkpoint. Higher sequences enter `consumer_pending_gaps` without an effect; arrival of the missing Event drains parked Events in sequence. A lower sequence with no Inbox record is quarantined unless a future consumer explicitly declares commutative backfill support.

For the current test-only data baseline, migration deterministically numbers existing Events by former global insertion order within each partition and rebuilds checkpoints from the proven contiguous Inbox prefix. A production system that has already externally published global sequence values requires a separately planned compatibility window; this migration does not claim to preserve those values as partition-local cursors.

## Consequences

Independent Projects progress independently, consumers cannot skip gaps, and replay uses the same Inbox/checkpoint rules. The allocator is a per-partition PostgreSQL contention point by design and does not provide global Event ordering.

## Validation

PostgreSQL tests cover independent partitions, atomic allocation constraints, `1 -> park 3 -> receive 2 -> drain 3`, duplicate and late delivery, consumer crash rollback, and reconcile that advances only a proven contiguous Inbox prefix.

## Open Questions

Production compatibility for previously published global cursors, gap retention duration, maximum parked rows per partition and commutative backfill registration remain open.
