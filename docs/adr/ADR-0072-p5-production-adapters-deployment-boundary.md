# ADR-0072: P5 Production Adapters and Deployment Boundary

## Status

ACCEPTED

## Phase

P5-0/P5-4/P5-5/P5-6

## Context

P4 local adapters prove product boundaries, but deployable single-node Hermes
needs production-compatible Artifact, Secret and Telemetry adapters plus a
repeatable deployment/operations baseline.

## Decision

Use one production-compatible target per adapter category:

- S3-compatible Artifact adapter, tested against an ephemeral MinIO-compatible
  local service when available.
- Vault KV-v2-compatible Secret Manager adapter, with product layers seeing only
  handles and metadata; value resolution is limited to authorized execution
  boundary.
- OTLP-compatible telemetry exporter with bounded queue, redaction and drop
  accounting.

Deployment uses a single-node Docker Compose topology with separate API,
runtime-supervisor and migration/bootstrap roles. Containers must be non-root
where practical, use read-only rootfs/tmpfs/cap-drop/no-new-privileges posture
and avoid default production credentials.

## Consequences

P5 gains a realistic single-node deployment baseline while deferring
multi-region/distributed infrastructure and additional cloud-vendor adapters.
