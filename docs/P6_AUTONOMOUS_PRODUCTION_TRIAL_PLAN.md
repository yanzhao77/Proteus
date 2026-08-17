# Proteus P6 Autonomous Production Trial — Execution Plan

Status: **COMPLETE** — Overall verdict PASS (all acceptance rows PASS, evidence in docs/evidence/p6, report in docs/P6_REPORT.md)
Branch: `codex/p6-autonomous-production-trial`
Baseline: `master` @ `24f7f75` (P5 complete, 497 tests, PostgreSQL 16 regression green)

> This file is the living execution plan for P6. It records repository
> reconnaissance results, the P6 capability gap, the architecture plan,
> implementation slices and the acceptance strategy. Update it as P6
> proceeds; do not start large modifications before the plan below is
> anchored.

---

## 1. Method (P6-0 Reconnaissance)

First principle: never assume documentation matches code. The following
conclusions were derived by reading actual code, tests, migrations, ADRs,
CI workflows and the P0-P5 acceptance matrices, and by running the real test
suites:

- No-DB discovery: `Ran 497 tests ... OK (skipped=298)` (2026-08-18 baseline).
- PostgreSQL 16 full regression (dedicated container `hermes-check-pg16`,
  port 55432): `Ran 497 tests ... OK (skipped=12)` (2026-08-18 baseline).
- There is no `AGENTS.md` / `AGENTS.override.md` in this repository.

## 2. Repository tree (P6-relevant)

```text
hermes-runtime/
  migrations/0001..0022                   22 versioned SQL authority migrations
  src/hermes_runtime/
    api_main.py / supervisor_main.py / migration_bootstrap.py / relay_once.py
    config.py
    application/   ControlPlane + per-authority application services
    domain/        pure authority models, state machines, decision engines
    infrastructure/ PostgreSQL stores + adapters (Docker, S3, Vault, OTLP, OIDC)
  tests/           unittest suites (no-DB, domain, PostgreSQL, permissions,
                   Docker, external adapters, E2E)
  scripts/capture_p5_ui_screenshots.py
  Dockerfile / requirements.txt / README.md
deploy/p5/docker-compose.single-node.yml
docs/              specs, ADRs (0001..0072), acceptance matrices, evidence
.github/workflows/hermes-p5.yml
```

## 3. Answers to the P6 reconnaissance questions (code-verified)

### A. Is there an entry from Request → Situation?

**PARTIAL.** The authority chain exists: `project.create` (ControlPlane) →
Event Log → `SituationAnalyzer.analyze_logged_event` produces Situations
(`work_available`, `verification_failed`, ...). Trigger catalog is
`TRIGGER_EVENT_CATALOG` in `domain/situation.py`; classification is
deterministic and fingerprint-bound (ADR-0033/0034). However there is **no
Software Request submission surface**: the FastAPI/ProductApiFacade layer only
exposes read routes and one authority-changing route (`human-gates/*/decisions`).
No API route submits a software request; no run/session aggregate exists.

### B. Is there a complete autonomous orchestration loop?

**NO.** The *authority pieces* of the loop are implemented and independently
tested against PostgreSQL: Situation → Diagnosis → Planning → Policy → Risk →
Selection → Capability/Context/Sandbox freeze → ExecutionRequest prep → Queue →
Scheduler Lease → Worker lifecycle → Result → Verification → Feedback →
Recovery cycle (P2-5, ADR-0052) → Human Gate (P3-1). But nothing wires them
into one autonomous driver. The P5 supervisor roles (`relay`,
`consumer-checkpoint`, `scheduler-lease`, `docker-worker`, `reconcile`) are
one-shot no-op placeholders in `supervisor_main.py`; tests drive each stage
manually. A real worker that *executes* a leased ExecutionRequest to produce a
software artifact does not exist yet (the Docker adapter executes containers,
but no worker role consumes queue/lease and produces a project).

### C. Can an ExecutionRequest be executed by a real Worker?

