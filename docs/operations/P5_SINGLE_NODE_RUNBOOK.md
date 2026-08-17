# Hermes P5 Single-Node Operations Runbook

## Scope

This runbook covers the P5 deployable single-node baseline. It does not claim
multi-region, Kubernetes, Kafka/Redis, Raft or cross-database transaction
support.

## Configuration

Production configuration must come from environment variables, secret files or
secret handles. Do not commit real credentials or `.env` files. The Compose file
references secret file paths that operators must create outside Git.

### Configuration reference

Ports (single-node Compose topology, `deploy/p5/docker-compose.single-node.yml`):

| Service | Container port | Host port | Purpose |
| --- | --- | --- | --- |
| postgres | 5432 | 5432 (default) | sole authority state and concurrency coordinator |
| api | 8080 | 8080 | FastAPI transport and Human Gate UI |
| runtime-supervisor | n/a | n/a | bounded runtime loops (no inbound port) |
| minio | 9000 | 9000 | S3-compatible artifact store |
| vault | 8200 | 8200 | secret-handle backend |
| otel-collector | 4318 | 4318 | OTLP/HTTP telemetry export target |

Environment variables (runtime entrypoints):

| Variable | Services | Purpose |
| --- | --- | --- |
| `HERMES_DATABASE_URL` | api, runtime-supervisor, migration-bootstrap, relay | PostgreSQL DSN |
| `HERMES_DATABASE_URL_FILE` | api, runtime-supervisor, migration-bootstrap | path to a secret file containing the DSN (Compose default) |
| `HERMES_CORS_ORIGINS` | api | comma-separated allowed CORS origins (empty = none) |
| `HERMES_SERVICE_BATCH_SIZE` | runtime-supervisor | per-loop batch size (default 100) |
| `HERMES_SERVICE_POLL_SECONDS` | runtime-supervisor | per-loop poll interval (default 1.0) |

Secret files referenced by Compose (operators must create them outside Git,
see `deploy/p5/secrets/`):

| File | Consumed by |
| --- | --- |
| `postgres_bootstrap_password.txt` | postgres (`POSTGRES_PASSWORD_FILE`) |
| `hermes_database_url.txt` | migration-bootstrap, api, runtime-supervisor |
| `minio_root_user.txt` / `minio_root_password.txt` | minio |
| `vault_dev_token.txt` | vault (`VAULT_DEV_ROOT_TOKEN_ID_FILE`) |

Test-only environment variables (`hermes-runtime/tests` and the CI
`external-adapters` job): `HERMES_TEST_DATABASE_URL`, `HERMES_TEST_S3_URL`,
`HERMES_TEST_S3_ACCESS_KEY`, `HERMES_TEST_S3_SECRET_KEY`,
`HERMES_TEST_VAULT_URL`, `HERMES_TEST_VAULT_TOKEN`, `HERMES_TEST_OTLP_ENDPOINT`.

## Startup

1. Start PostgreSQL.
2. Run the `migration-bootstrap` job with owner/bootstrap credentials.
3. Start `api`.
4. Start `runtime-supervisor`.
5. Confirm `/livez` is `LIVE` and `/readyz` is ready.

`depends_on` is used for ordering only; service readiness is determined by
health/readiness probes.

## Backup and restore

- Use PostgreSQL native logical backup for authority tables.
- Store object artifacts by content hash and retain tombstone metadata.
- Restore database first, then artifact content, then verify hashes against
  authority refs.
- Replay/reconcile findings must be used for uncertainty; do not patch authority
  tables manually.

## Migration and rollback

Hermes does not promise automatic down migrations for authority schema.
Rollback separates application rollback from schema compatibility:

- forward migrations must be validated on PostgreSQL 14 and 16;
- application rollback may run against a compatible already-migrated schema;
- incompatible schema rollback requires a documented restore point.

## Secret rotation

Rotate secret backend values by creating a new handle/version and updating
authorized execution configuration. Product/API/UI layers must continue to
display handles and metadata only.

## Readiness and incident response

- API `/livez`: process alive.
- API `/readyz`: database/migration/dependency/supervisor readiness.
- Critical supervisor loop failure makes readiness fail.
- Telemetry backend failure is exported/drop-counted and must not mutate
  authority.

## Forbidden operations

- generic SQL patching of authority tables;
- direct Project/Task status edits;
- treating metrics/logs/traces as authorization;
- resolving secret values outside authorized execution boundary.
