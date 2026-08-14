# Hermes P5 Single-Node Operations Runbook

## Scope

This runbook covers the P5 deployable single-node baseline. It does not claim
multi-region, Kubernetes, Kafka/Redis, Raft or cross-database transaction
support.

## Configuration

Production configuration must come from environment variables, secret files or
secret handles. Do not commit real credentials or `.env` files. The Compose file
references secret file paths that operators must create outside Git.

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