**PARTIAL.** ExecutionRequest prepare/queue (P2-2), scheduler lease + fencing
(P2-3) and Worker lifecycle with fenced result admission (P2-4) are fully
implemented and PostgreSQL-tested. Real Docker container execution exists via
`DockerExecutionAdapter` (P3-5) and is integration-tested. But there is no
Worker *role* that: reads a leased ExecutionRequest, executes a real
software-building task (write Golden Project), collects content-addressed
artifacts, and submits a fenced result. P6 must add the worker role and a
real worker implementation.

### D. Is Verification machine-readable?

**YES.** `VerificationResult` (verdict PASS/FAIL/INCONCLUSIVE/ERROR/CANCELLED),
`VerificationCheckResult` list, `Evidence` refs and exact artifact hash are
recorded via `verification.record_result` (ControlPlane, VERIFIER identity
only) and committed through `apply_verified_task_transition` (ADR-0028,
ADR-0031, invariant 2). Machine-readable JSON exists in PostgreSQL. P6 only
needs a real verifier *role* that runs pytest and produces such a result.

### E. Does failure enter Diagnosis / Recovery / Replan?

**YES (authority).** `RecoveryController.emit_execution_feedback` produces
structured feedback (FailureType/Severity/RecoveryLevel) → `feedback.created`
→ Situation (VERIFICATION_FAILED) → Diagnosis → Planner → bounded
RecoveryCycle/Attempt ledger (P2-5, ADR-0052) with `repair`/`retry`/`replan`/
`human_gate` actions. `test_recovery_postgres.py` proves the loop entry with
real PostgreSQL. Missing: an autonomous driver that invokes this loop
automatically after a FAIL.

### F. Can Human Gate truly pause and resume an autonomous run?

**YES.** `HumanGateAuthority` (request_gate → enter_project_waiting →
submit_decision → apply_decision) sets Project `WAITING_FOR_HUMAN`, requires
immutable resume context and re-executes the guard on resume (P3-1, ADR-0060).
The FastAPI/UI layer can only *submit decisions*, never resume directly.
`test_human_gate_postgres.py` proves the full lifecycle. P6 must demonstrate
no autonomous progress while WAITING and resume through the authority path.

### G. Is there run/session/correlation identity?

**YES.** `run_id` (AgentRun), `execution_request_id`, `correlation_id`,
`causation_id`, `trace_id`, `command_id` and scoped `idempotency_key` are
first-class and enforced. P6 will thread a run identity (run_id + correlation
prefix) through every command/event of one autonomous trial and record it in
evidence.

### H. Can one complete autonomous run's evidence be collected?

**PARTIAL.** Events, Situations, Decisions, Policy/Risk, Executions, Verifier
results, Gate records, Recovery attempts and immutable Decision Explain
snapshots all persist and are queryable; `DecisionExplainAuthority` captures
immutable explain snapshots. No harness collects them into a run evidence
bundle (`docs/evidence/p6/run-XXXX/`) or emits a run report.

### I. Capabilities that already exist (need only a Harness/roles)

- Project/Task authority, Event Log + Outbox + Relay + idempotent consumers
- Situation / Diagnosis / Planning / Policy / Risk / Selection / Budget
- Capability registry, Context Bundle, Sandbox Profile compilation
- ExecutionRequest prepare/queue, Scheduler lease/fencing/locks
- Worker lifecycle (start_run, artifact/evidence/usage admission, result)
- Verification plan/result/transition closure
- Recovery feedback + bounded attempts
- Human Gate + Project waiting/resume
- Decision Explain / Audit / Trace (immutable)
- Artifact stores (local content-addressed + S3), Secret handles, OTLP
- Docker execution adapter, FastAPI app + OIDC + Human Gate UI
- 22 migrations, PostgreSQL 14/16 regression, P5 CI

### J. Capabilities that are genuinely missing (must be implemented)

