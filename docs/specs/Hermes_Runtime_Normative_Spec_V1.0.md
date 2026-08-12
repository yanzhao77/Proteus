# Hermes Runtime Normative Specification V1.0

**Status:** NORMATIVE DRAFT  
**Version:** 1.0.0  
**Applies to:** HASF Core Runtime V1.2  
**Date:** 2026-08-12

Related documents:

- [Core Runtime Design V1.2](../Hermes_Autonomous_Software_Factory_Core_Runtime_Design_V1.2.md)
- [Command and Event Protocol](Hermes_Command_Event_Protocol_V1.0.md)
- [Execution Lease Protocol](Hermes_Execution_Lease_Protocol_V1.0.md)
- [Conformance Test Specification](Hermes_Conformance_Test_Spec_V1.0.md)
- [ADR index](../../ARCHITECTURE_DECISIONS.md)

---

## 1. Normative language

`MUST` / `MUST NOT` 表示合规实现的硬性要求；`SHOULD` / `SHOULD NOT` 表示除非有记录充分的理由否则应遵守；`MAY` 表示可选行为。每条关键要求以 `RT-*` 标识，并在 §24 定义验证方式。

## 2. Authority and scope

权威优先级为：V1.2 Runtime Invariants 和明确协议、本规范、V1.2 其他设计、V1.0 愿景、ADR。ADR 只能在上位规范允许的选项中作决定。

本规范定义 Project、Task、Execution、Verification、Human Gate、Artifact、Evidence 的权威边界和 P0-P3 阶段要求。它不规定 Web 框架、ORM、Python 版本、PostgreSQL 版本、消息系统或依赖管理工具。

非目标：完整 Event Sourcing、Raft、自研共识、Kafka、Kubernetes、跨地域 active-active、跨数据库分布式事务、图数据库、固定 Agent 部门或大量微服务。

## 3. Terms

| Term | Normative meaning |
| --- | --- |
| Authoritative State | Control Plane 在权威数据库中持久化的当前 Project、Task、Graph、Gate、Lease 或 Resource 状态 |
| Command | 请求改变权威事实的意图；可被接受或拒绝，不是已发生事实 |
| Event | 已提交事实的不可变记录；不得作为任意状态写命令 |
| Event Log | Append-only 审计与恢复记录；不是所有权威状态的唯一来源 |
| Outbox Message | 与权威变更同事务写入、等待异步发布的 Event 传输记录 |
| Projection | 为查询构造的可重建读模型，不是权威写入入口 |
| Snapshot | 某一时间点的权威状态副本，用于恢复加速 |
| Checkpoint | Snapshot 引用、Event cursor、open work、budget 和 gate 等恢复坐标 |
| Replay | 重放 Event 以重建 Projection、审计或恢复 Snapshot 之后的变化 |
| Reconcile | 比较权威状态、Event、Lease、Reservation 和外部执行事实并修复不一致 |
| CompletionClaim | Worker 声称一次执行完成的结构化请求，不是 verdict |
| VerificationResult | Verification Engine 对精确 Artifact hash 产生的正式 verdict 和 Evidence 引用 |
| Artifact | Worker 或系统产生的不可变内容对象 |
| Evidence | 支撑 Verification 或 Decision 的不可变证明记录 |

## 4. Runtime model

Hermes MUST 使用：

```text
Authoritative State
  + Append-only Event Log
  + Transactional Outbox
  + Checkpoint / Replay / Reconcile
```

Hermes MUST NOT 把权威状态降为普通可丢弃 Projection，MUST NOT 要求正常 Command 只能通过 `fold(events)` 写入。纯状态转移函数 MAY 用于 Guard 测试，但持久化仍由 Control Plane 权威事务完成。

## 5. Component responsibilities

