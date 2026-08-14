# ADR-0027: Outbox Relay Lease, Delivery DLQ and Authorized Redrive

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Command/Event Protocol §§9-14](../specs/Hermes_Command_Event_Protocol_V1.0.md#9-outbox-relay-state-machine)

## Context

The initial Outbox recorded only `PENDING | PUBLISHED | DEAD_LETTERED` and `published_at`. It had no atomic concurrent claim, expiring ownership, stale publisher isolation, retry policy or authorized recovery path.

## Decision

The delivery state machine is:

```text
PENDING -> LEASED -> PUBLISHED
LEASED -> PENDING on retryable failure or expiry takeover
PENDING/LEASED -> DEAD_LETTERED on policy exhaustion or poison failure
DEAD_LETTERED -> PENDING only through authorized RedriveOutbox
```

Relay claims use a short PostgreSQL transaction with `FOR UPDATE SKIP LOCKED`. Each claim receives a new opaque token and expiry. Publish occurs after the claim commits, without a database row lock. Published/failure acknowledgements conditionally match message, `LEASED`, owner and claim token, so an expired publisher cannot overwrite the new owner.

Delivery is at least once. A publish success followed by a crash before `PUBLISHED` marking intentionally permits the next Relay to publish the same Event again. Consumer Inbox uniqueness, not the Relay, prevents duplicate business effects.

Delivery attempts and DLQ metadata are durable and preserve the immutable Event envelope. Authorized Redrive requires Control Plane or System Operator identity, reason, authorization reference, resolved-cause assertion, expected status version and idempotent CommandReceipt. Redrive preserves Event identity and opens a new attempt window; it does not create a new logical Event.

## Consequences

Broker exactly-once behavior is neither required nor claimed. Operational policy must choose retry limits, backoff and retention. Redrive is auditable but cannot force a consumer checkpoint across an unresolved partition gap.

## Validation

Tests cover concurrent claims, `SKIP LOCKED`, expiry takeover, stale tokens, retry and exhaustion, non-retryable DLQ, publish-before-mark duplicate delivery, authorized/idempotent redrive and real non-superuser Relay/Consumer/Operator roles on PostgreSQL 14 and 16.

## Open Questions

Production transport choice, retention/archival, operator identity provider, adaptive retry policy and payload classification/redaction policy remain open.
