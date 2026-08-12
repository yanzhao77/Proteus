# ADR-0019: Psycopg 3 and Versioned Native SQL Migrations

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Command/Event Protocol §6](../specs/Hermes_Command_Event_Protocol_V1.0.md#6-authoritative-transaction)

## Context

The slice must prove PostgreSQL transaction semantics. It needs one small schema and explicit transaction control; the repository has no ORM or migration framework to reuse.

## Decision

Use Psycopg 3 as the PostgreSQL driver and versioned native SQL files as migrations. The first slice pins the verified driver package to Psycopg 3.2.13. Infrastructure code uses parameterized SQL and explicit transactions. Do not introduce SQLAlchemy or a migration framework for this slice.

## Alternatives Considered

SQLAlchemy/Alembic; viable later but unjustified for the small slice. Psycopg 2; mature but Psycopg 3 provides the current driver API. Hand-built wire protocol or CLI subprocesses; rejected.

## Consequences

The schema and constraints remain directly reviewable. A future ORM decision must preserve transaction and authority semantics.

## Validation

Apply migrations to a clean PostgreSQL database and run rollback, idempotency and version-conflict integration tests through Psycopg 3.2.13 connections.

## Open Questions

Long-term ORM and migration tooling remain open.
