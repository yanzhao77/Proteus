# ADR-0069: P5 FastAPI Service Host Boundary

## Status

ACCEPTED

## Phase

P5-0/P5-1

## Context

P4 deliberately used an in-process API facade to prove product API authority
closure without network dependencies. P5 needs a real production transport while
preserving the P4 facade and P0-P3 authority model.

## Decision

Use FastAPI, Pydantic and Uvicorn-compatible ASGI hosting for the P5 service
host. The FastAPI layer is transport only: application factory construction must
not connect to PostgreSQL, run migrations or start background loops at import
time. Routes are allowlisted semantic wrappers over the P4 facade and read
models.

Authority-changing HTTP requests must provide content type, `Idempotency-Key`,
`command_id`, `expected_version`, actor and non-empty reason. Error responses use
a stable redacted envelope with request/correlation IDs. `/livez` and `/readyz`
are health/readiness probes only and never mutate authority.

## Consequences

P5 gains a deployable network API without a second write authority. Future
public API expansion must add semantic routes, not generic mutation or arbitrary
command pass-through.
