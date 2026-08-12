# Hermes Runtime Conformance Test Specification V1.0

**Status:** NORMATIVE DRAFT  
**Version:** 1.0.0  
**Related:** [Runtime Normative Specification](Hermes_Runtime_Normative_Spec_V1.0.md), [Command/Event Protocol](Hermes_Command_Event_Protocol_V1.0.md), [Execution Lease Protocol](Hermes_Execution_Lease_Protocol_V1.0.md)

## 1. Test contract

Every test below MUST assert returned result, final authoritative state, Event Log, Outbox, audit/quarantine where applicable, and forbidden side effects. Empty tests or tests without assertions are non-conforming. PostgreSQL concurrency tests MUST use independent connections/processes and deterministic barriers.

Suggested levels: `UNIT` (pure domain), `PG` (PostgreSQL integration), `MULTI` (multi-process integration), `E2E`. `Gate` identifies the implementation phase whose conformance claim is blocked by failure.

## 2. Common fixtures

- `proj_001` with authoritative versioned state.
- `task_102` with current Artifact pointer and VerificationPlan where needed.
- Append-only Event Log, transactional Outbox and CommandRecord tables.
- A controllable database clock and separate service identities.
- Quarantine and audit stores.
- No external broker is required; relay may publish to a deterministic test transport.

## 3. V1.2 §30.2 required scenarios

### CT-001 — Duplicate Event does not create duplicate Task

- **Clause / purpose:** V1.2 §30.2 #1, Event idempotency.
- **Given:** Project has no `task_repair_1`; consumer checkpoint is sequence 10; inbox empty.
- **When:** The same `feedback.created` Event id and sequence 11 is delivered twice.
- **Then:** Exactly one repair Task/effect exists; inbox has one Event id; checkpoint is 11; both deliveries succeed idempotently.
- **Invariants:** Event at-least-once, idempotent consumer, Task identity uniqueness.
- **Initial → final persistence:** task count 0 → 1; inbox 0 → 1; checkpoint 10 → 11.
- **Event / Outbox:** No duplicate downstream Event or Outbox message.
- **Forbidden:** duplicate Task, repeated budget allocation, sequence 12 fabrication.
- **Level / gate / phase:** PG; yes; P0.

### CT-002 — Two Schedulers compete; one Lease wins

- **Clause / purpose:** V1.2 §30.2 #2, atomic Lease ownership.
- **Given:** One QUEUED ExecutionRequest, no owner, token 6; two DB connections at a barrier.
- **When:** Both Schedulers acquire simultaneously.
- **Then:** One succeeds with token 7; one reports contention; exactly one owner is stored.
- **Invariants:** Lease atomicity, monotonic fencing.
- **Initial → final persistence:** unleased/token 6 → one owner/token 7/LEASED.
- **Event / Outbox:** One `execution.leased` Event/Outbox.
- **Forbidden:** two winners, token 8 from the losing attempt, process-lock-only proof.
- **Level / gate / phase:** MULTI+PG; yes; P2.

### CT-003 — Stale fencing Result is quarantined

- **Clause / purpose:** V1.2 §30.2 #3 and Invariant 12.
- **Given:** Current owner W2 token 8; old W1 token 7; Task and Artifact pointer unchanged.
- **When:** W1 submits CompletionClaim/Result with token 7.
- **Then:** Submission returns `STALE_FENCING_TOKEN`; full payload is quarantined and audited.
- **Invariants:** stale Worker cannot write authority.
- **Initial → final persistence:** current request/token/pointer/settlement unchanged; quarantine 0 → 1.
- **Event / Outbox:** `execution.result_quarantined`, no `artifact.current_changed`.
- **Forbidden:** Task transition, current Artifact update, current reservation settlement.
- **Level / gate / phase:** PG; yes; P2/P3.

### CT-004 — Policy DENY beats high ActionScore

- **Clause / purpose:** V1.2 §30.2 #4 and Invariants 7/9.
- **Given:** Action score 1.0; applicable PolicyDecision is DENY.
- **When:** Action Selection evaluates candidates.
- **Then:** Action is ineligible and no ExecutionRequest is created.
- **Invariants:** Policy cannot be bypassed; Risk/score do not authorize.
- **Initial → final persistence:** Decision records rejection; queue remains empty.
- **Event / Outbox:** `action.rejected` MAY be emitted; never `execution.queued`.
- **Forbidden:** score overriding Policy, Scheduler seeing denied Action.
- **Level / gate / phase:** UNIT + PG integration; yes; P1.

