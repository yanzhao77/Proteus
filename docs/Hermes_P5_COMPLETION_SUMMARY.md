# Hermes Runtime V1.2 P5 Deployable Product Completion Summary

Date: 2026-08-17

Status: complete. P5 implementation commits are merged into `master`
(`3e67ba0`); the external acceptance evidence described below is delivered on
branch `codex/p5-external-acceptance` and validated on 2026-08-17.

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
- The P4 `otel-compatible-local/1.0` envelope remains unchanged; P5 adds
  `to_otlp_json_envelope` + `OtlpHttpJsonExporter` emitting the OTLP/HTTP proto3
  JSON wire format (hex trace/span IDs) so a real OpenTelemetry Collector
  accepts and validates exported spans.

## Validation evidence

Validated successfully on 2026-08-14 (implementation baseline):

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

External acceptance evidence verified on 2026-08-17:

- Docker image build: `docker build --label hermes.task=p5-external-acceptance
  --tag hermes-p5-smoke:20260817 hermes-runtime` succeeded after the Docker Hub
  network recovered (python:3.11-slim pulled, all requirements installed);
  in-image smoke `python -c "import hermes_runtime.api_main"` returned
  `API-IMPORT-OK`.
- Compose fix: `docker-compose.single-node.yml` referenced a MinIO tag that does
  not exist on Docker Hub; the image is now pinned to a verified digest
  `minio/minio@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e`.
- Real MinIO integration: container `hermes-p5-minio-20260817`
  (`minio/minio@sha256:14cea...`, port 19000); `test_s3_artifact_integration.py`
  ran 4 tests PASS (content-addressed put/read, idempotent duplicate, tampered
  object hash mismatch fail-closed, tombstone preservation).
- Real Vault integration: container `hermes-p5-vault-20260817`
  (`hashicorp/vault:1.17` dev, port 18200); `test_vault_secret_integration.py`
  ran 1 test PASS (register/metadata/authorized+unauthorized resolve; canary
  secret absent from handle repr and metadata payload).
- Real OTLP Collector integration: container `hermes-p5-otel-20260817`
  (`otel/opentelemetry-collector:0.104.0`, port 14318); the new
  `OtlpHttpJsonExporter` exported a redacted span (HTTP 200, `EXPORTED`), and a
  payload with an invalid-length trace ID was rejected with HTTP 400, proving
  the backend validates real OTLP/HTTP JSON.
- Browser/Playwright UI screenshots: `capture_p5_ui_screenshots.py` used the
  locally installed Google Chrome (channel "chrome", no browser download) and
  saved `docs/evidence/p5-ui/human-gate-inbox-desktop.png` (1440x900),
  `human-gate-detail-desktop.png` (1440x900) and
  `human-gate-detail-mobile.png` (780x1688); the script asserted inbox/detail
  content and absence of `apply_resume`/`project_state`/`task_status`.
- Full regression on this branch: no-DB discovery
  `Ran 497 tests in 0.699s — OK (skipped=298)`; PostgreSQL 16 + external
  adapters full regression on dedicated container `hermes-p5-ext-pg16-20260817`
  `Ran 497 tests in 163.655s — OK (skipped=5)`; `compileall` and
  `git diff --check` pass; migrations remain `0001`-`0022` continuous with no
  new migration.
- CI: `.github/workflows/hermes-p5.yml` gains an `external-adapters` job that
  starts MinIO/Vault/OTLP Collector containers and runs the full discovery with
  `HERMES_TEST_S3_URL`, `HERMES_TEST_VAULT_URL`/`HERMES_TEST_VAULT_TOKEN` and
  `HERMES_TEST_OTLP_ENDPOINT` set.

The P5-6 local focused E2E tests cover authenticated API/Gate/UI,
Artifact/Secret/OTLP, Explain query, duplicate/stale/failure behavior and secret
canary redaction, and are now complemented by the real external-container and
browser evidence above.

Note: PostgreSQL 14 full regression passed on the prior P5 baseline
(`Ran 490 tests in 173.709s — OK`); this evidence branch adds no migration or
schema changes, only Python-level adapters/tests/CI and the Compose image pin.

## Deferred scope

- Kafka, Redis, Kubernetes, Raft and multi-region active-active.
- Cross-database distributed transactions.
- Additional cloud-specific Artifact/Secret/Telemetry vendors beyond the P5
  adapter contracts.
- New irreversible third-party business side-effect integrations.
- Multi-approver authority semantics not already specified by P3/P4.