| Component | Responsibility | Explicitly forbidden |
| --- | --- | --- |
| Control Plane | Command admission、Guard、版本检查、权威事务、状态提交 | 代替 Verification 产生 verdict |
| State Machine | 计算合法状态迁移和 guard result | I/O、任意绕过 Evidence 的迁移 |
| Worker | 执行 Action，提交 CompletionClaim、Result 和 Candidate | 产生正式 PASS/FAIL、写 Project/Task state |
| Verification Engine | 对精确 Artifact hash 产生 VerificationResult 和 Evidence | 直接持久化 Task state |
| Scheduler | Queue、Lease、Fencing、并发与取消 | 业务诊断、业务 retry、正式 verdict |
| Execution Adapter | 在 CompiledSandboxProfile 中执行并返回结构化 Result/metrics | 产生状态变更指令 |
| Main Hermes | 用户入口、查询、解释、提交用户意图 | 状态权威、代表用户授权 |
| Human Gate | 保存问题、选项、回答和 resume context | 将回答直接当状态迁移 |
| Policy Engine | ALLOW/DENY/REQUIRE_HUMAN 与约束 | 选择最佳 Action |
| Risk Engine | 风险和 mitigation | 授权 Action |
| Resource Accounting | allocation/reservation/consumption/settlement/release | 业务选优 |

## 6. State ownership matrix

| State | Persistent authority | Fact producer | Commit path |
| --- | --- | --- | --- |
| Project state | Control Plane / Project State Machine | Control Plane、Human decision candidate | guarded Command transaction |
| Task state | Control Plane / Task State Machine | Worker claim、Verification verdict | guarded Command transaction |
| ExecutionRequest state | Control Plane / Scheduler transaction | Scheduler、Worker lease facts | lease/fencing Command |
| Verification verdict | Verification Engine | independent verifier | immutable VerificationResult |
| HumanGate state | Control Plane Gate service | user answer、timeout | gate-specific Command transaction |
| Artifact current pointer | Control Plane Artifact Registry | Worker Artifact Candidate | admitted result transaction |
| Resource account | Resource Accounting | usage meter、Scheduler | atomic accounting transaction |

## 7. Read/write permission matrix

| Component | May submit Command | May produce facts | May directly write authoritative state |
| --- | --- | --- | --- |
| Worker | CompletionClaim / ResultSubmission | ExecutionResult、Artifact/Evidence Candidate、usage | No |
| Verification Engine | SubmitVerificationResult | PASS/FAIL/INCONCLUSIVE/ERROR verdict、Evidence | No |
| Scheduler | Acquire/Renew/Release/Cancel Lease | Lease facts | Only through controlled Command transaction |
| Control Plane | StateTransition and domain Commands | state transition Event | Yes, through guarded transaction only |
| Main Hermes | user-intent and Gate-answer Commands | no formal verdict | No |
| Human user | Gate Answer | human decision fact | No |
| Policy Engine | policy evaluation request | PolicyDecision | No |
| Execution Adapter | none | ExecutionResult and metrics | No |

`RT-AUTH-001`: 数据库权限和应用接口 MUST enforce 此矩阵。MUST NOT 暴露 `update_task_status`、`set_project_state` 或通用状态 PATCH。

### 7.1 State authority interfaces

State transition evaluation SHOULD be a pure function, but persistence is an authoritative transaction rather than Event folding:

```text
evaluate_transition(current_state, semantic_command, evidence_context)
  -> TransitionDecision(allowed | rejected, target_state, reasons)

get_current_state(entity_id)
  -> AuthoritativeState(version, state, relevant_refs)

commit_command(command, transition_decision)
  -> CommandResult
```

`evaluate_transition` MUST have no I/O, clock, random or global-state dependency. `commit_command` MUST reload/lock authoritative state, re-check `expected_version` and relevant Guard inputs, then atomically mutate state, append Event Log/Outbox and store CommandResult. A generic `set_state` interface is forbidden.

### 7.2 Verification interface

```text
verify(task_id, artifact_hash, criteria_version, verification_context)
  -> VerificationResult(status, evidence_refs, artifact_hash, verifier_identity)
```

