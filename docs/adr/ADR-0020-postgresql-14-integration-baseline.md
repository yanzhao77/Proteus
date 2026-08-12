# ADR-0020: PostgreSQL 14+ Integration Test Baseline

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Conformance Test Spec §1](../specs/Hermes_Conformance_Test_Spec_V1.0.md#1-test-contract)

## Context

The slice requires real PostgreSQL tests but V1.2 does not select a precise production version. PostgreSQL 14 is a maintained baseline that supports every local transaction and locking primitive used by this slice.

## Decision

Integration tests MUST run against PostgreSQL 14 or newer. Tests receive a DSN via `HERMES_TEST_DATABASE_URL` and MUST fail closed when the integration suite is explicitly invoked without a reachable PostgreSQL database. A disposable PostgreSQL container is the documented local test method; it is not a production deployment decision.

## Alternatives Considered

SQLite/mock substitutes; rejected as transaction evidence. Pin a single exact PostgreSQL version; rejected because the slice uses no version-specific behavior requiring it.

## Consequences

CI/local environments must provision a disposable database. Production PostgreSQL version remains an open deployment decision subject to this minimum compatibility claim.

## Validation

The design minimum remains PostgreSQL 14. The test bootstrap queries `server_version_num`, requires at least 140000, applies migrations, and executes independent-connection conflict and fault-injection tests.

The first P0 Completion/Verification slice was initially exercised on PostgreSQL 16. The first and second P0 slices, including Task DAG and Work Graph concurrency tests, were subsequently exercised from clean migrations on PostgreSQL 14 on 2026-08-12. PostgreSQL 16 remains an additional validation target rather than the minimum-version definition.

## Open Questions

CI service configuration and final production PostgreSQL version remain open.
