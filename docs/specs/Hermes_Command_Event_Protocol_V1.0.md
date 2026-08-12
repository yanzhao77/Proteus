# Hermes Command and Event Protocol V1.0

**Status:** NORMATIVE DRAFT  
**Version:** 1.0.0  
**Related:** [Runtime Normative Specification](Hermes_Runtime_Normative_Spec_V1.0.md), [ADR index](../../ARCHITECTURE_DECISIONS.md)

## 1. Semantics

A `Command` requests a change and MAY be rejected. An `Event` records a committed fact and MUST be immutable. An `OutboxMessage` is the durable transport record for an Event. `Authoritative State` is mutable state owned by Control Plane. `Event Log` supports audit, recovery and projection rebuild; Hermes is NOT fully event sourced.

Commands MUST NOT be published as if they were facts. Consumers MUST NOT mutate authority from arbitrary Events; only explicit Command handlers may do so.

## 2. Command Envelope

```json
{
  "command_id": "cmd_01J001",
  "command_type": "task.submit_verification_outcome",
  "schema_version": "1.0",
  "project_id": "proj_001",
  "target": {"type": "task", "id": "task_102"},
  "idempotency_key": "verification:ver_001:apply:v1",
  "expected_version": 17,
  "actor": {
    "type": "control_plane_service",
    "id": "verification_outcome_handler",
    "authorization_context_ref": "authz_001"
  },
  "reason": "apply independently produced verification verdict",
  "correlation_id": "corr_task_102_attempt_1",
  "causation_id": "evt_verification_completed_001",
  "issued_at": "2026-08-12T10:14:01.000Z",
  "payload": {
    "verification_id": "ver_001",
    "artifact_hash": "sha256:..."
  }
}
```

Every authority-changing Command MUST contain `command_id`, `idempotency_key`, `expected_version`, `actor` and non-empty `reason`.

## 3. Actor model

`actor.type` MUST identify a user, Control Plane service, Scheduler service or recovery service. Authorization is evaluated for `command_type + target + scope`; possession of a valid identity alone is insufficient. Worker and Verification identities MAY submit their narrow result Commands but MUST NOT submit state transition Commands. Main Hermes MAY submit user intent or authenticated Gate Answer but MUST NOT impersonate the user.

## 4. Idempotency and CommandResult

Idempotency scope is `(project_id, command_type, idempotency_key)` unless an endpoint documents a narrower aggregate scope. The handler MUST persist a canonical request hash and CommandResult.

| Case | Required behavior |
| --- | --- |
| New key | execute once and persist result |
| Same key, same canonical payload | return the original result; do not re-run Guard or side effects |
| Same key, different payload/target/actor scope | reject `IDEMPOTENCY_CONFLICT`; no mutation |
| Same `command_id` with any different content | reject as integrity violation |

```json
{
  "command_id": "cmd_01J001",
  "status": "APPLIED",
  "result_code": "TASK_TRANSITIONED",
  "target_version": 18,
  "event_ids": ["evt_01J002"],
  "response": {"task_id": "task_102", "state": "PASSED"},
  "completed_at": "2026-08-12T10:14:01.020Z"
}
```

CommandRecord MUST be retained at least as long as clients may retry plus the maximum recovery/redrive window. Permanent authority and security Commands SHOULD retain their result for the project's audit retention. Purging MUST be recorded and MUST NOT allow a still-valid key to execute again.

## 5. Expected version

The handler MUST compare `expected_version` with authoritative entity version inside the write transaction. A mismatch returns `VERSION_CONFLICT` with current version and MUST NOT update state, graph, reservation, Event Log or Outbox. Clients MUST reload and replan; blind retry with a replaced version is forbidden.

## 6. Authoritative transaction

```text
BEGIN
  validate command schema and actor
  load idempotency record FOR UPDATE or attempt unique insert
  if matching completed record: return stored result
  if request hash conflicts: reject
  load authoritative entity
  compare expected_version
  evaluate State Machine Guard
  mutate authoritative entity / graph / reservation
  append immutable Event Log record
  insert Outbox Message for that Event
  store CommandResult
COMMIT
publish asynchronously
```

All steps through CommandResult MUST use one PostgreSQL local transaction. Event Log is included so audit cannot observe a state transition without its fact. No external broker, sandbox or HTTP call may occur inside this transaction.

## 7. Event Envelope

```json
{
  "event_id": "evt_01J002",
  "event_type": "task.passed",
  "schema_version": "1.0",
  "occurred_at": "2026-08-12T10:14:01.015Z",
  "recorded_at": "2026-08-12T10:14:01.018Z",
  "producer": {"type": "control_plane", "id": "task_state_machine"},
  "project_id": "proj_001",
  "task_id": "task_102",
  "correlation_id": "corr_task_102_attempt_1",
  "causation_id": "evt_verification_completed_001",
  "trace_id": "trace_01J001",
  "sequence": 185,
  "partition_key": "proj_001",
  "idempotency_key": "cmd_01J001:event:task.passed",
  "classification": "internal",
  "payload": {
    "from_state": "VERIFYING",
    "to_state": "PASSED",
    "verification_id": "ver_001",
    "artifact_hash": "sha256:...",
    "entity_version": 18
  }
}
```

Producer identifies the component that committed the fact. Worker-produced facts use `worker`, VerificationResult facts use `verification_engine`, and authority transition Events use `control_plane`.

## 8. Data relationship

