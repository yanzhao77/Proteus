# ADR-0070: P5 Supervised Runtime Services

## Status

ACCEPTED

## Phase

P5-0/P5-2

## Context

P0-P4 provide one-shot services and authority adapters. A deployable product
needs long-running loops, but loops can easily become hidden business logic or
incorrect in-process distributed coordination.

## Decision

Implement a bounded supervisor that runs independent service roles for relay,
consumer/checkpoint, scheduler/lease, Docker worker execution and reconcile
polling. Each loop has an explicit batch limit, poll interval, exponential
backoff with jitter, maximum concurrency, cancellation and readiness state.

The supervisor may schedule existing use cases but must not copy business
decision logic or repair arbitrary authority. Multi-instance correctness remains
the responsibility of PostgreSQL lease/fencing/idempotency.

## Consequences

Single-node Hermes can run continuously while preserving crash visibility and
least-authority service boundaries. Loop failure degrades readiness rather than
silently spinning.
