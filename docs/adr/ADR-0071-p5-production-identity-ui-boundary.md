# ADR-0071: P5 Production OIDC and Human Gate UI Boundary

## Status

ACCEPTED

## Phase

P5-0/P5-3

## Context

P4 introduced local/test identity assertions and a Human Gate product facade.
P5 needs standards-based production identity and a usable Gate UI.

## Decision

Use a mature JWT/JWKS-capable library for OIDC token validation. The verifier
must check signature, issuer, audience, subject, `exp`, `nbf`, algorithm and key
ID, with bounded JWKS cache. `alg=none`, unknown key, wrong algorithm, expired
or future token, issuer mismatch and audience mismatch fail closed.

Verified claims map into P4 identity assertion and actor scope. Tokens and UI
sessions do not become Project resume authority. Production profile disables
local/test identity issuer.

The Human Gate UI is minimal: inbox, detail, Evidence refs, risk/reason,
Approve/Reject, result status and Explain/Audit links. It has no generic entity
editor and no direct Project/Task status controls.

## Consequences

P5 can authenticate operators and submit scoped Gate Decisions without merging
Identity, UI and Control Plane authority.
