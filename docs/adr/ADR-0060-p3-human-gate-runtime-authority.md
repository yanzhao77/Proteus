# ADR-0060: P3-1 PostgreSQL Human Gate Runtime Authority

## Status

ACCEPTED

## Phase

P3-1

## Context

ADR-0053 and ADR-0054 defined the Human Gate and Project waiting/resume
contracts. P3-1 needed a runtime implementation that closes CT-009 and CT-010
without allowing Main Hermes, Policy, Worker, Scheduler, Planner or Verifier
authority to approve or apply human decisions.

## Decision

Implement Human Gate in PostgreSQL migration
`0018_human_gate_waiting_resume.sql` with three narrow authority surfaces:

- `hermes_gate_request_runtime` can create Gate Requests with immutable
  ResumeContext bindings only.
- `hermes_gate_decision_runtime` can submit authorized human/operator Decisions
  only.
- `hermes_control_plane_runtime` can enter Project waiting, apply approved
  Decisions, expire, cancel or supersede Requests.

Gate Request, Gate Decision and Decision Application are separate records.
`APPROVED` is not equivalent to `APPLIED`, and neither is equivalent to Project
resume. `human_gate.apply_decision` locks and revalidates current Project,
Waiting, Gate, Decision, ResumeContext hash, approver authorization, Evidence,
Policy and Budget facts before resolving the waiting record and writing
`human_gate.decision_applied` plus `project.resumed` Events/Outbox rows.

The implementation keeps P3-2 replay/reconcile and P3-3 quarantine/Evidence
operations out of scope. P3-1 relies on PostgreSQL local transactions and
pre-commit fault rollback; replay repair semantics remain a later authority.

## Consequences

Human Gate now has a tested runtime authority boundary, but production IdP,
notification, UI, multi-person approval policy and retention remain open
decisions. Test-only authorization assertions are explicit fixtures and are not
claimed as enterprise IdP integration.

## Evidence

- [`0018_human_gate_waiting_resume.sql`](../../hermes-runtime/migrations/0018_human_gate_waiting_resume.sql)
- [`test_human_gate_domain.py`](../../hermes-runtime/tests/test_human_gate_domain.py)
- [`test_human_gate_postgres.py`](../../hermes-runtime/tests/test_human_gate_postgres.py)
- [`test_human_gate_permissions.py`](../../hermes-runtime/tests/test_human_gate_permissions.py)
- PostgreSQL 14 full regression on 2026-08-14: 369 tests, PASS.
- PostgreSQL 16 full regression on 2026-08-14: 369 tests, PASS.
