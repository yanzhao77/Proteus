# Proteus Production Entry Architecture V1.0

**状态：** 实现前架构基线
**审计基线：** `codex/p6-autonomous-production-trial` / `bd55a9f`
**范围：** Factory Home、Production Entry、Entry Draft、Master Plan Review、Approval Bridge、Portfolio Projection 与 Factory Workspace Web 边界。
**不在范围：** 重构 P0–P6、替换 P6 Trial、创建第二 Scheduler/Task Graph/Execution/Event/Verification authority，或在浏览器直接写权威状态。

> **Architecture rule:** `Production` 是用户面对的产品概念；`Project` 是现有的后端权威聚合。Entry 在 Plan Approval 前只处理意图与版本。Approval Bridge 是唯一进入现有 Project Authority 的通道；P6 是其后唯一的自治运行时。

## 1. Architecture Overview

Proteus 已有经 P6 验证的 Autonomous Software Factory Control Plane，却没有将用户 Idea 变为受控生产输入的产品入口。本架构新增的是一个**pre-approval Entry layer**，不是新的 agent、聊天层或任务管理器。用户提交 Idea，获得结构化 Understanding、少量高价值 Clarification、显式 Assumption、Proposal 和可审阅 Master Plan。只有用户批准有效的 Master Plan 后，系统才调用既有 `CreateProject`、`ApplyWorkGraphPatch` 和 `CreateVerificationPlan` 等语义命令，并把后续运行交回现有 P6 authority chain。[1] [2]

```text
Factory Home / Web
  → EntryDraft authority (Idea, revisions, proposal, plan)
  → ApproveEntryPlan
  → Approval Bridge
  → existing Project / Graph / Verification authority
  → existing P6 runtime
  → existing Project/Gate/Evidence projections
  → Live Production Workspace
```

## 2. Authority Boundary

| Layer | Owns | May read | Must not own |
| --- | --- | --- | --- |
| Factory Home | navigation, query composition, local view state. | Portfolio, Gate, Draft, Factory health snapshots. | Project/Task/Execution lifecycle. |
| EntryDraft | pre-approval intent, revisions, plan revision, bridge status. | user-supplied data and generated provenance. | Scheduler, Worker, Artifact, Evidence, P6 state. |
| Approval Bridge | validation and recoverable delegation to existing commands. | Draft/Plan, existing command receipts/source facts. | raw SQL writes to Project/Task/Execution tables. |
| Project Authority | Project lifecycle and state guards. | command/guard facts. | Entry UX decision flow. |
| Control Plane / P6 | Graph, runtime planning, policy/risk, capability, execution, verification, recovery, delivery. | Project and prior authority facts. | Entry Draft lifecycle. |
| Live Production | read/control view over one Project. | Project/Gate/verification/evidence projections. | an alternate runtime authority. |

The UI only emits semantic intent. All mutations require actor, reason, idempotency key, expected version, authorization and a command envelope. Existing `ProductApiFacade` explicitly rejects unsupported routes and authority-shaped payloads; Entry extends that boundary rather than bypassing it.[3]

## 3. Entry State Machine

```text
IDLE
  → IDEA_INPUT
  → UNDERSTANDING
  → CLARIFICATION_REQUIRED ── answer/revise ──┐
  → PROPOSAL_READY ◄──────────────────────────┘
  → PLAN_GENERATING
  → PLAN_REVIEW
  → AWAITING_APPROVAL
  → APPROVAL_PROCESSING
  → APPROVED
  → PRODUCTION_CREATED / MATERIALIZED

Any pre-approval state → ARCHIVED
Any generation/validation failure → prior stable state + recoverable failure record
```

These are Entry flow states only. They do not map one-to-one to `ProjectState`, `TaskState` or execution state. `PRODUCTION_CREATED` is rendered only when the Bridge sees existing Project/Graph/Verification source receipts and records materialization; a `202` command acknowledgement is never enough.

## 4. Draft Model

`EntryDraft` is the smallest new aggregate that supplies missing approved-before-production persistence. It has `entry_draft_id` (shown as `draft_id` in product UI), owner/requester, entry state, optimistic `version`, current revision pointers, optional approved plan hash, nullable Project binding, timestamps and archival information.

A Draft is not a Project placeholder. It must not create a `projects` row, Task graph, ExecutionRequest, Worker, Artifact, Evidence, Gate or Scheduler lease. It can be resumed after browser restart because its submitted revisions are server persistence; local storage may retain only unsent non-secret text and is never state authority.

## 5. Revision Model

Every submitted Idea edit, generated Understanding, answer set, assumption decision, Proposal and Master Plan is an immutable `EntryDraftRevision`. Each revision records `draft_id`, ordinal/version, kind, canonical payload/hash, actor or generated-by source, reason, timestamps and provenance references. The Draft header points at current accepted revisions.

