from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Tuple


class ActorType(str, Enum):
    USER = "user"
    MAIN_HERMES = "main_hermes"
    WORKER = "worker"
    VERIFIER = "verifier"
    SCHEDULER = "scheduler"
    CONTROL_PLANE = "control_plane"
    RECOVERY_CONTROLLER = "recovery_controller"
    SYSTEM_OPERATOR = "system_operator"


class TaskState(str, Enum):
    NEW = "NEW"
    READY = "READY"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    COMPLETION_CLAIMED = "COMPLETION_CLAIMED"
    WAITING = "WAITING"
    VERIFYING = "VERIFYING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


class AgentRunKind(str, Enum):
    WORKER = "WORKER"
    VERIFIER = "VERIFIER"


class AgentRunStatus(str, Enum):
    ADMITTED = "ADMITTED"
    COMPLETED = "COMPLETED"
    INVALIDATED = "INVALIDATED"


class ProjectState(str, Enum):
    CREATED = "CREATED"
    INTAKE = "INTAKE"
    DISCOVERY = "DISCOVERY"
    PLANNING = "PLANNING"
    DESIGNING = "DESIGNING"
    IMPLEMENTING = "IMPLEMENTING"
    VERIFYING = "VERIFYING"
    HARDENING = "HARDENING"
    PACKAGING = "PACKAGING"
    DELIVERING = "DELIVERING"
    ACCEPTED = "ACCEPTED"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    WAITING_FOR_RESOURCE = "WAITING_FOR_RESOURCE"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    RECOVERING = "RECOVERING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Actor:
    actor_type: ActorType
    actor_id: str


@dataclass(frozen=True)
class Task:
    task_id: str
    state: TaskState
    version: int
    current_artifact_id: Optional[str]
    current_artifact_hash: Optional[str]
    completion_worker_identity: Optional[str]
    project_id: Optional[str] = None
    current_verification_plan_id: Optional[str] = None
    current_verification_plan_version: Optional[int] = None
    completion_worker_run_id: Optional[str] = None
    completion_worker_context_identity: Optional[str] = None


@dataclass(frozen=True)
class Project:
    project_id: str
    state: ProjectState
    version: int
    resume_state: Optional[ProjectState]


@dataclass(frozen=True)
class ArtifactCandidate:
    artifact_id: str
    task_id: str
    content_hash: str
    media_type: str
    produced_by: str


@dataclass(frozen=True)
class CompletionClaim:
    claim_id: str
    task_id: str
    run_id: str
    worker_identity: Actor
    artifact: ArtifactCandidate
    summary: str


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    artifact_id: str
    artifact_hash: str
    producer_identity: str
    valid: bool


@dataclass(frozen=True)
class AgentRun:
    run_id: str
    project_id: str
    task_id: str
    run_kind: AgentRunKind
    agent_identity: str
    context_identity: str
    status: AgentRunStatus
    created_by: Actor
    version: int = 1


@dataclass(frozen=True)
class VerificationPlanCheck:
    check_id: str
    check_type: str
    runner_profile: str
    required: bool
    timeout_seconds: int
    pass_condition: str
    evidence_level: str
    ordinal: int


@dataclass(frozen=True)
class VerificationPlan:
    verification_plan_id: str
    task_id: str
    project_id: str
    version: int
    status: str
    artifact_selectors: Tuple[str, ...]
    aggregation_rule: str
    independence: str
    created_by: Actor
    checks: Tuple[VerificationPlanCheck, ...]


@dataclass(frozen=True)
class VerificationCheckResult:
    check_id: str
    status: Verdict
    finding_codes: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]
    started_at: str
    completed_at: str


@dataclass(frozen=True)
class VerificationResult:
    verification_id: str
    plan_id: str
    plan_version: int
    task_id: str
    project_id: str
    artifact_id: str
    artifact_hash: str
    verifier_identity: Actor
    verifier_run_id: str
    verdict: Verdict
    check_results: Tuple[VerificationCheckResult, ...]
    evidence: Tuple[Evidence, ...]
    started_at: str
    completed_at: str
    correlation_id: str


@dataclass(frozen=True)
class CommandEnvelope:
    command_id: str
    command_type: str
    idempotency_key: str
    expected_version: int
    actor: Actor
    reason: str
    project_id: str


@dataclass(frozen=True)
class TransitionDecision:
    target_state: TaskState
    reason: str


@dataclass(frozen=True)
class CommandReceipt:
    command_id: str
    status: str
    result_code: str
    target_version: Optional[int]
    event_ids: Tuple[str, ...]
    response: Mapping[str, Any]


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    event_type: str
    schema_version: str
    occurred_at: str
    recorded_at: str
    producer: Mapping[str, str]
    project_id: str
    partition_key: str
    sequence: int
    idempotency_key: str
    payload: Mapping[str, Any]
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    run_id: Optional[str] = None
    classification: str = "INTERNAL"


@dataclass(frozen=True)
class PublishResult:
    transport_reference: str


@dataclass(frozen=True)
class OutboxClaim:
    message_id: str
    event_id: str
    topic: str
    partition_key: str
    sequence: int
    claim_token: str
    attempt_count: int
    envelope: EventEnvelope


@dataclass(frozen=True)
class RedriveOutbox:
    envelope: CommandEnvelope
    message_id: str
    authorization_ref: str
    cause_resolved: bool
