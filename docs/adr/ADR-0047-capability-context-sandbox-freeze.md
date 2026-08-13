# ADR-0047: Capability, Context and Sandbox Freeze Before Queue

- Status: ACCEPTED
- Phase: P2-0
- Related specifications: Core Runtime Design V1.2 §§16, 19, 21, 26; Runtime Normative Spec §19; P2 Execution Admission Spec §10; ADR-0013

## Context

Capability matching, Context Bundle construction and SandboxProfile compilation
can change execution safety. If they happen after queueing or after Worker
pickup, a Scheduler may lease a request that can never safely execute or that
weakens Policy/Risk constraints.

## Decision

Before ExecutionRequest enters `QUEUED`, P2 must freeze:

- WorkerTemplate revision and capability match evidence;
- immutable Context Bundle manifest and hash;
- SandboxProfile hash, compiler version and constraint mapping evidence.

WorkerTemplate revision must include capabilities, revision identity,
availability, trust level, allowed tools, adapter type, sandbox support and
disabled/deprecated state. Capability matching is deterministic and replayable.

Context Bundle uses a minimal selector and immutable manifest. Secret handles are
allowed; secret values are forbidden in Events, Outbox, CommandReceipt, Context,
Artifact and logs.

SandboxProfile Compiler may only preserve or tighten Policy/Risk constraints.
If a mandatory constraint cannot be represented, compilation fails closed.

Registry or Policy updates after `QUEUED` do not silently mutate the request.
They require an explicit invalidation, cancellation or requeue command with audit
Event/Outbox.

## Consequences

- P2-1 can be implemented and tested before durable Queue.
- Scheduler does not perform first-time capability/context/sandbox admission.
- Worker receives frozen execution inputs and cannot widen its own permissions.
