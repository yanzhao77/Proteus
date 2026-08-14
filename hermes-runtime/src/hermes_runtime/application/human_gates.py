from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, Tuple

from hermes_runtime.domain.models import Actor


@dataclass(frozen=True)
class RequestHumanGate:
    command_id: str
    idempotency_key: str
    project_id: str
    gate_request_id: str
    action_scope: str
    requester: Actor
    expected_project_version: int
    resume_context: Mapping[str, Any]
    reason: str
    task_id: str = ""
    request_type: str = "approval"
    policy_decision_id: str = ""
    risk_assessment_id: str = ""
    supporting_evidence_refs: Tuple[str, ...] = ()
    requested_constraints: Mapping[str, Any] = None
    approval_policy: str = "ALL_REQUIRED"
    required_approver_count: int = 1
    authorization_requirements: Mapping[str, Any] = None
    expires_at: str = ""
    expected_graph_version: Optional[int] = None
    attempt_ledger: Tuple[Mapping[str, Any], ...] = ()
    remaining_options: Tuple[Mapping[str, Any], ...] = ()
    recommended_option: str = ""
    actor_type: str = "main_hermes"
    actor_id: str = "main-hermes"


@dataclass(frozen=True)
class EnterProjectWaitingForGate:
    command_id: str
    idempotency_key: str
    project_id: str
    waiting_record_id: str
    gate_request_id: str
    resume_context_id: str
    expected_project_version: int
    blocking_reason: str
    actor_type: str = "control_plane"
    actor_id: str = "project-control-plane"
    reason: str = "enter project waiting for human gate"


@dataclass(frozen=True)
class SubmitHumanGateDecision:
    command_id: str
    idempotency_key: str
    project_id: str
    gate_decision_id: str
    gate_request_id: str
    decision: str
    approver: Actor
    authorization_ref: str
    assertion_id: str
    assertion_hash: str
    reason: str
    evidence_refs: Tuple[str, ...] = ()
    constraints: Mapping[str, Any] = None
    expires_at: str = ""
    actor_type: str = "user"
    actor_id: str = "user"


@dataclass(frozen=True)
class ApplyHumanGateDecision:
    command_id: str
    idempotency_key: str
    project_id: str
    gate_request_id: str
    gate_decision_id: str
    waiting_record_id: str
    expected_project_version: int
    expected_waiting_version: int
    expected_gate_version: int
    expected_decision_version: int
    resume_context_hash: str
    target_state: str = ""
    actor_type: str = "control_plane"
    actor_id: str = "project-control-plane"
    reason: str = "apply human gate decision and resume project"


@dataclass(frozen=True)
class ExpireHumanGateRequest:
    command_id: str
    idempotency_key: str
    project_id: str
    gate_request_id: str
    actor_type: str = "control_plane"
    actor_id: str = "gate-expiry-worker"
    reason: str = "expire human gate request"


@dataclass(frozen=True)
class CancelHumanGateRequest:
    command_id: str
    idempotency_key: str
    project_id: str
    gate_request_id: str
    authorization_ref: str
    actor_type: str = "system_operator"
    actor_id: str = "operator"
    reason: str = "cancel human gate request"


@dataclass(frozen=True)
class SupersedeHumanGateRequest:
    command_id: str
    idempotency_key: str
    project_id: str
    old_gate_request_id: str
    new_gate_request_id: str
    actor_type: str = "control_plane"
    actor_id: str = "project-control-plane"
    reason: str = "supersede human gate request"


class HumanGateStore(Protocol):
    def request_gate(self, command: RequestHumanGate) -> Mapping[str, Any]:
        ...

    def enter_project_waiting(self, command: EnterProjectWaitingForGate) -> Mapping[str, Any]:
        ...

    def submit_decision(self, command: SubmitHumanGateDecision) -> Mapping[str, Any]:
        ...

    def apply_decision(self, command: ApplyHumanGateDecision) -> Mapping[str, Any]:
        ...

    def expire_request(self, command: ExpireHumanGateRequest) -> Mapping[str, Any]:
        ...

    def cancel_request(self, command: CancelHumanGateRequest) -> Mapping[str, Any]:
        ...

    def supersede_request(self, command: SupersedeHumanGateRequest) -> Mapping[str, Any]:
        ...


class HumanGateAuthority:
    def __init__(self, store: HumanGateStore) -> None:
        self._store = store

    def request_gate(self, command: RequestHumanGate) -> Mapping[str, Any]:
        return self._store.request_gate(command)

    def enter_project_waiting(self, command: EnterProjectWaitingForGate) -> Mapping[str, Any]:
        return self._store.enter_project_waiting(command)

    def submit_decision(self, command: SubmitHumanGateDecision) -> Mapping[str, Any]:
        return self._store.submit_decision(command)

    def apply_decision(self, command: ApplyHumanGateDecision) -> Mapping[str, Any]:
        return self._store.apply_decision(command)

    def expire_request(self, command: ExpireHumanGateRequest) -> Mapping[str, Any]:
        return self._store.expire_request(command)

    def cancel_request(self, command: CancelHumanGateRequest) -> Mapping[str, Any]:
        return self._store.cancel_request(command)

    def supersede_request(self, command: SupersedeHumanGateRequest) -> Mapping[str, Any]:
        return self._store.supersede_request(command)