The result status is `PASS | FAIL | INCONCLUSIVE | ERROR | CANCELLED`. This interface produces a verdict but has no state repository write capability. Applying the result requires a separate Control Plane Command.

### 7.3 Execution Adapter interface

```text
execute(compiled_sandbox_profile, input_artifact_refs, execution_context)
  -> ExecutionResult(
       exit_code,
       stdout_ref,
       stderr_ref,
       output_artifact_candidates,
       evidence_candidates,
       resource_metrics,
       policy_violations
     )
```

`ExecutionResult` MUST NOT contain `new_state`, `mark_passed`, `mark_failed` or a state transition instruction. The adapter MUST NOT have Project/Task state write credentials.

## 8. Project state authority

Project State MUST 使用 V1.2 §5 的状态集。迁移 MUST 由语义明确 Command 发起并校验 actor、idempotency、`expected_version`、Guard、Evidence、Policy、Budget 和 Gate 条件。Agent、Main Hermes、Verification 和 Scheduler 的输出只可作为 Command 输入。

`RT-STATE-001`: 每次成功 Project 迁移 MUST 在同一 PostgreSQL 本地事务中更新状态与 version，并插入 Outbox Event。

P0 MAY admit minimal Project Guard facts produced by future P1/P3 authorities, but it MUST NOT implement fake Policy, Budget, Evidence or Human Gate engines to synthesize permission. Missing authority facts MUST fail closed. Command payload booleans, `supporting_refs`, Candidate fields and Worker self-report MUST NOT be treated as facts. Each accepted Guard fact MUST be bound to the current Project, current Project version, source state, target state, authority, validity and currentness metadata.

## 9. Task state authority

Task 状态使用 V1.2 §6.2。Worker 完成后 Task 最多进入 `COMPLETION_CLAIMED` 或 `VERIFYING`。只有绑定当前 Artifact hash 的有效 VerificationResult 可支持 `PASSED` 或正式 `FAILED`。

`RT-STATE-002`: Control Plane MUST compare Task `expected_version`; 冲突 MUST 不产生状态或 Outbox 副作用。

## 10. Execution state authority

ExecutionRequest、Lease 和 AgentRun 是持久化运行时实体。Scheduler 只能通过 [Execution Lease Protocol](Hermes_Execution_Lease_Protocol_V1.0.md) 改变它们。业务失败 MUST 回到 Situation / Diagnosis / Planner；Scheduler retry 仅适用于执行层瞬态错误。

## 11. Verification verdict authority

`RT-VER-001`: Verification Engine 是正式 `PASS | FAIL` 的唯一 producer。它 MUST 使用与 Worker 独立的 identity 和 execution context，MUST 固定 `task_id + artifact_hash + criteria_version`。

`RT-VER-002`: Verification Engine MUST NOT 修改 Task state。Control Plane MUST 校验 verdict、Evidence、Artifact hash、verifier identity、current state、`expected_version` 和 Guard 后再提交迁移。

`INCONCLUSIVE` 与 `ERROR` 均 MUST NOT 使 Task PASSED；前者表示证据不足，后者表示验证器失败。

## 12. Human Gate authority

Gate Answer 是用户事实，不是状态迁移。Gate Command MUST 校验 Gate version、expiry、answer actor 和授权范围。OPEN Gate MUST 有可解析 `resume_context_ref`；否则创建失败。Main Hermes MAY 展示和提交回答，但 MUST NOT 代表用户批准。

## 13. Command lifecycle

所有改变权威事实的 Command MUST 包含：

```text
command_id  idempotency_key  expected_version  actor  reason
```

处理顺序和重复语义由 [Command and Event Protocol](Hermes_Command_Event_Protocol_V1.0.md) 定义。Command API MAY 存在，但 MUST 是 `:pause`、`:answer`、`:submit-result` 等语义操作，MUST NOT 是任意状态 PATCH。

