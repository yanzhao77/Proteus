# ADR-0049: P2 ExecutionRequest Preparation and Durable Queue Enqueue

## Status

ACCEPTED

## Phase

P2-2

## Context

P2-1 freezes Capability Match, WorkerTemplate revision, Context Bundle and
SandboxProfile facts, but a SelectedAction is still not runnable. V1.2 requires
`QUEUED` to mean that all execution inputs are frozen, ResourceReservation has
been handed off and a future Scheduler may safely attempt lease acquisition.

## Decision

P2-2 uses one PostgreSQL local transaction for `execution.prepare_request`.

The transaction validates the current Project/Task, DecisionRecord,
SelectedAction, ALLOW PolicyDecision, current RiskAssessment, ACTIVE
Selection-created ResourceReservation, Capability Match, exact WorkerTemplate
revision/availability version, immutable Context Bundle, immutable
`contract-only/1.0` SandboxProfile, current ACTIVE VerificationPlan, input
Artifact hashes and normalized lock intents.

On success it atomically inserts:

- immutable `execution_requests` with state `QUEUED` and request version `1`;
- one `execution_reservation_bindings` row for the P1 Reservation handoff;
- one pending `execution_queue_items` row;
- `execution.request_prepared` and `execution.queued` Events;
- matching Outbox rows;
- an APPLIED CommandReceipt.

P2-2 does not persist a cross-transaction runnable `PREPARING` state. Preparation
is a transaction-local phase. Any pre-commit failure rolls back Request, binding,
Queue item, Events, Outbox and Receipt finalization. Stable rejections may write
`execution_preparation_rejections` and a REJECTED CommandReceipt, but never an
effective Request or Queue item.

The queue is enqueue-side only. It exposes deterministic read ordering but no
claim/dequeue, Lease, fencing token, heartbeat, Worker dispatch, retry/requeue or
result/usage admission.

## Consequences

- FI-16 execution coupling is closed for Request/Queue/Reservation binding.
- P1 reservation balances are not debited a second time.
- Duplicate commands converge by idempotency key and canonical payload hash.
- Same Reservation or Decision/Action cannot create two effective Requests.
- Lock intents are normalized and frozen, but actual mutually exclusive lock or
  Lease acquisition remains P2-3.
- `SUCCEEDED != Task PASSED`; P2-2 creates no execution success state.

## Evidence

- `hermes-runtime/src/hermes_runtime/domain/execution.py`
- `hermes-runtime/src/hermes_runtime/application/executions.py`
- `hermes-runtime/src/hermes_runtime/infrastructure/postgres_execution.py`
- `hermes-runtime/migrations/0014_execution_request_queue.sql`
- `hermes-runtime/tests/test_execution_domain.py`
- `hermes-runtime/tests/test_execution_postgres.py`
- `hermes-runtime/tests/test_execution_permissions.py`
