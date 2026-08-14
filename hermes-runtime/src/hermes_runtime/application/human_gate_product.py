from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Tuple

from hermes_runtime.application.human_gates import SubmitHumanGateDecision
from hermes_runtime.domain.human_gate import (
    AuthorizationAssertion,
    GateDecisionKind,
    HumanGateRejected,
    validate_approver,
)
from hermes_runtime.domain.identity import validate_assertion_window
from hermes_runtime.domain.models import Actor


@dataclass(frozen=True)
class ProductGateDecisionRequest:
    command_id: str
    idempotency_key: str
    project_id: str
    gate_decision_id: str
    gate_request_id: str
    decision: GateDecisionKind
    requester: Actor
    approver: Actor
    authorization_ref: str
    assertion: AuthorizationAssertion
    expected_gate_version: int
    current_gate_version: int
    action_scope: str
    reason: str
    now: str
    task_id: str = ""
    evidence_refs: Tuple[str, ...] = ()
    constraints: Mapping[str, Any] = None
    expires_at: str = ""


class HumanGatePresentationStore(Protocol):
    def get_gate_request(self, gate_request_id: str) -> Mapping[str, Any]:
        ...

    def list_gate_requests(self, project_id: str, actor: Actor) -> Tuple[Mapping[str, Any], ...]:
        ...


class HumanGateDecisionSink(Protocol):
    def submit_decision(self, command: SubmitHumanGateDecision) -> Mapping[str, Any]:
        ...


class EvidenceValidityQuery(Protocol):
    def invalid_evidence_refs(self, project_id: str, evidence_refs: Tuple[str, ...]) -> Tuple[str, ...]:
        ...


class HumanGateProductFacade:
    def __init__(
        self,
        presentation_store: HumanGatePresentationStore,
        decision_sink: HumanGateDecisionSink,
        evidence_query: EvidenceValidityQuery,
    ) -> None:
        self._presentation_store = presentation_store
        self._decision_sink = decision_sink
        self._evidence_query = evidence_query

    def list_requests(self, project_id: str, actor: Actor) -> Tuple[Mapping[str, Any], ...]:
        return tuple(self._safe_gate_payload(row) for row in self._presentation_store.list_gate_requests(project_id, actor))

    def present_request(self, gate_request_id: str) -> Mapping[str, Any]:
        return self._safe_gate_payload(self._presentation_store.get_gate_request(gate_request_id))

    def submit_decision(self, request: ProductGateDecisionRequest) -> Mapping[str, Any]:
        if request.expected_gate_version != request.current_gate_version:
            raise HumanGateRejected("GATE_VERSION_CONFLICT")
        validate_assertion_window(request.assertion, request.now)
        validate_approver(
            request.requester,
            request.approver,
            request.assertion,
            request.project_id,
            request.task_id or None,
            request.gate_request_id,
            request.action_scope,
        )
        invalid_refs = self._evidence_query.invalid_evidence_refs(request.project_id, request.evidence_refs)
        if invalid_refs:
            raise HumanGateRejected("GATE_EVIDENCE_INVALID")

        command = SubmitHumanGateDecision(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            project_id=request.project_id,
            gate_decision_id=request.gate_decision_id,
            gate_request_id=request.gate_request_id,
            decision=request.decision.value,
            approver=request.approver,
            authorization_ref=request.authorization_ref,
            assertion_id=request.assertion.assertion_id,
            assertion_hash=request.assertion.assertion_hash,
            reason=request.reason,
            evidence_refs=request.evidence_refs,
            constraints=request.constraints,
            expires_at=request.expires_at,
            actor_type=request.approver.actor_type.value,
            actor_id=request.approver.actor_id,
        )
        return self._decision_sink.submit_decision(command)

    def apply_resume(self, *_args: Any, **_kwargs: Any) -> Mapping[str, Any]:
        raise HumanGateRejected("GATE_PRODUCT_FACADE_CANNOT_RESUME_PROJECT")

    def _safe_gate_payload(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if any(key in payload for key in ("secret", "secret_value", "token", "password")):
            raise HumanGateRejected("GATE_PRESENTATION_UNSAFE_PAYLOAD")
        return payload
