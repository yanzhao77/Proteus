# Hermes Runtime V1.2 P5 Deployable Product Completion Summary

Date: 2026-08-14

Status: implementation commits prepared on branch
`codex/p5-deployable-single-node`; formal P5 completion is blocked by external
smoke evidence gaps listed below.

## Implemented objective

P5 delivers a deployable single-node product baseline over the completed P0-P4
authority runtime:

- P5-0: deployable product contract, acceptance matrix and ADR-0069 through
  ADR-0072.
- P5-1: FastAPI/Pydantic production service host over the P4 ProductApiFacade.
- P5-2: supervised bounded runtime loops for relay, consumer/checkpoint,
  scheduler, Docker worker and reconcile roles.
- P5-3: PyJWT/cryptography OIDC verification and minimal Human Gate UI.
- P5-4: S3-compatible Artifact adapter, Vault KV-v2-compatible Secret adapter
  and OTLP-compatible telemetry exporter.
- P5-5: Dockerfile, single-node Compose topology, API/runtime/migration
  entrypoints, operations runbook and CI smoke workflow.
- P5-6: P5 end-to-end and fault-injection hardening.

## Authority/security decisions

- FastAPI is transport only and exposes allowlisted semantic routes.
- API/UI/health/metrics/traces do not mutate authority.
- OIDC token verification maps to scoped actor/assertion facts and does not
  apply Project resume.
- Supervisor loops schedule existing services; correctness remains in
  PostgreSQL lease/fencing/idempotency.
- S3 location and URLs are not Verification authority; content hash is.
- Vault adapter exposes handles/metadata to product layers; secret value
  resolution is execution-boundary only.
- OTLP backend failure is drop/failure accounting, not recovery or authorization.

## Validation evidence

Validated successfully on 2026-08-14:

- P5 focused no-DB/unit/E2E tests:
  `Ran 27 tests in 0.479s — OK`.
- Full no-DB discovery:
  `Ran 490 tests in 0.552s — OK (skipped=291)`.
- PostgreSQL 16 full regression with dedicated container
  `hermes-p5-pg16-20260814`:
  `Ran 490 tests in 169.015s — OK (skipped=5)`.
- PostgreSQL 14 full regression with dedicated container
  `hermes-p5-pg14-20260814`:
  `Ran 490 tests in 173.709s — OK (skipped=5)`.
- `compileall`: passed.
- `git diff --check`: passed.
- Migration continuity: `migration_count 22`, `first_last 1 22`,
  `continuous True`, `empty_migrations []`.
- Compose config smoke:
  `docker compose -f deploy/p5/docker-compose.single-node.yml config --quiet`
  passed.

Blocked / not counted as PASS:

- Docker image build: attempted twice with
  `docker build --label hermes.task=p5 --tag hermes-p5-smoke:20260814
  hermes-runtime`; both attempts failed while loading Docker Hub metadata for
  `python:3.11-slim` with `DeadlineExceeded`.
- Real MinIO integration: adapter implemented and local contract tests pass, but
  no real MinIO container PASS is claimed.
- Real Vault integration: adapter implemented and local contract tests pass, but
  no real Vault container PASS is claimed.
- Real OTLP backend integration: exporter implemented and local contract tests
  pass, but no real OTLP collector PASS is claimed.
- Browser/Playwright UI screenshots: UI routes and HTML contract tests pass, but
  no browser screenshot evidence is claimed.

The P5-6 local focused E2E tests cover authenticated API/Gate/UI,
Artifact/Secret/OTLP, Explain query, duplicate/stale/failure behavior and secret
canary redaction. They are not a substitute for the blocked external-container
and browser acceptance evidence.

## Deferred scope

- Kafka, Redis, Kubernetes, Raft and multi-region active-active.
- Cross-database distributed transactions.
- Additional cloud-specific Artifact/Secret/Telemetry vendors beyond the P5
  adapter contracts.
- New irreversible third-party business side-effect integrations.
- Multi-approver authority semantics not already specified by P3/P4.