User action never overwrites old content. A stale `expected_draft_version` yields conflict, current revision summary and a deliberate reload/reapply path. Revision kinds are typed and validated; a generic JSON patch endpoint is forbidden.

## 6. Understanding Model

Understanding converts Idea into reviewable product facts, not a model chain-of-thought. It includes Core Objective, Target User, Expected Outcome, Requirements, Scope, Unknowns, Risks and Assumptions. Each field has source classification: `USER_INPUT`, `INFERRED` or `NEEDS_CONFIRMATION`.

Understanding is a Draft-derived revision with generation provenance and user confirmation. It is not P6 `Situation`: `situations` in existing runtime represent event/failure analysis and feed Diagnosis/Planner, while Understanding represents pre-approval product intent. **DO NOT reuse `situations` for Entry Understanding.**

## 7. Clarification Model

Clarification is a bounded product-intent question set. A round presents one to three questions selected because their answer affects scope, architecture, constraints, risk or verification. It records question ID, source revision, answer revision, rationale, impact class, required/optional status and resolution state.

Clarification is not a Human Gate. Existing `human_gate_requests`/`ResumeContext` govern authorization and runtime pause/resume. Draft clarification must not set `WAITING_FOR_HUMAN`, mutate Project state or invoke Gate authority.

## 8. Assumption Model

Assumptions allow low-risk, reversible, explainable defaults. Each assumption contains value, domain, source, rationale, risk, reversibility, status and revision reference. User actions are `accept`, `change`, `ask why` or `defer`; each produces a new Draft revision and decision reference.

Examples like Python, PostgreSQL, Docker and automated testing are Product/Plan assumptions, not initial entry form fields and not Worker/Model selection. Assumptions become immutable plan input snapshots at approval; they do not directly create capability, policy, scheduler or execution facts.

## 9. Proposal Model

Proposal answers “is this what you want to produce?” before Master Plan. It compiles Product Statement, Target Outcome, Scope In/Out, Requirements, Assumptions, Candidate Architecture, Phases, Workforce Profile, Verification Strategy, Delivery Strategy, Complexity and Risks from Draft revisions.

Proposal is a Draft revision/projection. It is not `candidate_actions`, `decision_records`, Policy/Risk facts or an ExecutionRequest. The user may modify Idea, revise assumptions, ask for revision, reject or generate Master Plan. No Proposal action may start a Worker, modify Project state or materialize Task Graph.

## 10. Master Plan Bridge

A Master Plan is a versioned Entry plan revision containing Goal, Requirements, Constraints, Architecture, Phases, Nodes, Dependencies, Risks, Verification, Delivery and Workforce. It aligns to Live Production UX shape but is not the current P6 `planning_runs`/`candidate_actions` authority. P6 runtime planning occurs after a Project/Task readiness situation and selects executable actions; Entry Master Plan is user-approved product planning.

The Entry plan compiler validates that the approved plan can be lowered into existing `GraphPatch` and `VerificationPlan` types. Plan edits/add/remove requirements, split/merge node and dependency changes create a new plan revision/hash and invalidate outstanding approval UI. No plan revision can enter production until approval validation succeeds.

## 11. Production Creation Bridge

`ApproveEntryPlan` is the sole boundary command. It requires actor, reason, idempotency key, expected Draft/Plan version, approved content hash, assumption refs, proposal refs and correlation context. If any reviewed revision/hash differs, approval rejects; old plans cannot be approved.

| Step | Authority | Action | Required result |
| --- | --- | --- | --- |
| 1 | EntryDraft | Record approval receipt as `PROCESSING`. | No Project exists. |
| 2 | Entry compiler | Validate plan and compile GraphPatch/VerificationPlan. | Deterministic compiled reference. |
| 3 | Existing Project | `ControlPlane.create_project(CreateProject)`. | Existing `projects` row + receipt/event/outbox. |
| 4 | Existing Graph | `ControlPlane.apply_work_graph_patch(ApplyWorkGraphPatch)`. | Existing tasks/DAG/readiness event. |
| 5 | Existing Verification | `ControlPlane.create_verification_plan(CreateVerificationPlan)`. | Existing verification authority record. |
| 6 | EntryDraft | Reconcile child receipts/source facts; set materialized Project binding. | `PRODUCTION_CREATED` can render. |
| 7 | Existing P6 | Consume actual readiness and run its normal chain. | Entry no longer controls runtime. |

The Bridge is a recoverable saga, not direct database SQL or an atomic replacement for existing authority transactions. `hermes_create_project_authority` is a security-definer function that requires a control-plane actor and a processing receipt; it must only be reached through existing application ports/handlers.[4]