### CT-005 — Concurrent Budget reservations do not overspend

- **Clause / purpose:** V1.2 §30.2 #5 and Invariant 8.
- **Given:** limit 100, consumed 20, reserved 50; two requests reserve 20 each at a barrier.
- **When:** Separate transactions reserve concurrently.
- **Then:** Exactly one succeeds; final reserved is 70 and never exceeds available 80.
- **Invariants:** atomic reservation and versioning.
- **Initial → final persistence:** reserved 50 → 70; one valid Reservation.
- **Event / Outbox:** one `budget.reserved`, one rejected result.
- **Forbidden:** reserved 90, partial reservation, two success results.
- **Level / gate / phase:** MULTI+PG; yes; P1 before distributed P2 claim.

### CT-006 — Worker self-report cannot pass Task

- **Clause / purpose:** V1.2 §30.2 #6 and Invariants 1/2.
- **Given:** Task RUNNING, valid Worker Lease and Artifact Candidate.
- **When:** Worker submits `status=COMPLETED` and claims tests passed.
- **Then:** Task is at most COMPLETION_CLAIMED/VERIFYING; no formal verdict exists.
- **Invariants:** Agent is not state authority; Worker is not Judge.
- **Initial → final persistence:** RUNNING → COMPLETION_CLAIMED; claim/artifact candidate stored.
- **Event / Outbox:** `task.completion_claimed`; no `task.passed`.
- **Forbidden:** PASSED/FAILED Task, fabricated VerificationResult/Evidence.
- **Level / gate / phase:** PG/E2E; yes; P0.

### CT-007 — Artifact hash change invalidates old Verification

- **Clause / purpose:** V1.2 §30.2 #7 and Evidence integrity.
- **Given:** PASS Verification references hash A; current Artifact becomes hash B.
- **When:** Control Plane evaluates Task transition using old result.
- **Then:** Guard rejects `ARTIFACT_HASH_MISMATCH`; old result remains immutable.
- **Invariants:** current hash must match formal PASS.
- **Initial → final persistence:** current hash B and Task state unchanged; invalid applicability/audit recorded.
- **Event / Outbox:** rejection/audit Event; no `task.passed`.
- **Forbidden:** rewriting old Verification to B or accepting stale PASS.
- **Level / gate / phase:** UNIT+PG; yes; P0/P3 invalidation.

### CT-008 — Work Graph may cycle; Task DAG may not

- **Clause / purpose:** V1.2 §30.2 #8 and Invariant 11.
- **Given:** Work Graph has Feedback→Decision→Task→Verification→Feedback; Task A depends on B.
- **When:** Add Work Graph feedback edge, then propose B `DEPENDS_ON` A.
- **Then:** feedback edge succeeds; DAG patch is rejected atomically as cycle.
- **Invariants:** only `DEPENDS_ON` subgraph is acyclic.
- **Initial → final persistence:** Work edge added; Task dependency graph unchanged/version not incremented by rejected patch.
- **Event / Outbox:** one graph edge Event; one patch rejection audit.
- **Forbidden:** partial cyclic dependency or rollback of valid Work edge.
- **Level / gate / phase:** UNIT+PG; yes; P0.

### CT-009 — Human Gate requires resume context

- **Clause / purpose:** V1.2 §30.2 #9 and Invariant 6.
- **Given:** Gate Command lacks or references an invalid `resume_context_ref`.
- **When:** Control Plane handles open Gate.
- **Then:** Command is rejected; no OPEN Gate exists; related work is safely paused/unchanged per policy.
- **Invariants:** every Gate is resumable.
- **Initial → final persistence:** no Gate → no Gate; rejection CommandResult.
- **Event / Outbox:** optional `human_gate.rejected`; no `human_gate.opened`.
- **Forbidden:** OPEN Gate with null/broken context.
- **Level / gate / phase:** PG; yes; P3.

### CT-010 — Exhausted strategy Gate is complete

- **Clause / purpose:** V1.2 §30.2 #10 and escalation semantics.
- **Given:** Attempt ledger has all attempted strategies and eligible remaining options.
- **When:** L6 Human Gate is opened for exhaustion.
- **Then:** Gate includes all attempts, strategies, agents consulted, remaining options, recommendation, risks, exact question and resume context.
- **Invariants:** explainable Human Gate; no premature escalation.
- **Initial → final persistence:** active Situation → OPEN Gate linked to immutable attempt ledger/checkpoint.
- **Event / Outbox:** `human_gate.opened` with refs, not secret/full logs.
- **Forbidden:** omitted failed attempt, empty options, generic “AI cannot continue”.
- **Level / gate / phase:** UNIT+E2E; yes; P3.

