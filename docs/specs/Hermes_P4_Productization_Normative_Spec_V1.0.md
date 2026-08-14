# Hermes P4 Productization Normative Specification V1.0

Status: SPECIFIED
Phase: P4-0 through P4-5 Productization
Date: 2026-08-14

P4 productizes the completed P0-P3 authority runtime without creating a new
core authority path. Public API, Human Gate presentation, artifact storage,
secret handles, retention and observability are wrappers, ports and read/query
surfaces over existing semantic commands and immutable facts.

P4 MUST NOT introduce generic state mutation, generic SQL, arbitrary Event
append, direct Task PASS/FAIL, direct Project resume, Worker-issued
authorization, or observability-as-policy.

## 1. Productization scope

Implemented by P4:

- public product API boundary for semantic command wrappers and read models;
- Human Gate identity assertion and presentation boundary;
- local content-addressed Artifact store port;
- local/test Secret handle provider port;
- retention/archive/purge guard model for product-owned content;
- observability/export port with redaction and missing-link semantics;
- P4 end-to-end hardening across API, Gate, Artifact, Secret, Retention and
  Observability.

Deferred beyond P4:

- production Web UI;
- production IdP/OIDC/SAML;
- cloud object store and production secret manager;
- production OpenTelemetry backend;
- Kafka, Redis, Kubernetes, Raft or multi-region operation;
- irreversible third-party side-effect reconciliation beyond existing P3
  receipt/finding boundary.

## 2. Public API boundary

`P4-API-001`: Public API handlers MUST be semantic wrappers over existing
application services, query stores or product ports. They MUST reject generic
`PATCH`, generic status update, arbitrary SQL, arbitrary Event append and
arbitrary command payloads.

`P4-API-002`: Every authority-changing API request MUST include
`command_id`, `idempotency_key`, `expected_version`, `actor` and non-empty
`reason`. The API maps `Idempotency-Key` to the semantic command's scoped
idempotency key and MUST NOT synthesize authority facts from request booleans.

`P4-API-003`: Product API responses MAY expose current read models, explain
snapshots, Gate requests, replay/reconcile findings, Docker process
observations, side-effect receipts and Productization port records. Responses
MUST NOT expose secret values, raw chain-of-thought, unsafe payloads or mutable
authority overwrite capabilities.

P4 chooses a stdlib in-process API facade and explicit DTO validation for this
runtime slice. FastAPI and Pydantic remain deferred decisions because P4 does
not need network-facing HTTP serving to prove authority closure.

## 3. Human Gate product boundary

`P4-GATE-001`: Product Gate presentation MAY query/list/present safe Gate
payloads and submit a human decision command, but it MUST NOT apply resume or
transition Project state directly.

`P4-GATE-002`: Identity assertions are product boundary facts. The local/test
adapter may issue deterministic assertions, but production IdP verification is
deferred. Assertions MUST be bound to issuer, subject, project, optional task,
Gate request, action scope, validity interval and assertion hash.

`P4-GATE-003`: Self approval, unauthorized approver, expired assertion, stale
Gate version and invalidated Evidence MUST fail closed.

## 4. Artifact, Secret and Retention boundary

`P4-ART-001`: Product artifacts are content-addressed immutable blobs with hash,
media type, provenance and retention metadata. Mutable file paths MUST NOT be
the primary authority.

`P4-SEC-001`: Secret providers return handles and metadata only. Secret values
MUST NOT appear in Events, Outbox, API responses, logs, observability exports or
artifact content.

`P4-RET-001`: Retention/archive/purge may remove product-owned raw content only
when policy allows it and no active authority dependency requires the content.
Hash, tombstone, provenance and audit proof MUST remain.

## 5. Observability and export boundary

`P4-OBS-001`: Observability records and exports are diagnostic/audit facts, not
Policy, Risk, Budget, Gate or Task state facts.

`P4-OBS-002`: Missing trace/ref links MUST be represented as `MISSING` rather
than fabricated. Unsafe export fields MUST be redacted or rejected.

P4 uses an OpenTelemetry-compatible local export envelope without requiring an
OpenTelemetry SDK or backend.

## 6. Acceptance rows

P4 acceptance is tracked in
[`../P4_PRODUCTIZATION_ACCEPTANCE_MATRIX.md`](../P4_PRODUCTIZATION_ACCEPTANCE_MATRIX.md).
Rows may be marked `PASS` only when implementation and tests exist. Skipped
PostgreSQL, Docker or external-backend checks MUST NOT be counted as PASS.
