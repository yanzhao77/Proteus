# ADR-0067: P4 Artifact, Secret and Retention Boundary

## Status

ACCEPTED

## Phase

P4-0/P4-3

## Context

P0-P3 bind Verification and execution facts to artifact/evidence hashes, but P4
needs a product-facing artifact store, secret-handle discipline and retention
model.

## Decision

Introduce ports with local/test adapters:

- a content-addressed Artifact store that writes immutable blobs by canonical
  hash and records provenance/retention metadata;
- a Secret handle provider that returns only handles/metadata and never exposes
  secret values to Events, Outbox, API responses, logs, exports or artifacts;
- a Retention policy service that can archive/purge product-owned raw content
  only when no active authority dependency requires it, while retaining hash,
  tombstone, provenance and audit proof.

Cloud object stores and production secret managers are deferred behind these
ports.

## Consequences

P4 can productize artifact export and retention without weakening exact-hash
Verification or leaking secrets into immutable audit surfaces.
