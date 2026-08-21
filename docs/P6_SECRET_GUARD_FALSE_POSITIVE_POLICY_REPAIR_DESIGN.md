# P6 Secret Guard False-Positive Policy Repair — Design

## Purpose

This Stage A repair replaces the P6 execution admission secret guard's unscoped `payload::text` scan with a structured JSONB traversal. The change resolves the deterministic false positive in which E4's `task-<uuid5hex>` identity contains the substring `sk-` across the fixed `task-` prefix boundary.

> This document describes a P6 security-policy repair only. It does not change E4 durable identity, E1–E7 authority semantics, the P6 state machine, or the E8 production-entry trial.

## Forward Migration Contract

Migration `0031_p6_secret_guard_structured_jsonb.sql` is the sole schema artifact. It creates schema-private helper functions, replaces `public.hermes_execution_has_secret_value(JSONB)` without changing its signature, and preserves `hermes_execution_owner`, `SECURITY INVOKER`, hardened `search_path = pg_catalog`, and public execute revocation. It creates no business table, column, role, grant, or authority-state transition.

| Policy area | Stage A rule |
| --- | --- |
| JSON traversal | Recursively visits objects, arrays, and scalar values. |
| Sensitive material keys | Uses exact normalized key equality for `api_key`, `api_token`, `password`, `access_token`, `authorization`, `client_secret`, `private_key`, `secret_value`, `credential`, and `secret`. |
| `sk-*` detection | Runs against every string scalar with a left/right token boundary; embedded text after header, equals, colon, whitespace, or slash remains detectable. |
| Identity handling | No identity-path allowlist exists. `task-<uuid5hex>` passes naturally because the `s` in its internal `sk-` is preceded by alphanumeric `a`, not a token boundary. |
| Secret references | `secret_ref`, `credential_ref`, and `handle` must be strings matching the strict opaque grammar `^(secret|credential|handle)-(ref|opaque|vault)-[a-z0-9][a-z0-9._:-]{5,120}$`. Their values still undergo scalar secret-token detection. |
| PEM / assignment forms | Every string scalar is checked for `password=`, private-key markers, and private-key text. |

The stable external rejection remains `SECRET_VALUE_FORBIDDEN`. Rejection behavior must not persist or disclose raw secret material in receipts, events, outbox, audit records, logs, or API responses.

## Compatibility Decision

E4 `stable_id()` remains unchanged. Its derived IDs participate in durable replay, child command identity, E4 reconciliation, E5 ownership mapping, and E7 projections. Changing that format would be an identity compatibility migration, not a secret-detection repair. Manifest resealing records changed source files only; it does not substitute for durable identity compatibility.

## Stage Boundary

Stage A ends after the P6 repair PR is merged and remote master is verified. The minimum E4-derived regression tests a snapshot containing real `stable_id("task", ...)` output and a risk reference through the real P6 guard plus real execution admission continuation. It does not restore, commit, or depend on the stopped E8 forensic adapter, E4 preview DTO, GraphPatch alignment, observer, or full E8 trial.
