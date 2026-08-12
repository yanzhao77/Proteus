# ADR-0015: At-Least-Once Delivery with Idempotent Consumers

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Command/Event Protocol §§9-13](../specs/Hermes_Command_Event_Protocol_V1.0.md#9-outbox-relay-state-machine)

## Context

Relay crashes make duplicate publication unavoidable without distributed transactions.

## Decision

Events use at-least-once delivery, project partition ordering, durable consumer inbox/checkpoint, gap detection and authorized DLQ redrive.

## Alternatives Considered

Exactly-once claims and best-effort delivery; rejected as misleading or lossy.

## Consequences

Every consumer effect must be idempotent/deduplicated.

## Validation

CT-001 and FI-03-05, FI-18-20.

## Open Questions

Broker choice and gap timeout.
