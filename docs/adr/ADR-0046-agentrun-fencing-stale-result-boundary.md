# ADR-0046: AgentRun Evolution, Fencing and Stale Result Boundary

- Status: ACCEPTED
- Phase: P2-0
- Related specifications: Core Runtime Design V1.2 §§15-17, 21, 26, 30; Execution Lease Protocol §§6-13; P2 Execution Admission Spec §§11-12; ADR-0011; ADR-0029; ADR-0030

## Context

P0 introduced minimal AgentRun identity to bind Worker and Verifier provenance.
P2 must add execution attempts, Lease ownership, fencing token checks, usage and
result admission without creating a second parallel Run model or letting stale
Workers mutate authority.

## Decision

P2 evolves the existing AgentRun authority. It must relate:

```text
ExecutionRequest -> attempt -> AgentRun(kind=WORKER)
AgentRun -> Lease owner/token while current
AgentRun -> Result, UsageRecord, Artifact Candidate and Evidence Candidate
CompletionClaim -> AgentRun + ExecutionRequest + fencing token
VerificationResult -> independent AgentRun(kind=VERIFIER)
```

Every Worker-originating authority write must include ExecutionRequest ID,
attempt ID, AgentRun ID, lease owner, fencing token, request version, lease
version, payload hash and idempotency key.

PostgreSQL authority clock decides Lease expiry. Every Lease grant/re-grant
increments the fencing token. Renew by the current owner keeps the token. Old
token, wrong owner, wrong AgentRun, stale request version or mismatched payload
cannot mutate current authority.

Stale payloads must be durably quarantined with request, owner, submitted token,
current token, hashes, metrics, received time and reason. P2 implements minimal
quarantine admission. P3 owns retention, review, adoption, redrive and full
reconcile operations.

## Consequences

- CT-002 and FI-11 belong to P2-3.
- CT-003 core, FI-09 and FI-10 result rejection/quarantine belong to P2-4.
- Full quarantine operations and recovery adoption remain P3.
- Verification remains independent and cannot be authorized by Worker token.
