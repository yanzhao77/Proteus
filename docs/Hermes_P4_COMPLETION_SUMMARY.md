# Hermes Runtime V1.2 P4 Productization Completion Summary

Date: 2026-08-14

Status: P4-0 through P4-5 complete and merged to `master` as baseline for P5.

## Completed objective

P4 productizes the completed P0-P3 authority runtime without adding a second
state authority. The completed scope covers:

- P4-0 productization contract closure and ADR-0065 through ADR-0068.
- P4-1 public API facade for semantic read/query and command wrapper routes.
- P4-2 Human Gate product identity assertion and presentation boundary.
- P4-3 content-addressed Artifact store, Secret handle provider and Retention
  tombstone/guard model.
- P4-4 Observability/export port with redaction and explicit `MISSING` links.
- P4-5 end-to-end productization hardening tests.

## Authority boundaries preserved

- Public API cannot perform generic PATCH, status mutation, arbitrary SQL,
  arbitrary Event append or arbitrary command passthrough.
- Authority-changing product requests preserve command metadata:
  `command_id`, `idempotency_key`, `expected_version`, `actor` and `reason`.
- Human Gate product facade can submit a Decision but cannot apply Project
  resume; resume remains a guarded Control Plane command.
- Artifact store uses immutable content hashes; Verification binds the exact
  hash rather than a mutable path.
- Secret provider exposes handles and metadata only; plain secret values are
  rejected from product payloads.
- Retention can archive/purge raw content only while preserving hash,
  provenance and tombstone proof; active authority dependencies block purge.
- Observability and metrics are diagnostic facts only; missing links remain
  explicit `MISSING` records and are not fabricated.

## Implementation files

- `hermes_runtime.domain.product_api`
- `hermes_runtime.application.product_api`
- `hermes_runtime.infrastructure.http_api`
- `hermes_runtime.domain.identity`
- `hermes_runtime.application.human_gate_product`
- `hermes_runtime.infrastructure.local_identity`
- `hermes_runtime.domain.product_artifacts`
- `hermes_runtime.domain.secret_handles`
- `hermes_runtime.infrastructure.local_artifact_store`
- `hermes_runtime.infrastructure.local_secrets`
- `hermes_runtime.domain.observability`
- `hermes_runtime.application.observability`
- `hermes_runtime.infrastructure.local_observability`

## Validation evidence

Final validation on 2026-08-14:

- P4 focused no-DB tests:
  `Ran 25 tests in 0.004s — OK`.
- Full no-DB discovery with `.venv`:
  `Ran 463 tests in 0.156s — OK (skipped=291)`.
- PostgreSQL 16 full regression with dedicated container
  `hermes-p4-pg16-20260814`:
  `Ran 463 tests in 193.504s — OK (skipped=5)`.
- PostgreSQL 14 full regression with dedicated container
  `hermes-p4-pg14-20260814`:
  `Ran 463 tests in 172.880s — OK (skipped=5)`.
- `compileall`:
  `PYTHONPYCACHEPREFIX=/private/tmp/hermes-p4-pycache ... compileall -q
  hermes-runtime/src hermes-runtime/tests` completed successfully.
- `git diff --check`: completed successfully.
- Migration continuity scan: `migration_count 22`, `first_last 1 22`,
  `continuous True`.

P4 no-DB focused files:

- `test_public_api_domain.py`
- `test_public_api_boundary.py`
- `test_human_gate_product_boundary.py`
- `test_artifact_secret_retention_boundary.py`
- `test_observability_export_boundary.py`
- `test_p4_end_to_end_productization.py`

PostgreSQL authority regressions remain P0-P3 responsibility; P4 does not add a
durable authority migration.

## Deferred scope

- Production FastAPI/Web UI.
- Production IdP/OIDC/SAML.
- Cloud object store.
- Production secret manager.
- Production OpenTelemetry backend/alerting.
- Kafka, Redis, Kubernetes, Raft or multi-region deployment.
- New irreversible third-party side-effect integrations.