## 14. CompletionClaim protocol

```json
{
  "claim_id": "claim_001",
  "task_id": "task_102",
  "run_id": "run_009",
  "execution_request_id": "exec_001",
  "fencing_token": 7,
  "claimed_status": "COMPLETED",
  "artifact_candidates": [
    {"artifact_id": "art_patch_010", "content_hash": "sha256:..."}
  ],
  "evidence_candidate_refs": ["evd_log_020"],
  "resource_usage_ref": "usage_run_009"
}
```

Control Plane MUST validate current Lease token, run identity, Artifact hashes and Policy constraints. Candidate admission MUST NOT imply Evidence validity or PASS. Stale results MUST enter quarantine.

## 15. VerificationResult to Task transition

```text
CompletionClaim admitted
  -> exact Artifact hash registered
  -> Verification Engine verifies hash + criteria
  -> VerificationResult + Evidence stored immutable
  -> SubmitVerificationOutcome Command
  -> actor / identity / hash / version / guard checks
  -> Task state + version mutated
  -> outbox event inserted
  -> one local transaction committed
```

Duplicate VerificationResult submission MUST return the stored Command result. A changed Artifact hash MUST invalidate applicability of the old result without deleting it.

## 16. Artifact and Evidence constraints

Artifact and Evidence MUST be immutable and content-hashed. Current pointers are authoritative mutable metadata controlled by Control Plane. Evidence invalidation MUST append an audit fact rather than overwrite content. Worker Result, Artifact Candidate and Evidence Candidate MUST NOT be treated as VerificationResult or validated Evidence.

`RT-EVD-001`: A PASSED Task MUST reference a PASS VerificationResult whose recorded Artifact hash equals the current verified Artifact hash.

## 17. Consistency and transaction boundaries

`RT-TXN-001`: Each authority mutation and corresponding Outbox insert MUST commit in one PostgreSQL local transaction. Cross-database distributed transactions MUST NOT be an MVP prerequisite.

Short transactions MAY independently protect Project state, Task/Graph patch, Lease and Reservation. External execution MUST NOT hold a database transaction. Coordination uses expected version, idempotency, Lease and compensation/reconcile.

## 18. Checkpoint, Replay and Reconcile

Checkpoint MUST include authoritative versions, Work Graph snapshot, Event cursor, active Situations, open executions, Artifact manifest, Evidence index, Budget snapshot and open Gates. Replay MAY rebuild Projection, audit behavior, or apply post-Snapshot facts during recovery; it MUST NOT be described as the sole normal write path.

Reconcile MUST detect orphan Lease, un-settled usage, stale Reservation, missing Outbox publication, late Result and invalid Evidence reference. Recovery actions MUST be idempotent and emit audit Events.

## 19. Security and isolation

- Worker and verifier identities and contexts MUST be separate.
- Every ExecutionRequest MUST reference an applicable PolicyDecision.
- RiskAssessment MUST NOT contain authorization.
- SandboxProfile Compiler MUST only preserve or tighten Policy constraints; unrepresentable mandatory constraints MUST fail closed.
- Capability Registry MUST match capability, not fixed organizational role.
- Secret values MUST NOT enter prompt, Event, Artifact or log.

## 20. Runtime invariants

The fourteen V1.2 §26 invariants are incorporated and MUST be enforced as follows:

