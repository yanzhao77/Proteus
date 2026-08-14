# ADR-0054: P3 Project Waiting Records and Immutable Resume Context

## Status

ACCEPTED

## Phase

P3-0

## Context

ADR-0022 kept V1.2 waiting and recovery states in the schema but deferred their
protocol-specific commands. P3 must support Human, Resource, Dependency and
Recovery waiting without multiplying Project states into every possible
combination.

## Decision

P3 uses:

```text
Project mainline state
+ typed waiting record
+ immutable resume context
```

A waiting record states the reason, scope, blocked command, owner authority,
timeout behavior and current version. The resume context captures project/task
versions, causation Event, Situation/Diagnosis/Planning/Policy/Risk/Budget/
Decision refs, Gate refs, Work Graph snapshot, Evidence/Artifact hashes,
open executions, Lease/fencing refs and replay cursor.

Resume is a new guarded Command. It reloads current facts and re-executes the
current Guard; it does not trust a historical boolean. Stale Gate Decisions,
invalid Evidence, budget hard stops or version conflicts fail closed. Cancel has
precedence over waiting, and terminal Projects cannot resume.

## Consequences

Project state remains comprehensible while P3 can model multiple concurrent
blocking causes. Waiting records become operational facts; Human Gate still
cannot directly mutate Project or Task state.

## Evidence

- [P3 Operational Governance Spec §5](../specs/Hermes_P3_Operational_Governance_Normative_Spec_V1.0.md#5-project-waiting-and-resume-context)
- [P3 Acceptance Matrix](../P3_OPERATIONAL_GOVERNANCE_ACCEPTANCE_MATRIX.md)
