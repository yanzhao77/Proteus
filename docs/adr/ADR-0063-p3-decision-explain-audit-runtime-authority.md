# ADR-0063: P3-4 PostgreSQL Decision Explain, Audit and Trace Runtime Authority

## Status

ACCEPTED

## Phase

P3-4

## Context

ADR-0058 specified immutable Decision Explain, audit and trace requirements for
P3. P3-4 needs a runtime implementation that can answer why a decision happened
from facts captured at the time, without query-time recomputation under newer
Policy, Risk, model, compiler or code versions.

## Decision

Implement P3-4 in PostgreSQL migration
`0021_decision_explain_audit_trace.sql` with three append-only surfaces:

- immutable `decision_explain_snapshots`;
- immutable `decision_explain_nodes` / `decision_explain_edges` reference graph;
- immutable `audit_trace_records`.

`DecisionExplainAuthority` captures a deterministic snapshot hash from
source aggregate refs, schema/producer versions, safe summaries, node/edge refs,
redaction class, retention policy and authorization scope. Missing links are
first-class `MISSING` nodes with stable reasons; the runtime does not fabricate
or infer absent facts. Existing snapshots are not enriched in place when late
facts arrive; a later capture creates a new snapshot version.

The PostgreSQL authority uses `hermes_explain_capture_runtime` for writes and
`hermes_explain_query_runtime` for scoped reads. All mutating writes commit the
snapshot/reference graph, audit record, Event Log, Outbox and CommandReceipt in
one local transaction. All P3-4 authority functions are
`SECURITY DEFINER SET search_path = pg_catalog`, owned by the NOLOGIN
`hermes_p3_explain_owner`, revoke `PUBLIC` execute and deny direct runtime
INSERT/UPDATE/DELETE on explain/audit tables.

Explain and audit records store safe summaries, hashes, references and
redaction metadata only. Raw prompt, chain-of-thought, secret values and
unbounded stdout/stderr are rejected before capture.

## Consequences

P3-4 closes the Decision Explain/Audit/Trace runtime slice while preserving
existing P0-P3 authority boundaries. Explain can be queried by authorized scope
and trace/correlation refs, but it remains observability/audit evidence rather
than a new state or authorization authority.

Production Docker execution, side-effect receipts and P3 end-to-end completion
remain separate P3-5/P3-6 slices.

## Evidence

- [`0021_decision_explain_audit_trace.sql`](../../hermes-runtime/migrations/0021_decision_explain_audit_trace.sql)
- [`explain.py`](../../hermes-runtime/src/hermes_runtime/domain/explain.py)
- [`application/explain.py`](../../hermes-runtime/src/hermes_runtime/application/explain.py)
- [`postgres_explain.py`](../../hermes-runtime/src/hermes_runtime/infrastructure/postgres_explain.py)
- [`test_explain_domain.py`](../../hermes-runtime/tests/test_explain_domain.py)
- [`test_explain_postgres.py`](../../hermes-runtime/tests/test_explain_postgres.py)
- [`test_explain_permissions.py`](../../hermes-runtime/tests/test_explain_permissions.py)