1. **Autonomous Run Harness** (`scripts/autonomous_run.py` + a reusable
   `hermes_runtime/trial` driver): submits a Software Request, creates run
   identity, drives the authority chain, waits, collects, asserts — never
   mutates authority directly (Observe/Submit/Wait/Collect/Assert only).
2. **Software Request API surface**: a minimal allowlisted production route to
   submit a request through the existing ProductApiFacade/application boundary
   (keeps the API semantic, no generic mutation).
3. **Real Worker role + real worker implementation**: consumes a leased
   ExecutionRequest and builds the Golden Project in a workspace (this is the
   "HOW"; the factory still decides WHAT/WHY/WHEN/WHETHER).
4. **Real Verifier role**: runs pytest against the produced artifact and
   records a machine-readable VerificationResult through the authority path.
5. **Golden Project** (`examples/golden-todo/`): real FastAPI + PostgreSQL +
   JWT + pytest + OpenAPI + Docker Compose + CI + README; `docker compose up`
   boots it and `pytest` passes.
6. **Failure injection scenarios** wired through the real runtime (verification
   failure, worker crash/SIGKILL, duplicate execution, artifact tampering,
   human gate), each with invariant assertions.
7. **Evidence collector + run report** under `docs/evidence/p6/run-XXXX/`.
8. **P6 CI workflow** (fast validation + full autonomous trial job).
9. **P6 acceptance matrix + completion report**.

## 4. P6 architecture plan

### 4.1 Boundary (must not change)

- Proteus Control Plane (PostgreSQL authority) remains the only authority.
- Harness/worker/verifier/failure-injector never write authority directly:
  they only submit semantic commands through application services or read
  through query stores.
- No mock PASS, no fake artifact, no direct DB state surgery in the trial
  itself. Failure injection uses *real* process termination, *real* artifact
  mutation, *real* failing pytest cases, *real* PostgreSQL, *real* Docker.

### 4.2 Shape

```text
scripts/autonomous_run.py          CLI entrypoint
hermes_runtime/trial/              new package: driver + roles + report
  run_harness.py                    harness: submit/wait/collect/assert
  driver.py                         autonomous lifecycle driver (authority-only)
  workers/golden_worker.py          real Worker role (builds golden-todo)
  verifiers/golden_verifier.py      real Verifier role (pytest -> result)
  evidence.py                       evidence collector + run report writer
  scenarios/                        failure-injection scenario drivers
examples/golden-todo/               P6-2 Golden Project (real product)
docs/P6_AUTONOMOUS_PRODUCTION_TRIAL_ACCEPTANCE_MATRIX.md
docs/P6_AUTONOMOUS_PRODUCTION_TRIAL_REPORT.md
docs/evidence/p6/run-XXXX/          generated run evidence
.github/workflows/hermes-p6.yml     P6 CI
```

Driver flow (happy path, all through existing authority services):

```text
Software Request (API/command)
  -> project.create (ControlPlane)
  -> task graph patch + readiness (ControlPlane)
  -> Situation (task.readiness_recomputed -> work_available)
  -> Planner (schedule_ready_task -> worker-executable action)
  -> Policy / Risk / Selection + Reservation
  -> Capability match / Context / Sandbox freeze
  -> execution.prepare_request -> QUEUED
  -> Scheduler register + lease (fencing token)
  -> Worker start_run -> real golden-worker subprocess writes project files,
     runs pytest in-workspace -> artifact candidates -> fenced result
  -> Verification plan -> real verifier runs pytest -> VerificationResult
  -> ApplyVerifiedTaskTransition (task PASSED)
  -> Project guard facts -> transition -> ... -> ACCEPTED (delivery)
```

Failure paths use the same authority chain: FAIL -> feedback -> situation
(VERIFICATION_FAILED) -> diagnosis -> planner (repair) -> new execution ->
verification PASS; Worker SIGKILL -> lease expiry -> fencing -> takeover ->
retry; duplicate command -> idempotency no-op; tampered artifact ->
verification FAIL closed; high-risk action -> Gate -> WAITING -> decision ->
resume.

