import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

from hermes_runtime.domain.models import Actor, ActorType, ProjectState


HUMAN_GATE_HASH_VERSION = "human-gate-payload-hash/1.0"
RESUME_CONTEXT_SCHEMA_VERSION = "resume-context/1.0"


class HumanGateRejected(ValueError):
    pass


class GateRequestState(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class GateDecisionKind(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class WaitingState(str, Enum):
    WAITING = "WAITING"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class WaitingType(str, Enum):
    HUMAN = "HUMAN"
    RESOURCE = "RESOURCE"
    DEPENDENCY = "DEPENDENCY"
    RECOVERY = "RECOVERY"


@dataclass(frozen=True)
class AuthorizationAssertion:
    assertion_id: str
    issuer: str
    subject: str
    role: str
    project_id: str
    task_id: Optional[str]
    gate_request_id: str
    action_scope: str
    valid_from: str
    valid_until: str
    assertion_hash: str
    revoked: bool = False


@dataclass(frozen=True)
class ResumeContext:
    context_id: str
    project_id: str
    before_state: ProjectState
    project_version: int
    original_command_type: str
    requester: Actor
    gate_request_id: str
    policy_decision_id: str
    risk_assessment_id: str = ""
    budget_fact_id: str = ""
    evidence_refs: Tuple[str, ...] = ()
    supporting_refs: Tuple[str, ...] = ()
    expected_task_versions: Optional[Mapping[str, int]] = None
    expected_graph_version: Optional[int] = None
    schema_version: str = RESUME_CONTEXT_SCHEMA_VERSION

    def canonical_payload(self) -> Mapping[str, Any]:
        return {
            "schema_version": self.schema_version,
            "context_id": self.context_id,
            "project_id": self.project_id,
            "before_state": self.before_state.value,
            "project_version": self.project_version,
            "original_command_type": self.original_command_type,
            "requester": actor_dict(self.requester),
            "gate_request_id": self.gate_request_id,
            "policy_decision_id": self.policy_decision_id,
            "risk_assessment_id": self.risk_assessment_id,
            "budget_fact_id": self.budget_fact_id,
            "evidence_refs": sorted(self.evidence_refs),
            "supporting_refs": sorted(self.supporting_refs),
            "expected_task_versions": dict(sorted((self.expected_task_versions or {}).items())),
            "expected_graph_version": self.expected_graph_version,
        }

    @property
    def context_hash(self) -> str:
        return hash_payload(self.canonical_payload())


def actor_dict(actor: Actor) -> Mapping[str, str]:
    return {"type": actor.actor_type.value, "id": actor.actor_id}


def hash_payload(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload["payload_hash_version"] = HUMAN_GATE_HASH_VERSION
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def validate_requester(actor: Actor) -> None:
    if actor.actor_type not in {
        ActorType.MAIN_HERMES,
        ActorType.CONTROL_PLANE,
        ActorType.RECOVERY_CONTROLLER,
    }:
        raise HumanGateRejected("GATE_REQUESTER_UNAUTHORIZED")


def validate_approver(
    requester: Actor,
    approver: Actor,
    assertion: AuthorizationAssertion,
    project_id: str,
    task_id: Optional[str],
    gate_request_id: str,
    action_scope: str,
) -> None:
    if approver.actor_type not in {ActorType.USER, ActorType.SYSTEM_OPERATOR}:
        raise HumanGateRejected("GATE_APPROVER_UNAUTHORIZED")
    if requester.actor_type == approver.actor_type and requester.actor_id == approver.actor_id:
        raise HumanGateRejected("GATE_SELF_APPROVAL_FORBIDDEN")
    if assertion.revoked:
        raise HumanGateRejected("GATE_APPROVER_UNAUTHORIZED")
    if assertion.subject != approver.actor_id:
        raise HumanGateRejected("GATE_APPROVER_UNAUTHORIZED")
    if assertion.project_id != project_id or assertion.gate_request_id != gate_request_id:
        raise HumanGateRejected("GATE_SCOPE_MISMATCH")
    if assertion.task_id not in {None, task_id}:
        raise HumanGateRejected("GATE_SCOPE_MISMATCH")
    if assertion.action_scope != action_scope:
        raise HumanGateRejected("GATE_SCOPE_MISMATCH")
    if not assertion.assertion_hash.startswith("sha256:"):
        raise HumanGateRejected("GATE_APPROVER_UNAUTHORIZED")


def aggregate_gate_decisions(decision_kinds: Tuple[GateDecisionKind, ...], required_count: int) -> str:
    if required_count < 1:
        raise HumanGateRejected("GATE_RESUME_GUARD_FAILED")
    if any(kind is GateDecisionKind.REJECT for kind in decision_kinds):
        return "REJECTED"
    approvals = sum(1 for kind in decision_kinds if kind is GateDecisionKind.APPROVE)
    if approvals >= required_count:
        return "APPROVED"
    return "INCOMPLETE"