## 12. Portfolio Projection

Production Portfolio is a source-derived read model. There is no `productions` authority table. `Production` resolves to Project plus Draft-to-Project binding and related current facts.

| Card field | Source | Rule |
| --- | --- | --- |
| production/project ID, display name, owner | Project + bridge mapping. | Project remains authority. |
| status/current phase | Project state/projection. | UI never derives final status locally. |
| current node/action | Task graph/readiness and safe current projection. | Must be explicitly sourced. |
| progress/progress source | Authority-derived aggregation if available; otherwise null. | No arbitrary percent. |
| blocker/gate count | Gate/recovery/task facts. | Count from server query. |
| plan revision | approved Entry plan revision/hash bridge mapping. | Not P6 planning run ID. |
| last update/health/staleness | source timestamp, read model freshness, actual runtime health. | Browser shows `STALE` on disconnect/gap. |

The first implementation can be a bounded query adapter. A materialized projection table is deferred until measured volume/performance needs demand a rebuildable projection.

## 13. Event Flow

```text
Entry semantic command
  → EntryDraft authority transaction
  → existing event_log + outbox_messages (only for meaningful lifecycle fact)
  → Entry/Portfolio projection
  → Web snapshot/event hydration

ApproveEntryPlan
  → Entry bridge receipt
  → existing Project/Graph/Verification command receipts + event/outbox
  → Project/Gate/Evidence projections
  → Live Production read surface
```

Allowed Entry events include draft begun/revised, understanding confirmed, plan generated, approval requested, bridge materialized/failed. Typing, focus, filters and unsubmitted input are not domain events. Existing Project/Task/Execution/Verification/Gate events remain their authorities’ exclusive facts. No Entry Event Store, private outbox, scheduler event loop or browser event truth is allowed.

## 14. API Contract

Existing Product API routes stay intact. New Entry routes should be allowlisted semantic commands, not generic CRUD/state mutations.

| Capability | Proposed minimal route | Classification |
| --- | --- | --- |
| Begin Draft | `POST /production-drafts` | New semantic command. |
| Read Draft | `GET /production-drafts/{id}` | New query. |
| Amend Idea | `POST /production-drafts/{id}/idea-revisions` | New semantic command. |
| Generate/confirm Understanding | `POST /production-drafts/{id}/understanding` | New semantic command. |
| Answer clarification | `POST /production-drafts/{id}/clarifications/{qid}/answer` | New semantic command. |
| Accept/change assumption | `POST /production-drafts/{id}/assumptions/{aid}/accept|change` | New semantic command. |
| Generate Proposal/Plan | `POST /production-drafts/{id}/proposal|plan` | New semantic command. |
| Approve plan | `POST /plans/{id}/approve` | New Approval Bridge command. |
| Portfolio | `GET /productions`, `GET /productions/{id}` | New source-derived query. |
| Project/Gate | Existing Project status and Gate APIs; later user-scoped list adapters. | Adapt existing facade. |

All mutating calls require actor, reason, idempotency, expected version and authorization. Responses distinguish `accepted receipt`, `processing`, `rejected`, `materialized` and `authority snapshot`. `202 Accepted` never means “Production Created.”

## 15. Web / TUI / API Boundary

| Surface | Responsibility | Forbidden |
| --- | --- | --- |
| Web Factory Workspace | Idea/Draft/plan review, Portfolio, Gate visibility, navigation, snapshot display. | direct authority write, Worker selection/start, local truth. |
| TUI / CLI | Operator diagnostics, relay/supervisor inspection, guarded semantic controls. | primary user Entry workflow or raw state changes. |
| API | automation, query, semantic command, subscribe. | generic state PATCH, raw SQL, unsafe event injection. |

Current repository has no general TUI and only minimal Gate HTML; this boundary is a target architecture, not an assertion that all surfaces already exist.

## 16. Error / Recovery

| Condition | Required behavior |
| --- | --- |
| Stale Draft/Plan version | Reject command; present current revision and explicit reload/reapply. |
| Permission denied | Safe rejection; preserve user input where allowed; no information leakage. |
| Generation failure | Keep prior stable revision; retryable generation record; never overwrite user input. |
| Network timeout | Query the same idempotency receipt; do not blind resubmit. |
| Event disconnect/gap | Mark snapshot stale; stop delta application; re-fetch full snapshot. |
| Plan approval conflict | Reject old hash/version; require re-review. |
| Production materialization failure | Show bridge processing/failed state; reconcile child receipts/source facts; never fake created state. |
| Worker/runtime unavailable | Surface actual health/blocker from read model; Entry cannot self-heal P6. |
| Browser reconnect | Rehydrate server Draft/Project/Gate snapshot; never restore authority from local storage. |