### 4.3 Harness non-authority rule

The harness may:
- submit semantic commands through the existing application services with
  valid command metadata (command_id, idempotency_key, expected_version,
  actor, reason) — the same authority path the FastAPI layer uses;
- read via query stores / event log / evidence tables (read-only);
- wait on state changes; collect; assert invariants; write evidence files.

The harness must NOT:
- execute raw INSERT/UPDATE/DELETE against authority tables;
- fabricate PASS/FAIL, artifacts, or worker results;
- skip the authority path (no direct `projects.state=...`).

## 5. Implementation slices

Each slice ends with: code + tests + evidence + matrix update + diff check +
authority invariant check.

| Slice | Deliverable | Acceptance evidence |
| --- | --- | --- |
| P6-0 | Reconnaissance + this plan + matrix skeleton | docs above |
| P6-1 | `hermes_runtime/trial` harness + `scripts/autonomous_run.py` | harness tests (unit + PG), run identity threading |
| P6-2 | `examples/golden-todo` Golden Project | `docker compose up` smoke + `pytest` green + CI file |
| P6-3 | Happy path autonomous run (real PG, real worker subprocess, real pytest verifier, real Docker artifact) | `docs/evidence/p6/run-0001/` complete + report |
| P6-4 | Scenario A verification failure + recovery/replan | evidence: FAIL -> diagnosis -> repair -> PASS |
| P6-5 | Scenario B worker crash (SIGKILL) + fencing recovery | evidence: RUNNING -> crash -> takeover -> retry -> PASS; stale worker writes rejected |
| P6-6 | Scenario C duplicate execution idempotency | evidence: duplicate command -> no second authority fact |
| P6-7 | Scenario D artifact tampering fail-closed | evidence: hash mismatch -> FAIL closed -> recovery path |
| P6-8 | Scenario E human gate pause/resume | evidence: WAITING, no progress, decision, resume, PASS |
| P6-9 | Autonomous Run invariants (authority/idempotency/fencing/recovery/evidence/gate/audit/replan/delivery) | invariant test module green |
| P6-10 | Evidence collector + run report | `run-XXXX/*.json` + `run-report.md` |
| P6-11 | Acceptance matrix all PASS with test/evidence refs | matrix |
| P6-12 | P6 report + full regression (no-DB, PG16, Docker, external adapters) + compileall + diff check + migration continuity | report + CI green |

## 6. Acceptance strategy

- Acceptance rows list requirement, implementation, test, evidence, status.
- PASS requires test/runtime evidence, never "implemented" wording alone.
- Full P6 trial runs against a dedicated PostgreSQL container labeled
  `hermes.task=p6-autonomous-trial` and real Docker; external adapters reuse
  the P5 MinIO/Vault/OTLP pattern.
- Regression gate: existing 497 tests stay green (no-DB + PostgreSQL 16 +
  Docker + external adapters); migrations stay 0001..0022 continuous with no
  new migration unless proven necessary (no schema change is anticipated).
- Security: no credentials committed; secret values never appear in handles,
  metadata, logs, events, evidence or artifacts; Golden Project gets its own
  `.env.example` and test secrets only.

## 7. Out of scope (P6 does NOT add)

Kubernetes, Kafka, Redis, Raft, multi-region, active-active, distributed
transactions, cloud-vendor expansion, multi-approver semantics, large-scale
scheduler optimization, cost optimization, massive concurrency.

## 8. Definition of Done (from task §21)

P6 is complete only when: reconnaissance done; plan done; harness done; Golden
Project done; happy path really ran; verification failure really recovered;
worker crash really recovered; duplicate execution really validated; artifact
tampering really fail-closed; human gate really paused/resumed; recovery/replan
really ran; final delivery succeeded; evidence complete; acceptance matrix all
PASS; report done; CI done; P0-P5 regression PASS; compileall PASS; diff check
PASS; migration continuity PASS; no authority bypass; no secret leakage; no
fake PASS; no undocumented workaround.