```text
CommandRecord 1 ---- 0..N EventLog records
EventLog record 1 -- 1 OutboxMessage
OutboxMessage 1 ---- 0..N delivery attempts
Consumer 1 --------- 1 checkpoint per partition
```

The authoritative row references relevant Verification, Evidence or Decision IDs. Event payload copies only the fields needed for consumers and audit; it does not replace the authoritative row.

Required uniqueness: Command id; scoped idempotency key; Event id; `(partition_key, sequence)`; Outbox message id; `outbox.event_id`; consumer inbox `(consumer, event_id)`.

## 9. Outbox relay state machine

```text
PENDING -> LEASED -> PUBLISHED
   ^          |
   |          +-> PENDING (lease expiry / retryable failure)
   +--------------
PENDING/LEASED -> DEAD_LETTERED (attempt policy exhausted)
DEAD_LETTERED -> PENDING (authorized redrive)
```

Relay instances MUST claim batches using PostgreSQL atomic locking such as `FOR UPDATE SKIP LOCKED` or equivalent. Relay lease MUST expire. Publish success is followed by marking `PUBLISHED`; crash between them intentionally causes duplicate delivery.

Redrive MUST preserve `event_id`, payload, schema version, partition and sequence; it MUST add redrive attempt/audit metadata and MUST NOT create a logically new Event.

## 10. Delivery semantics

- Delivery is at least once.
- Consumers MUST be idempotent and persist inbox/dedup record with their effect.
- Logical ordering is guaranteed only within `partition_key`.
- Default project partition is `project_id`.
- A consumer MUST maintain durable checkpoint `(consumer_id, partition_key, last_contiguous_sequence)`.
- Publishing order SHOULD follow partition sequence; consumers still MUST handle duplicates and detectable gaps.

## 11. Duplicate, order and gap behavior

**Duplicate:** If `event_id` exists in consumer inbox, acknowledge and return the stored outcome without repeating effects.

**Out of order:** If sequence is greater than `checkpoint + 1`, park the Event in a bounded pending-gap store, request/backoff for missing sequence and do not advance contiguous checkpoint. Independent partitions continue.

**Missing:** After configurable timeout or retention lookup failure, emit an operational alert and route the affected partition to reconcile; MUST NOT silently skip a state-critical Event.

**Late:** A lower sequence not in inbox is processed only if the consumer declares commutative/backfill support; otherwise quarantine for reconcile. A lower sequence already in inbox is duplicate.

## 12. Schema evolution

Events MUST include `schema_version`. Compatible changes MAY add optional fields with safe defaults. Producers MUST NOT rename/remove fields or change meaning within a version. Unknown non-critical fields MUST be ignored and retained when forwarding where practical.

Unknown critical enum/state, unsupported major schema or missing required field MUST stop processing for that partition and enter schema quarantine/DLQ. Consumers MUST NOT map an unknown state to a default.

## 13. DLQ and redrive

DLQ record MUST contain Event, consumer, failure category, attempts, first/last failure time and trace. Poison data, unsupported schema and exhausted transient errors are distinct categories. Redrive requires authorization, resolved cause and an idempotent consumer. Successful redrive advances checkpoint only when all preceding sequences are accounted for.

## 14. Crash-point analysis

| Crash point | Durable result | Recovery behavior |
| --- | --- | --- |
| Before state update | no mutation | Command may retry |
| After state update, before Outbox insert | transaction rolls back | no visible mutation/Event |
| After Outbox insert, before commit | transaction rolls back | no visible mutation/Event |
| After commit, before publish | state/Event/Outbox durable | relay publishes PENDING row |
| After publish, before mark published | consumer may receive duplicate | relay republishes; inbox deduplicates |
| Consumer effect committed, before checkpoint | effect and inbox MUST be atomic; checkpoint lags | redelivery returns stored outcome; checkpoint catches up |

If a consumer cannot atomically commit effect and inbox, it MUST use an idempotent target operation and document compensation; it cannot claim exactly-once semantics.

## 15. Checkpoint and replay

Replay reads Event Log or retained transport events to rebuild Projection, audit, or recover after Snapshot. It MUST use the same idempotent consumer semantics. Replay MUST NOT overwrite newer authoritative state and MUST NOT bypass Command Guard. Reconcile compares replay result with authority and emits explicit recovery Commands.

## 16. Forbidden implementations

- State update and Outbox insert in separate transactions.
- Publish-before-commit.
- Best-effort in-memory Event queue as the only Outbox.
- Consumer effect without durable deduplication.
- Global ordering claims across partitions.
- Advancing checkpoint across a missing critical sequence.
- Reusing an Idempotency-Key with different payload.
- Treating Event as a generic state mutation instruction.
- Rebuilding all authoritative state solely by folding Event Log as the normal write model.
- Cross-database distributed transaction as an MVP prerequisite.

## 17. Acceptance criteria

The protocol conforms only if CT-001 and FI-01 through FI-08, FI-18 through FI-20 in [Conformance Test Specification](Hermes_Conformance_Test_Spec_V1.0.md) pass at their required test level. Database constraints and crash tests MUST prove no state-without-Outbox commit, idempotent CommandResult, duplicate-safe consumption, gap handling and fail-closed schema behavior.

## 18. Open questions

- Outbox retention and archival duration.
- Maximum gap wait and partition pause policy.
- Broker choice, if a broker becomes necessary.
- Canonical JSON hashing rules and schema validation technology.