## 4. Fault-injection scenarios

### FI-01 — Crash before transaction commit

- **Clause / purpose:** Runtime §17; atomic authority transaction.
- **Given:** Task v17 and no related Outbox/Event.
- **When:** Handler prepares mutation then process crashes before COMMIT.
- **Then:** Task remains v17; Command retry can execute once.
- **Invariants:** no uncommitted authority.
- **Initial → final:** state/Event/Outbox/CommandResult unchanged.
- **Event / Outbox:** none durable.
- **Forbidden:** visible v18 or published Event.
- **Level / gate / phase:** PG fault injection; yes; P0.

### FI-02 — Exception between state update and Outbox insert

- **Clause / purpose:** Command/Event §6/14; transactional outbox.
- **Given:** Command begins against Task v17.
- **When:** SQL update runs, injected exception occurs before Outbox insert.
- **Then:** entire transaction rolls back.
- **Invariants:** state and Outbox atomicity.
- **Initial → final:** Task v17 unchanged; no Event/Outbox/CommandResult.
- **Event / Outbox:** none.
- **Forbidden:** state without Event/Outbox.
- **Level / gate / phase:** PG; yes; P0.

### FI-03 — Relay crashes after Outbox commit, before publish

- **Clause / purpose:** V1.2 §7; relay recovery.
- **Given:** committed PENDING Outbox row.
- **When:** Relay crashes before transport publish.
- **Then:** lease expires/new Relay publishes same Event id.
- **Invariants:** durable at-least-once delivery.
- **Initial → final:** PENDING → PUBLISHED; authority unchanged.
- **Event / Outbox:** exactly one Event Log row; one or more attempts.
- **Forbidden:** lost Event or new logical Event id.
- **Level / gate / phase:** MULTI+PG; yes; P0.

### FI-04 — Event duplicate publish and delivery

- **Clause / purpose:** V1.2 §7.2; idempotent consumer.
- **Given:** one Event, consumer inbox empty.
- **When:** Relay publishes it twice.
- **Then:** consumer effect and inbox occur once; duplicate acknowledged.
- **Invariants:** at-least-once does not duplicate effects.
- **Initial → final:** one effect, one inbox, one contiguous checkpoint.
- **Event / Outbox:** original Event id retained.
- **Forbidden:** duplicate Task/transition/resource spend.
- **Level / gate / phase:** PG; yes; P0.

### FI-05 — Consumer crashes before checkpoint

- **Clause / purpose:** Command/Event §14; consumer recovery.
- **Given:** Event sequence 11, checkpoint 10.
- **When:** Consumer commits effect+inbox then crashes before checkpoint.
- **Then:** redelivery finds inbox, repeats no effect, advances checkpoint 11.
- **Invariants:** durable deduplication.
- **Initial → final:** effect/inbox one; checkpoint 10 → 11 after retry.
- **Event / Outbox:** no new domain Event unless effect itself specifies one once.
- **Forbidden:** second effect.
- **Level / gate / phase:** PG; yes; P0.

### FI-06 — Same Idempotency-Key and payload retry

- **Clause / purpose:** §4.4 Command semantics.
- **Given:** completed CommandRecord with canonical hash H.
- **When:** same scoped key, actor and payload H retry.
- **Then:** stored CommandResult is returned byte/semantically equivalent.
- **Invariants:** accepted Command executes once.
- **Initial → final:** all authority/Event counts unchanged.
- **Event / Outbox:** no duplicate.
- **Forbidden:** Guard rerun causing a second transition.
- **Level / gate / phase:** PG; yes; P0.

### FI-07 — Same Idempotency-Key, different payload conflict

- **Clause / purpose:** §4.4 Command integrity.
- **Given:** key maps to hash H1.
- **When:** same scoped key is submitted with H2.
- **Then:** `IDEMPOTENCY_CONFLICT`; original result remains.
- **Invariants:** key cannot alias different intent.
- **Initial → final:** no changes except security audit MAY be added.
- **Event / Outbox:** no domain mutation Event.
- **Forbidden:** execute H2 or overwrite CommandRecord.
- **Level / gate / phase:** PG; yes; P0.

### FI-08 — Expected version conflict

