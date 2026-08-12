# ADR-0025: SECURITY DEFINER Search Path and Owner Hardening

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Runtime Invariants](../Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.2.md#26-runtime-invariants), [ADR-0023](ADR-0023-postgresql-project-runtime-roles.md)

## Context

Project authority uses PostgreSQL `SECURITY DEFINER` functions so runtime roles can invoke guarded state changes without direct `projects` write grants. A definer function is only safe if object resolution, ownership and grants are also constrained; otherwise caller-controlled `search_path`, schema `CREATE`, function owner leakage or object shadowing can become an authority bypass.

## Decision

Project authority functions are owned by `hermes_authority_owner`, a `NOLOGIN` role distinct from Worker, read-only and Control Plane runtime roles. Runtime roles receive only the required `EXECUTE` and table `SELECT` grants. `PUBLIC` execute is revoked.

Definer functions set `search_path = pg_catalog` and schema-qualify authority tables, helper functions and generated UUID calls. Runtime roles and `PUBLIC` cannot create objects in `public`. Tests still use temporary schemas to attempt object shadowing because temp objects remain caller-controlled.

The deferred Project/Event/Outbox invariant trigger and immutable trigger helper are recreated with explicit `public.` references and a fixed safe `search_path`.

## Consequences

The current MVP keeps authority objects in `public` for migration simplicity, but treats `public` as a trusted schema by revoking untrusted `CREATE`. A future dedicated schema may reduce this concern further, but is not required for P0 conformance.

## Validation

PostgreSQL role tests verify runtime roles cannot directly update Project state, write Guard facts, alter functions, disable triggers or create trusted schema objects. Object shadowing tests create same-name temp objects and change session `search_path`; guarded functions still operate on authoritative objects.

## Open Questions

Production role bootstrap, cloud IAM, credential rotation, dedicated schema migration and administrator alerting for deliberately disabled triggers remain deployment decisions.