| ID | Normative invariant | Primary validation |
| --- | --- | --- |
| RT-INV-001 | Agent MUST NOT directly modify Project or Task state. | CT-006, FI-15, DB role/API scan |
| RT-INV-002 | Only Verification Engine may produce formal PASS/FAIL. | CT-006, FI-14/15 |
| RT-INV-003 | Direct A2A communication is denied by default; collaboration is a controlled Task. | capability/credential contract test |
| RT-INV-004 | Every important State Transition MUST have an atomically committed Event/Outbox record. | FI-01/02 |
| RT-INV-005 | Important Artifact MUST have sufficient Evidence before supporting PASS/delivery. | CT-007, FI-13 |
| RT-INV-006 | Every OPEN Human Gate MUST have valid resume context. | CT-009/010 |
| RT-INV-007 | No Agent or ExecutionRequest may bypass Policy. | CT-004 |
| RT-INV-008 | Every resource-consuming Run MUST be reserved/accounted and settled or reconciled. | CT-005, FI-16/17 |
| RT-INV-009 | Risk Engine MUST NOT authorize an Action. | CT-004 and schema contract test |
| RT-INV-010 | Every execution Decision MUST trace to Situation, candidates, Policy, Risk, Budget and score configuration. | Decision trace integration test |
| RT-INV-011 | Task `DEPENDS_ON` graph MUST remain acyclic although Work Graph may cycle. | CT-008 |
| RT-INV-012 | Expired/stale Worker result MUST NOT mutate authority and MUST be quarantined. | CT-003, FI-09/10 |
| RT-INV-013 | Human Gate MUST remain independent from Main Hermes; user identity is preserved. | Gate identity contract test |
| RT-INV-014 | Worker and verifier MUST use independent identities and contexts. | FI-14/15 |

- `RT-INV-015`: Verification verdict authority, transition decision authority and persistence authority MUST remain separate.
- `RT-INV-016`: Authoritative state MUST NOT be reconstructed exclusively from Event Log as a normal operation requirement.
- `RT-INV-017`: Every accepted Command MUST have exactly one durable CommandResult, even if its Outbox Event is delivered more than once.

## 21. Phase requirements

| Phase | Required scope | Not a prerequisite for |
| --- | --- | --- |
| P0 | Authoritative State、Guard、Task DAG、Event Log、Outbox、idempotent consumer、Verification isolation、Agent write prohibition | P1 accounting or P2 cluster scheduler |
| P1 | Situation、Diagnosis、Planner、Policy、Risk、Resource Accounting、Selection、Decision Record | P0 vertical slice |
| P2 | Capability Registry、Scheduler、Queue、Lease/Fencing、Context Bundle、SandboxProfile、Worker lifecycle、Feedback | P0 authority proof |
| P3 | Human Gate、resume context、Checkpoint、Replay、Reconcile、Quarantine、Evidence invalidation、Explain、Audit | P0/P1 unit work |

Resource Accounting MUST be complete before distributed Worker scheduling is declared conformant, but MUST NOT block all P0 work.

P0 MUST persist the minimum AgentRun identity, Project/Task scope and independent execution context needed to authorize CompletionClaim and VerificationResult. This identity authority is not P2 execution scheduling: ExecutionRequest, Queue, Lease/fencing, heartbeat, spawn, retry and complete Worker lifecycle remain P2 requirements.

## 22. V1.0 conflict and evolution notes

V1.0 is visionary. Where it depicts Main Hermes selecting Agents or Evidence/Judge directly advancing state, V1.2 refines this: Control Plane selects via Scheduler and commits all state after Guard. V1.0 fixed Agent labels are capability examples, not persistent authority roles. V1.0 Human Gate interaction layer is refined into an independent Gate service parallel to Agent Runtime and Verification. These are semantic refinements, not deletion of the original goals.

The former root ADR decision “Event-Sourced Aggregate” conflicted with V1.2 §4.3 and is superseded by [ADR-0006](../adr/ADR-0006-authoritative-state-event-log-outbox.md) and [ADR-0007](../adr/ADR-0007-no-full-event-sourcing.md).

## 23. Recommended first vertical slice

Implement later, not in this documentation change:

```text
Worker submits CompletionClaim
-> Control Plane persists claim and Outbox atomically
-> Verification evaluates exact Artifact hash
-> VerificationResult produces formal PASS/FAIL
-> Control Plane validates identity, Evidence, hash, version and Guard
-> Task transition and Outbox commit atomically
-> duplicate delivery changes nothing
-> Worker direct PASS is rejected and audited
```