## 17. Security

Entry data is user intent and may contain sensitive information. Enforce authenticated actor ownership/role scope, approval authorization, server-derived actor identity, safe response filtering, secret scanning/redaction, attachment reference allowlists and correlation/audit from Draft command to Bridge child commands. Do not accept secret values in revisions/events/telemetry. Existing command envelopes and safe response enforcement in Product API are the mandatory baseline.[3]

## 18. Versioning

Draft and Plan revisions are immutable and hash-addressed. Draft commands have expected Draft version; plan-related commands include expected plan revision and content hash. The Bridge records all derived Project/Graph/Verification command IDs and source versions. Portfolio snapshot has `as_of`, source/projection version and freshness. A browser cannot use its last seen event sequence to declare success after a gap.

## 19. Idempotency

Every semantic mutation accepts one idempotency key. Approval creates deterministic child keys/correlation IDs, so retried approval discovers the same Bridge receipt and at most one Project. Existing Project/Graph/Verification commands retain their own command receipt behavior. Idempotency is not UI double-click prevention only; it is persisted authority behavior.

## 20. Permission Model

| Actor capability | Allowed | Not allowed |
| --- | --- | --- |
| Draft owner | begin/amend/answer/revise/submit plan. | approve beyond own authorization policy, mutate Project runtime. |
| Plan approver | approve a valid reviewed plan with reason/authorization. | direct Worker/Scheduler control. |
| Viewer | read scoped Draft/Portfolio/Live status. | amend, approve, Gate decision without role. |
| Gate approver | existing Human Gate decision only. | pre-approval Clarification mutation by gate shortcut. |
| Control Plane bridge service | submit existing child semantic commands. | raw table write/new runtime state machine. |
| Operator | diagnostics/TUI guarded actions under existing policy. | bypass Entry/Project authority. |

## 21. Test Strategy

- **Unit:** Entry transitions, immutable revisions, assumption changes, proposal revision, plan compiler/hash, stale plan rejection.
- **PostgreSQL:** Draft version/idempotency, revision audit, bridge record, event/outbox atomicity, secret rejection.
- **Integration:** Idea → Draft → Understanding → Proposal → Plan; plan approval → Project/Graph/Verification creation; duplicate approval; permission rejection.
- **Authority:** Static/contract tests verify Entry UI/API has no raw SQL, direct Project/Task/Worker/Execution state mutation or direct event insertion.
- **Read/UI:** Snapshot-first, loading/error/empty/stale states, reconnect, accessibility and mock adapter labels.
- **Regression:** Existing P0–P6 suites, migration continuity, compileall, secret scan, Docker/CI remain green.

## 22. Migration Strategy

Future migration `0025_production_entry_drafts.sql` should add only `entry_drafts`, `entry_draft_revisions` and `entry_approval_bridges` plus indexes, role grants, version/foreign-key constraints and existing event/outbox integration. It must not add `productions`, `entry_tasks`, `entry_scheduler`, `entry_workers`, `entry_execution_requests`, `entry_event_log`, `entry_outbox` or alternative verification tables.

## 23. P6 Compatibility

P6 protected areas include `hermes-runtime/src/hermes_runtime/trial/**`, `tests/test_p6_autonomous_trial.py`, `migrations/0023_project_guard_fact_producers.sql`, `migrations/0024_p6_autonomous_trial_runtime.sql`, `docs/P6_REPORT.md`, P6 evidence, and existing Execution/Scheduler/Worker/Human Gate/Recovery/Verification authority modules. Entry only accesses official application ports and source-derived reads. It never imports the Trial driver as product code, changes acceptance semantics or manipulates P6 evidence.

## 24. P7+ Roadmap

P7+ may add collaboration/RBAC expansion, richer plan mutation diff/impact analysis, durable materialized Portfolio projections, bounded event subscription, advanced Workspace visualization, cross-Production insights and specialized operator TUI. These are gated on Entry E2E trial acceptance, concrete read-model performance evidence and continued proof that no second authority emerges.

## References

[1]: [`docs/P6_REPORT.md`](P6_REPORT.md)
[2]: [`docs/ENTRY_RECON.md`](ENTRY_RECON.md)
[3]: [`hermes-runtime/src/hermes_runtime/application/product_api.py`](../hermes-runtime/src/hermes_runtime/application/product_api.py), [`api_main.py`](../hermes-runtime/src/hermes_runtime/api_main.py)
[4]: [`hermes-runtime/migrations/0003_project_state_authority.sql`](../hermes-runtime/migrations/0003_project_state_authority.sql) and [`trial/driver.py`](../hermes-runtime/src/hermes_runtime/trial/driver.py)
