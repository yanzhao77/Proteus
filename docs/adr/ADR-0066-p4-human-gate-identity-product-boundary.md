# ADR-0066: P4 Human Gate Identity Product Boundary

## Status

ACCEPTED

## Phase

P4-0/P4-2

## Context

P3 implemented Gate Request, Gate Decision and Project waiting/resume authority.
P4 must make Gate usable from product surfaces without introducing production
IdP scope or allowing Main Hermes/API to approve on behalf of a user.

## Decision

Introduce an identity assertion port and local/test assertion adapter. Assertion
facts are bound to issuer, subject, project, optional task, Gate request, action
scope, validity interval and assertion hash. The Gate product facade may list
and present safe Gate payloads and submit `SubmitHumanGateDecision` through the
existing authority, but it never applies Project resume directly.

Production IdP/OIDC/SAML, multi-party directory policy and UI-specific session
management are deferred.

## Consequences

P4 can prove self-approval, unauthorized approval, stale version, expired
assertion and invalidated Evidence fail closed while leaving production identity
integration outside the runtime core.
