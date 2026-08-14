# ADR-0064: P3-5 Production Docker Execution Runtime Authority

## Status

ACCEPTED

## Phase

P3-5

## Context

ADR-0059 required one provable production execution target before Hermes can
claim production sandbox execution. P2 `contract-only/1.0` SandboxProfiles were
authority contracts only; they did not spawn containers, prove filesystem or
network isolation, collect artifacts, propagate fencing into process metadata or
record external side-effect receipts.

## Decision

P3-5 chooses Docker target 1.0 as the first production execution adapter.

`DockerSandboxProfile` compiles into deterministic `DockerRunPlan` records with
compiler/adapter version, image policy, structured command args, non-root user,
read-only root filesystem, deny-by-default network, `cap-drop=ALL`,
`no-new-privileges`, tmpfs, pids/memory/cpu/timeout/output limits, environment
allowlist, secret handles and declared export paths. The compiler fails closed
when required constraints cannot be represented.

`DockerExecutionAdapter` performs the external Docker action outside the
PostgreSQL authority transaction. It creates deterministic container
names/labels containing request/run/lease/fencing/trace refs, runs without DB
or Docker socket credentials in the container, collects bounded stdout/stderr,
collects only declared export artifacts with content hashes/provenance, marks
usage dimensions that Docker Desktop cannot prove as untrusted/unknown, and
cleans the task-created container by exact deterministic name.

`0022_production_docker_execution.sql` records the authority side:

- current Docker process lifecycle in `docker_process_runs`;
- append-only `docker_process_observations`;
- append-only `external_side_effect_receipts`;
- append-only `docker_process_reconcile_findings`.

Side-effect receipts are external facts, not Hermes Project/Task authority. They
require current lease/fencing refs; irreversible effects without Human Gate
authorization fail closed. Same side-effect key/same intent converges, while
same key/different intent conflicts. Effect-before-receipt uncertainty is
represented as an explicit reconcile finding.

## Consequences

P3-5 adds the first real Docker execution target without changing P2 Worker
Result admission or Verification authority. Docker daemon access remains a
high-privilege adapter/process-manager capability and is not exposed to Worker
containers. Docker Desktop/macOS isolation is documented as a local VM boundary,
not as a full multi-tenant cloud hardening proof.

P3-6 still needs cross-slice end-to-end hardening and completion summary.

## Evidence

- [`0022_production_docker_execution.sql`](../../hermes-runtime/migrations/0022_production_docker_execution.sql)
- [`docker_execution.py`](../../hermes-runtime/src/hermes_runtime/domain/docker_execution.py)
- [`application/docker_execution.py`](../../hermes-runtime/src/hermes_runtime/application/docker_execution.py)
- [`docker_adapter.py`](../../hermes-runtime/src/hermes_runtime/infrastructure/docker_adapter.py)
- [`postgres_production_execution.py`](../../hermes-runtime/src/hermes_runtime/infrastructure/postgres_production_execution.py)
- [`test_docker_execution_domain.py`](../../hermes-runtime/tests/test_docker_execution_domain.py)
- [`test_docker_adapter.py`](../../hermes-runtime/tests/test_docker_adapter.py)
- [`test_production_execution_postgres.py`](../../hermes-runtime/tests/test_production_execution_postgres.py)
- [`test_production_execution_permissions.py`](../../hermes-runtime/tests/test_production_execution_permissions.py)
