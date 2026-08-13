# ADR-0048: P2 Capability Registry, Context Selector and Sandbox Compiler Minimums

- Status: ACCEPTED
- Phase: P2-1
- Related specifications: Core Runtime Design V1.2 §§16, 19, 21, 26; Runtime Normative Spec §19; P2 Execution Admission Spec §10; ADR-0013; ADR-0047

## Context

P2-0 established that WorkerTemplate, Context Bundle and SandboxProfile must be
frozen before any request becomes `QUEUED`, but left three runtime decisions
open: the WorkerTemplate trust taxonomy, the minimal Context selector
vocabulary, and the first SandboxProfile compiler target.

If these decisions remain implicit, P2-1 could accidentally match Workers by
identity string, copy mutable context into a bundle, ignore unknown critical
selectors, or compile a sandbox profile that weakens Policy/Risk constraints.

## Decision

P2-1 implements the minimum executable contract in
`hermes-runtime/src/hermes_runtime/domain/capability.py` and
`hermes-runtime/migrations/0013_capability_context_sandbox.sql`.

### WorkerTemplate trust taxonomy

Trust is a finite ordered enum:

```text
UNTRUSTED < STANDARD < ELEVATED < PRIVILEGED
```

The rank values are `0`, `100`, `200` and `300`. A selected action requirement
matches only when the immutable WorkerTemplate revision has rank greater than or
equal to the required minimum. Unknown trust values fail closed. Identity
strings are never trust proof. Changing trust requires creating a new immutable
WorkerTemplate revision; mutable availability/admission state is stored
separately.

### Context selector vocabulary and limits

P2-1 supports only typed selectors for:

- `project`
- `task`
- `selected_action`
- `decision_record`
- `artifact`
- `verification_plan`
- `policy_decision`
- `risk_assessment`
- `resource_reservation`
- `evidence`

Selectors are normalized and deterministically sorted. Wildcards such as an
entire database, repository or all evidence are forbidden. Unknown selector
types fail closed.

The first size limits are:

- at most 32 selectors;
- at most 64 resolved manifest items;
- at most 4096 canonical JSON bytes per item;
- at most 65536 canonical JSON bytes per manifest.

The Context Bundle stores only immutable refs, versions, hashes and non-secret
metadata. It does not copy mutable object bodies, read arbitrary filesystem
paths or transmit Worker-visible context.

### Sandbox compiler target

The first compiler target is backend-neutral:

```text
contract-only/1.0
```

It proves the compile contract without claiming Docker, Process or Kubernetes
isolation has started.

Supported constraint vocabulary:

- `network_access`
- `filesystem_write`
- `environment`
- `secret_access`
- `production_access`
- `allowed_tools`
- `forbidden_paths`
- `max_external_api_calls`
- `required_mitigations`
- `lock_scopes`
- `execution_time_ms`
- `cpu_time_ms`
- `storage_bytes`
- `process_count`
- `output_bytes`

Unknown mandatory constraints fail closed. WorkerTemplate unsupported mandatory
constraints fail closed.

Merge rules:

- allowlists intersect;
- deny lists union;
- numeric upper bounds take the minimum;
- required mitigations union;
- network, filesystem, environment, secret and lock scopes can only shrink;
- secret values are forbidden; secret handles must use stable refs;
- compilation failure leaves no valid SandboxProfile.

P2-1 includes a pure conformance evaluator that checks the compiled profile is
less permissive than or equal to every upstream constraint source.

## Consequences

- `P2-CAP-001`, `P2-CTX-001` and `P2-SBX-001` can be marked PASS only for their
  authority facts and freeze objects.
- `P2-LOCK-001` is not fully PASS because P2-1 only normalizes lock scope
  declarations inside requirements/profiles; lock acquisition and conflict
  handling remain P2-2/P2-3.
- P2-1 does not implement ExecutionRequest, Queue, Scheduler, Lease, Worker
  spawn, real sandbox execution, Result, CompletionClaim, UsageRecord, Human
  Gate lifecycle or P3 quarantine/reconcile.