- **Clause / purpose:** V1.2 §4.3; optimistic concurrency.
- **Given:** entity current v18, Command expects v17.
- **When:** handler runs.
- **Then:** `VERSION_CONFLICT` reports current v18 and no mutation.
- **Invariants:** no lost update.
- **Initial → final:** authority v18 unchanged; rejected CommandResult stored per policy.
- **Event / Outbox:** no state-change Event.
- **Forbidden:** auto-rebase or blind overwrite.
- **Level / gate / phase:** PG; yes; P0.

### FI-09 — Lease expired; old Worker returns

- **Clause / purpose:** V1.2 §15.4/Invariant 12.
- **Given:** token 7 expired and token 8 granted.
- **When:** Worker with token 7 submits.
- **Then:** same outcome as CT-003; quarantine and audit.
- **Invariants:** fencing is authoritative.
- **Initial → final:** current execution/token/pointers unchanged; quarantine +1.
- **Event / Outbox:** quarantine Event only.
- **Forbidden:** accepted Result or settlement.
- **Level / gate / phase:** PG; yes; P2/P3.

### FI-10 — Heartbeat lost while Worker still runs

- **Clause / purpose:** Lease §8/13; uncertain execution.
- **Given:** Worker token 7 alive but heartbeat path partitioned.
- **When:** Lease expires and token 8 is granted, then old heartbeat/result arrives.
- **Then:** token 7 operations are rejected/quarantined; token 8 remains owner.
- **Invariants:** DB clock/Lease, not Worker liveness claim, controls authority.
- **Initial → final:** token 8 remains; old payload audited.
- **Event / Outbox:** expiry/regrant and quarantine facts.
- **Forbidden:** extending superseded Lease.
- **Level / gate / phase:** MULTI; yes; P2.

### FI-11 — Scheduler crashes while holding Lease

- **Clause / purpose:** Lease §13; scheduler recovery.
- **Given:** Scheduler A granted token 7.
- **When:** A crashes without release.
- **Then:** no takeover before expiry; after expiry B obtains token 8.
- **Invariants:** leases self-expire and tokens increase.
- **Initial → final:** owner A/token7 → owner B/token8.
- **Event / Outbox:** lease granted/regranted facts.
- **Forbidden:** manual unfenced unlock or simultaneous owner.
- **Level / gate / phase:** MULTI+PG; yes; P2.

### FI-12 — Control Plane restart with checkpoint/replay/reconcile

- **Clause / purpose:** V1.2 §25; recovery.
- **Given:** checkpoint at sequence 100; Events through 105; one orphan Lease and unsettled usage.
- **When:** Control Plane restarts.
- **Then:** replay rebuilds recovery view; authoritative state is read; reconcile issues idempotent Commands; cursor becomes 105.
- **Invariants:** replay does not overwrite authority; recovery is auditable.
- **Initial → final:** orphan resolved, usage settled/released, checkpoint advanced.
- **Event / Outbox:** `recovery.reconciled` and specific correction Events.
- **Forbidden:** fold-based blind replacement of newer state.
- **Level / gate / phase:** E2E; yes; P3.

### FI-13 — Verification Artifact hash mismatch

- **Clause / purpose:** V1.2 §19/20; exact content verification.
- **Given:** VerificationResult says hash A; submitted/current target is hash B.
- **When:** outcome Command is admitted.
- **Then:** reject and audit mismatch; Task unchanged.
- **Invariants:** PASS binds exact Artifact.
- **Initial → final:** Task/version/pointer unchanged; result preserved as invalid for target.
- **Event / Outbox:** rejection audit only.
- **Forbidden:** Task PASS or rewriting hash.
- **Level / gate / phase:** PG; yes; P0.

### FI-14 — Verifier identity invalid

- **Clause / purpose:** V1.2 §19.4/Invariant 14.
- **Given:** verifier identity equals Worker run or lacks verifier policy.
- **When:** VerificationResult is submitted.
- **Then:** reject; security audit; Task unchanged.
- **Invariants:** Worker/Judge isolation.
- **Initial → final:** no valid Verification attached.
- **Event / Outbox:** `verification.rejected` audit MAY be emitted.
- **Forbidden:** formal verdict admission.
- **Level / gate / phase:** PG; yes; P0.

### FI-15 — Worker forges PASS/FAIL verdict

