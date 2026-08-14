# Hermes P5 Deployable Product Normative Specification V1.0

Status: SPECIFIED
Phase: P5-0 through P5-6 Deployable Single-Node Product
Date: 2026-08-14

P5 turns the completed P0-P4 Hermes runtime into a deployable single-node
product baseline. P5 adds network transport, service supervision, production
identity, Human Gate UI, production-compatible Artifact/Secret/Telemetry
adapters, deployment automation and end-to-end hardening. It does not create a
second state authority.

Normative priority remains:

```text
Core Runtime Design V1.2 invariants
-> Runtime / Command / Lease / P2 / P3 / P4 normative specs
-> this P5 specification
-> ACCEPTED ADR
-> acceptance matrices
-> completion summaries
```

## 1. Scope

P5 MUST prove this single-node minimum product loop:

```text
authenticated API request
-> semantic command wrapper
-> PostgreSQL authority
-> queue / lease / Docker execution
-> Artifact / Evidence
-> Verification
-> Human Gate decision when required
-> guarded resume
-> Explain / Audit query
-> observability export
```

P5 remains single-node. Kafka, Redis, Kubernetes, Raft, multi-region
active-active and cross-database distributed transactions are non-goals.

## 2. Topology and trust boundaries

The deployable topology contains these roles:

- `api`: FastAPI network transport and Human Gate UI presenter.
- `runtime-supervisor`: bounded service loops for relay, consumer/checkpoint,
  scheduler, Docker worker execution and reconcile polling.
- `migration-bootstrap`: one-shot migration and role/bootstrap job.
- `postgres`: sole authority state and concurrency coordinator.
- `docker-daemon`: single-node execution target controlled only by the
  authorized worker/process-manager boundary.
- `artifact-store`: S3-compatible content-addressed blob location.
- `secret-manager`: production secret-handle backend.
- `telemetry`: OTLP-compatible export target.

API, UI, IdP, logs, metrics, traces, artifact URLs and secret handles are not
authority. PostgreSQL remains the only authority state and lease/fencing point.

## 3. P5 acceptance IDs

Rows are tracked in
[`../P5_DEPLOYABLE_PRODUCT_ACCEPTANCE_MATRIX.md`](../P5_DEPLOYABLE_PRODUCT_ACCEPTANCE_MATRIX.md).
Rows MAY be marked `PASS` only after implementation and tests exist.

### P5-CONTRACT

- `P5-CONTRACT-001`: P5 deployment/product boundary is specified before code.
- `P5-CONTRACT-002`: P4 completion summary reflects merged baseline, not only a
  stale feature branch.

### P5-API

- `P5-API-001`: FastAPI service host exposes only allowlisted semantic routes.
- `P5-API-002`: Authority-changing endpoints require content type,
  `Idempotency-Key`, `command_id`, `expected_version`, actor and reason.
- `P5-API-003`: Error envelope, request/correlation IDs and redaction prevent
  internal stack, database DSN and secret leakage.
- `P5-API-004`: `/livez` and `/readyz` are health/readiness only and cannot
  mutate authority.

### P5-SERVICE

- `P5-SERVICE-001`: Supervised runtime loops are bounded, cancellable,
  backoff-aware and expose readiness degradation on critical failure.
- `P5-SERVICE-002`: Multi-instance correctness relies on PostgreSQL
  lease/fencing/idempotency, not process-local locks.

### P5-IDP

- `P5-IDP-001`: OIDC/JWT verification validates signature, issuer, audience,
  subject, exp/nbf, algorithm and JWKS key id with bounded cache.
- `P5-IDP-002`: Local/test identity issuer is disabled in production profile.

### P5-UI

- `P5-UI-001`: Human Gate UI provides inbox, detail, Evidence refs, risk/reason,
  Approve/Reject, status and Explain/Audit links.
- `P5-UI-002`: UI has no generic entity editor and cannot apply Project resume.

### P5-ART

- `P5-ART-001`: S3-compatible adapter stores immutable content-addressed
  artifacts and never treats bucket/key/URL as Verification authority.

### P5-SECRET

- `P5-SECRET-001`: Production secret adapter exposes handles/metadata to product
  layers and resolves values only at authorized execution boundary.

### P5-OBS

- `P5-OBS-001`: OTLP-compatible exporter redacts unsafe attributes, bounds
  queues, preserves `MISSING` links and never changes authority on backend
  failure.

### P5-DEPLOY

- `P5-DEPLOY-001`: Single-node deployment baseline defines entrypoints,
  non-root/read-only/cap-drop container posture, Compose topology and
  migration/bootstrap flow.
- `P5-DEPLOY-002`: Operations runbook covers readiness, backup/restore,
  migration forward validation, secret rotation and rollback boundaries.

### P5-E2E

- `P5-E2E-001`: Full happy-path and fault-injection tests prove P5 preserves
  P0-P4 authority invariants under API, OIDC, UI, supervisor, Docker, S3,
  Secret Manager and OTLP interactions.

## 4. SLO and health semantics

`/livez` reports process liveness only. `/readyz` reports dependency readiness:
database connectivity, migration compatibility, supervisor critical-loop state
and configured adapter readiness. Neither endpoint may emit commands, events or
repair actions.

Single-node baseline target SLOs are:

- API returns stable validation/error envelopes for malformed client requests.
- Supervisor critical-loop failure degrades readiness within one polling window.
- Background loops use bounded batches and bounded backoff to avoid silent spin.
- Adapter backend outage is visible in readiness/observability and never mutates
  authority state by itself.

## 5. Supported versions

P5 supports Python 3.9+, PostgreSQL 14 and 16, Docker target 1.0 and a
single-node Linux container deployment posture. macOS Docker Desktop remains
valid for local integration testing, not a multi-tenant production sandbox
claim.

## 6. Forbidden implementations

- generic `PATCH`, status mutation, arbitrary SQL, arbitrary Event append or
  arbitrary command passthrough;
- API/UI/metrics/traces/logs becoming authority facts;
- secret value exposure in API, UI, logs, events, outbox, artifacts, traces,
  exceptions or test snapshots;
- relying on mocks/skips as production PostgreSQL, Docker, OIDC, S3/Vault, OTLP
  or browser PASS evidence;
- empty migration or empty test files as acceptance evidence.