---

## 9. Execution status (updated during P6-1..P6-11)

All slices are implemented on branch `codex/p6-autonomous-production-trial`:

| Slice | Status | Evidence |
| --- | --- | --- |
| P6-0 | DONE | this plan |
| P6-1 | DONE | `hermes_runtime/trial/{driver,scenarios,harness}.py`, `scripts/autonomous_run.py`, `tests/test_p6_autonomous_trial.py` |
| P6-2 | DONE | `examples/golden-todo` (pytest 9/9, compose up verified) |
| P6-3 | DONE | happy path runs: Request -> Situation -> Planning -> Policy/Risk -> Selection -> Capability -> Execution -> genuine FAIL -> Diagnosis -> Repair -> Recovery -> independent PASS -> ACCEPTED; `docs/evidence/p6/run-*` |
| P6-4 | DONE | initial implementation genuinely fails (real pytest) and is recovered |
| P6-5 | DONE | worker SIGKILLed mid-run; lease relinquished, request requeued, re-acquired, re-run (attempt 2), PASS |
| P6-6 | DONE | same command + idempotency key -> identical receipt, one row |
| P6-7 | DONE | produced artifact mutated on disk; verifier fails closed ARTIFACT_HASH_MISMATCH; task FAILED |
| P6-8 | DONE | policy-required human gate: project WAITING_FOR_HUMAN -> human decision -> resumed (real commands + guard facts) |
| P6-9 | DONE | harness assertions per scenario (real outcomes, no mocks) |
| P6-10 | DONE | `docs/evidence/p6/run-*/{request,situation,diagnosis,planning,policy,selection,execution,verification,delivery}.json` + events/artifacts + run-report |
| P6-11 | DONE | `docs/evidence/p6/acceptance-matrix.md` all PASS |
| P6-12 | DONE | P6 report + full regression + compileall + diff check + migration continuity (0001..0024) |

### Runtime gap closures implemented (minimal, authority-conforming, ADR-0073)

The P6 trial proved that the P0-P5 runtime could not start fresh implementation
work through the real authority path. The following gaps were closed with the
smallest possible, fully documented changes; every P0-P5 test still passes:

1. **Entry-point deadlock**: the planner only emitted worker-executable
   candidates for `verification_failed` situations, so no fresh execution could
   ever start (P2/P3 tests seeded a candidate via raw SQL). Closed by a
   versioned registry extension `action-registry/1.1` adding the worker-executable
   `implement` action (`domain/planner.py` `P6_REGISTRY`, routing, SQL whitelist,
   candidate type CHECK, policy rule). `action-registry/1.0` is untouched (P1
   contract).
2. **Recovery task re-entry**: a task whose execution failed could never return
   to the ready pool (P2-5 tests raw-SQLed the transition). `hermes_emit_execution_feedback`
   now performs task re-entry inside the recovery authority transaction.
3. **Readiness trigger for dependency-free tasks**: a single fresh task becomes
   READY at patch time and no `task.readiness_recomputed` event fires. The
   analyzer now classifies `work_graph.patch.applied` readiness changes as
   `work_available` (migration 0024).
4. **Consumer liveness on unimplemented rules**: `policy.evaluated` /
   `agent.stalled` / `resource.missing` events crashed the situation consumer
   (classifier still fails closed, P1-pinned); the consumer now quarantines them
   and advances, so later events are still processed.
5. **Secret-guard false positive**: deterministic authority ids such as
   `risk-<hex>` matched the `sk-[A-Za-z0-9]{12,}` API-key pattern. The pattern
   now requires `sk-` not preceded by an alphanumeric (Python capability guard
   and all SQL guards tightened in migration 0024); real API keys still fail
   closed.

No P0-P5 acceptance criterion, authority invariant, or API contract was
changed; migration continuity is 0001..0024.