- **Clause / purpose:** V1.2 Invariants 1/2.
- **Given:** Worker identity and valid execution Lease.
- **When:** Worker invokes verdict/state transition Command or embeds PASS in Result.
- **Then:** command rejected; embedded claim remains untrusted text; audit created.
- **Invariants:** verdict and state authority separation.
- **Initial → final:** Task state unchanged or only CompletionClaim admitted.
- **Event / Outbox:** security/audit Event; no `task.passed/failed`.
- **Forbidden:** formal VerificationResult or Task verdict.
- **Level / gate / phase:** PG/E2E; yes; P0.

### FI-16 — Reservation succeeds but ExecutionRequest creation fails

- **Clause / purpose:** V1.2 §13/15; accounting coupling.
- **Given:** sufficient budget and no request.
- **When:** exception occurs after reservation calculation but before request becomes QUEUED.
- **Then:** same transaction rolls back, or reconcile releases explicit orphan; no runnable request.
- **Invariants:** no leaked reservation.
- **Initial → final:** reserved unchanged after recovery; request absent/FAILED_PREPARATION.
- **Event / Outbox:** no `execution.queued`; optional release/reconcile Event.
- **Forbidden:** active reservation with no owner indefinitely.
- **Level / gate / phase:** PG; yes; P1/P2.

### FI-17 — Execution completes before usage settlement crash

- **Clause / purpose:** V1.2 §13/25; settlement recovery.
- **Given:** accepted Result and consumption samples; reservation unsettled.
- **When:** process crashes before settlement commit.
- **Then:** restart detects unsettled usage and settles exactly once, releasing remainder.
- **Invariants:** every run accounted; no double charge.
- **Initial → final:** unsettled → SETTLED; consumed increases once; reserved decreases.
- **Event / Outbox:** one `budget.settled` effect/Event.
- **Forbidden:** run closed with unaccounted usage or duplicate settlement.
- **Level / gate / phase:** PG/E2E; yes; P1/P3.

### FI-18 — Outbox DLQ redrive

- **Clause / purpose:** V1.2 §7; recover poison/transient delivery.
- **Given:** DEAD_LETTERED message with resolved cause and original Event id.
- **When:** authorized redrive occurs.
- **Then:** message returns to PENDING, publishes, consumer applies once, audit records redrive.
- **Invariants:** redrive preserves identity and idempotency.
- **Initial → final:** DLQ → PUBLISHED; checkpoint advances contiguously.
- **Event / Outbox:** same Event id/payload/schema; new attempt metadata.
- **Forbidden:** new logical Event or bypass preceding gap.
- **Level / gate / phase:** PG/E2E; yes; P0 operations.

### FI-19 — Unknown non-critical Event field

- **Clause / purpose:** V1.2 §7 schema compatibility.
- **Given:** supported schema plus an unknown optional field.
- **When:** consumer processes Event.
- **Then:** known semantics apply; field is ignored/preserved safely; checkpoint advances.
- **Invariants:** backward-compatible additive evolution.
- **Initial → final:** expected idempotent effect committed once.
- **Event / Outbox:** no DLQ.
- **Forbidden:** rejection solely for optional field.
- **Level / gate / phase:** UNIT+PG; yes; P0.

### FI-20 — Unknown critical Event state

- **Clause / purpose:** V1.2 §7; fail-closed schema handling.
- **Given:** Event contains unknown critical state/enum.
- **When:** consumer processes it.
- **Then:** no domain effect; partition checkpoint does not pass Event; schema quarantine/DLQ and alert created.
- **Invariants:** unknown authority values never default.
- **Initial → final:** authority/checkpoint unchanged; DLQ +1.
- **Event / Outbox:** original Event retained.
- **Forbidden:** mapping to READY/FAILED/other default or skipping sequence.
- **Level / gate / phase:** UNIT+PG; yes; P0.

## 5. Coverage and phase gates

| Phase | Blocking tests |
| --- | --- |
| P0 | CT-001, CT-006, CT-007, CT-008; FI-01-08, FI-13-15, FI-18-20 |
| P1 | CT-004, CT-005; FI-16-17 accounting portions |
| P2 | CT-002, CT-003; FI-09-11; FI-16 execution coupling |
| P3 | CT-009, CT-010; FI-12, quarantine/reconcile portions of CT-003/FI-09/FI-17 |

All ten V1.2 §30.2 scenarios are covered in original order by CT-001 through CT-010. All twenty requested fault injections are covered by FI-01 through FI-20. A skipped blocking test means the phase is not conformant; it is not a pass.

## 6. Open questions

- CI provisioning mechanism for PostgreSQL multi-process tests.
- Standard fault-injection hook API.
- Performance thresholds for relay backlog and reconcile completion; correctness is already required.
