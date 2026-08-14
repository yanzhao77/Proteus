# ADR-0062: P3-3 PostgreSQL Quarantine and Evidence Invalidation Runtime Authority

## Status

ACCEPTED

## Phase

P3-3

## Context

ADR-0056 and ADR-0057 specified the P3 quarantine review/adoption/redrive and
Evidence invalidation boundaries. P2-4 already preserves stale Worker payloads
inside immutable `execution_quarantine_records`, and P0/P1/P3-1 already keep
Evidence, VerificationResult and Human Gate facts immutable enough to audit. P3-3
needed the runtime authority layer that lets operators review quarantined
payloads and invalidate Evidence without creating a shortcut around Worker
fencing, Verification or Control Plane guarded state transitions.

## Decision

P3-3 is implemented as a PostgreSQL authority overlay in
`0020_quarantine_evidence_invalidation.sql`.

Quarantine operations use:

- immutable original P2 quarantine envelopes in `execution_quarantine_records`;
- `quarantine_current_states` as the expected-version lifecycle pointer;
- append-only `quarantine_operations`;
- append-only adoption and redrive request ledgers.

Adoption creates only a guarded semantic command shell and records guard refs; it
does not update Task state, Verification state, Worker state or normal execution
authority. Redrive requires a new command/idempotency identity and preserves
original causation.

Evidence invalidation uses:

- immutable original `evidence` and `verification_results` rows;
- `evidence_current_states` as the expected-version validity pointer;
- append-only `evidence_invalidation_records`;
- append-only stale dependency and re-verification requirement ledgers.

Invalidation does not delete Evidence, does not rewrite VerificationResult and
does not directly flip a passed Task to failed. Human Gate Decision insertion and
Decision Application receive fail-closed invalid-Evidence triggers, so stale Gate
facts cannot authorize resume. Unknown impact creates `REVERIFICATION_REQUIRED`.

All P3-3 authority functions are `SECURITY DEFINER SET search_path =
pg_catalog`, owned by a NOLOGIN owner role, revoke `PUBLIC` execute, use scoped
idempotency and payload hashes through `command_receipts`, and commit authority
state, Event Log, Outbox and Receipt changes in one local PostgreSQL
transaction.

## Consequences

P3-3 closes the operational review and Evidence invalidation runtime slice while
preserving the P0-P2 authority chain. Reviewers can inspect, discard, request
guarded adoption or request redrive, but cannot directly pass a Task or replay
stale Worker output into current authority. Evidence producers/operators can
invalidate current Evidence and force downstream decisions to fail closed, but
Control Plane must still choose waiting, recovery or re-verification through
later guarded Commands.

P3-4 Decision Explain/Audit query runtime and P3-5 production sandbox/external
side-effect reconciliation remain separate future slices.

## Evidence

- `hermes-runtime/migrations/0020_quarantine_evidence_invalidation.sql`
- `hermes-runtime/tests/test_quarantine_domain.py`
- `hermes-runtime/tests/test_quarantine_postgres.py`
- `hermes-runtime/tests/test_quarantine_permissions.py`
- `hermes-runtime/tests/test_evidence_invalidation_domain.py`
- `hermes-runtime/tests/test_evidence_invalidation_postgres.py`
- `hermes-runtime/tests/test_evidence_invalidation_permissions.py`
- PostgreSQL 16 full regression on 2026-08-14: 413 tests, PASS.
- PostgreSQL 14 full regression on 2026-08-14: 413 tests, PASS.
- No-DB discovery on 2026-08-14: 413 discovered, 272 DB tests skipped, PASS.