Minimum entities: Task, AgentRun, ExecutionRequest/Lease token, CompletionClaim, Artifact, Evidence, VerificationPlan, VerificationResult, CommandRecord, EventLog, OutboxMessage and AuditFinding.

Primary tests: CT-001, CT-006, FI-04, FI-05, FI-06, FI-13, FI-14 and FI-15 in the Conformance Specification. This slice proves authority separation, exact-hash verification, optimistic concurrency, transactional outbox, idempotency and hostile Worker rejection without requiring P1/P2 breadth.

## 24. Key requirement validation

| Requirement | Validation |
| --- | --- |
| RT-AUTH-001 | API surface scan, DB role test, CT-006/FI-15 |
| RT-STATE-001/002 | PostgreSQL fault injection FI-01/FI-02/FI-08 |
| RT-VER-001/002 | CT-006/CT-007/FI-13/FI-14 |
| RT-EVD-001 | CT-007 and current-pointer integration test |
| RT-TXN-001 | FI-01 through FI-05 plus DB atomicity assertions |
| RT-INV-015 | contract tests proving three distinct identities/interfaces |
| RT-INV-016 | architecture dependency and persistence review |
| RT-INV-017 | FI-06/FI-07 and CommandResult uniqueness constraint |

## 25. V1.2 traceability matrix

| V1.2 | Original requirement | New specification | ADR | Test | Status |
| --- | --- | --- | --- | --- | --- |
| §4 | Control Plane authority and atomic command | §§4-9,17 | ADR-0006,0008 | FI-01/02 | COVERED |
| §5 | guarded Project state | §§8,13 | ADR-0009 | FI-08 | COVERED |
| §7 | Event delivery and outbox | Command/Event §§5-15 | ADR-0008,0015 | CT-001, FI-03-07,18-20 | COVERED |
| §13 | Resource accounting | §21; Lease §15 | ADR-0014 | CT-005, FI-16/17 | COVERED |
| §15 | Scheduler / lease | §§10,21; Lease entire spec | ADR-0011 | CT-002/003, FI-09-12 | COVERED |
| §16 | dynamic Agent Runtime | §§5,7,19 | ADR-0012,0013 | CT-006, FI-15 | COVERED |
| §17 | Worker lifecycle | §§10,14; Lease §§3-12 | ADR-0011 | CT-002/003 | COVERED |
| §19 | sole verdict producer | §§11,15 | ADR-0012 | CT-006/007, FI-13/14/15 | COVERED |
| §20 | Artifact/Evidence hash | §16 | ADR-0012 | CT-007, FI-13 | COVERED |
| §23 | independent Human Gate | §12 | ADR-0017 | CT-009/010 | COVERED |
| §25 | checkpoint/replay/reconcile | §18; Lease §16 | ADR-0006 | FI-12 | COVERED |
| §26 | fourteen invariants | §§19-20 | ADR-0006-0016 | CT-001-010 | COVERED |
| §28 | relational authoritative data | §§4,17 | ADR-0005,0006 | FI-01/02/08 | COVERED |
| §29 | semantic Command/Event API | §13; Command/Event entire spec | ADR-0010,0015 | FI-06-08 | COVERED |
| §30 | P0-P3 ordering | §21 | ADR-0004 | phase gates | COVERED |
| §30.2 | ten required tests | Conformance §3 | all relevant | CT-001-010 | COVERED |

## 26. Open questions

- Python、PostgreSQL、FastAPI、SQLAlchemy 和 dependency manager 的版本尚未决定。
- Event payload validator 采用 JSON Schema、Pydantic 或其他方案尚未决定。
- Docker 与 restricted Process Adapter 的实现优先级尚未决定。
- Event Log 与 Outbox 的保留周期、归档介质尚未决定。
- Human Gate identity provider 和 Artifact object store 尚未决定。
