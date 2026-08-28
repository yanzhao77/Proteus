"""E12 server-side adapter for Human Gate presentation and decisions."""
from __future__ import annotations

from typing import Any, Mapping, Optional, Protocol, Sequence, Tuple

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.human_gate_product import HumanGateProductFacade, ProductGateDecisionRequest
from hermes_runtime.domain.human_gate import AuthorizationAssertion, GateDecisionKind, HumanGateRejected
from hermes_runtime.domain.models import Actor, ActorType


class UserHumanGateRejected(ValueError):
    """Stable public rejection for the E12 browser transport."""


class ActorProjectScope(Protocol):
    def project_ids_for(self, actor_scope: Mapping[str, Any]) -> Optional[Sequence[str]]: ...


class HumanGatePresentationReader(Protocol):
    def list_gate_requests(self, project_ids: Sequence[str]) -> Tuple[Mapping[str, Any], ...]: ...
    def get_gate_request(self, gate_request_id: str, project_ids: Sequence[str]) -> Optional[Mapping[str, Any]]: ...
    def get_active_approver_assertion(self, gate_request_id: str, project_ids: Sequence[str], subject: str) -> Optional[AuthorizationAssertion]: ...
    def current_time(self) -> str: ...


class UserHumanGateTransport:
    """Trusted browser transport over the existing Human Gate authority.

    It only presents creator-scoped gate facts and delegates APPROVE/REJECT to
    the established HumanGateProductFacade. It offers no request, cancel,
    supersede, apply, or Project resume operation.
    """

    _DECISIONS = {"APPROVE": GateDecisionKind.APPROVE, "REJECT": GateDecisionKind.REJECT}

    def __init__(self, presentation_reader: HumanGatePresentationReader, actor_project_scope: ActorProjectScope, gate_facade: HumanGateProductFacade) -> None:
        self._presentation_reader = presentation_reader
        self._actor_project_scope = actor_project_scope
        self._gate_facade = gate_facade

    def list(self, *, verified_identity_subject: str, actor: Actor) -> Tuple[Mapping[str, Any], ...]:
        project_ids = self._require_verified_scope(verified_identity_subject, actor)
        return tuple(self._safe_gate_payload(row) for row in self._presentation_reader.list_gate_requests(project_ids))

    def detail(self, *, gate_request_id: str, verified_identity_subject: str, actor: Actor) -> Mapping[str, Any]:
        row = self._gate(verified_identity_subject, actor, gate_request_id)
        return self._safe_gate_payload(row)

    def submit(
        self,
        *,
        gate_request_id: str,
        verified_identity_subject: str,
        actor: Actor,
        command_id: str,
        gate_decision_id: str,
        idempotency_key: str,
        expected_gate_version: int,
        decision: str,
        reason: str,
    ) -> Mapping[str, Any]:
        project_ids = self._require_verified_scope(verified_identity_subject, actor)
        if not all(isinstance(value, str) and value.strip() for value in (command_id, gate_decision_id, idempotency_key)):
            raise UserHumanGateRejected("E12_GATE_DECISION_METADATA_MISSING")
        if not isinstance(expected_gate_version, int) or expected_gate_version < 1:
            raise UserHumanGateRejected("E12_GATE_EXPECTED_VERSION_INVALID")
        if not isinstance(reason, str) or not reason.strip():
            raise UserHumanGateRejected("E12_GATE_DECISION_REASON_REQUIRED")
        decision_kind = self._DECISIONS.get(decision)
        if decision_kind is None:
            raise UserHumanGateRejected("E12_GATE_DECISION_FORBIDDEN")
        gate = self._presentation_reader.get_gate_request(gate_request_id, project_ids)
        if gate is None:
            raise UserHumanGateRejected("E12_GATE_NOT_AVAILABLE")
        assertion = self._presentation_reader.get_active_approver_assertion(gate_request_id, project_ids, verified_identity_subject)
        if assertion is None:
            raise UserHumanGateRejected("E12_GATE_APPROVER_NOT_AUTHORIZED")
        try:
            receipt = self._gate_facade.submit_decision(
                ProductGateDecisionRequest(
                    command_id=command_id.strip(), idempotency_key=idempotency_key.strip(),
                    project_id=str(gate["project_id"]), gate_decision_id=gate_decision_id.strip(),
                    gate_request_id=gate_request_id, decision=decision_kind,
                    requester=Actor(ActorType(str(gate["requester_type"])), str(gate["requester_id"])),
                    approver=Actor(ActorType.USER, verified_identity_subject),
                    authorization_ref="oidc-session:{}:{}".format(assertion.issuer, assertion.assertion_id),
                    assertion=assertion, expected_gate_version=expected_gate_version,
                    current_gate_version=int(gate["version"]), action_scope=str(gate["action_scope"]),
                    reason=reason.strip(), evidence_refs=(), constraints=None,
                    expires_at=str(gate["expires_at"]), now=self._presentation_reader.current_time(),
                    task_id=str(gate.get("task_id") or ""),
                )
            )
        except (HumanGateRejected, CommandRejected) as exc:
            raise UserHumanGateRejected(str(exc)) from exc
        return self._safe_receipt(gate, receipt)

    def _gate(self, subject: str, actor: Actor, gate_request_id: str) -> Mapping[str, Any]:
        project_ids = self._require_verified_scope(subject, actor)
        gate = self._presentation_reader.get_gate_request(gate_request_id, project_ids)
        if gate is None:
            raise UserHumanGateRejected("E12_GATE_NOT_AVAILABLE")
        return gate

    def _require_verified_scope(self, subject: str, actor: Actor) -> Tuple[str, ...]:
        if not subject or actor.actor_type is not ActorType.USER or actor.actor_id != subject:
            raise UserHumanGateRejected("E12_GATE_IDENTITY_REQUIRED")
        scoped = self._actor_project_scope.project_ids_for({"identity_verified": True, "identity_subject": subject, "actor_id": subject})
        if scoped is None:
            raise UserHumanGateRejected("E12_GATE_SCOPE_UNAVAILABLE")
        return tuple(str(project_id) for project_id in scoped)

    @staticmethod
    def _safe_gate_payload(row: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "availability": "CURRENT", "gate_id": str(row["gate_request_id"]), "project_id": str(row["project_id"]),
            "production_name": str(row.get("production_name") or "NOT_AVAILABLE"), "action": str(row["action_scope"]),
            "request_type": str(row["request_type"]), "risk_ref": str(row.get("risk_assessment_id") or "NOT_AVAILABLE"),
            "reason": str(row["reason"]), "evidence_refs": [str(item) for item in row.get("supporting_evidence_refs", ())],
            "evidence_count": int(row.get("evidence_count") or 0), "expires_at": str(row["expires_at"]),
            "status": str(row["request_state"]), "version": int(row["version"]),
            "as_of": str(row.get("updated_at") or ""), "freshness": "NOT_AVAILABLE",
            "audit": tuple({"decision_id": str(item["gate_decision_id"]), "decision": str(item["decision"]), "status": str(item["decision_state"]), "issued_at": str(item["issued_at"]), "expires_at": str(item["expires_at"])} for item in row.get("decisions", ())),
        }

    @staticmethod
    def _safe_receipt(gate: Mapping[str, Any], receipt: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "availability": "CURRENT", "command_id": str(receipt.get("command_id") or ""),
            "gate_request_id": str(receipt.get("gate_request_id") or gate["gate_request_id"]),
            "gate_decision_id": str(receipt.get("gate_decision_id") or ""), "receipt_status": "APPLIED",
            "result_code": str(receipt.get("result_code") or ""), "request_state": str(receipt.get("request_state") or ""),
            "request_version": receipt.get("request_version"), "decision": str(receipt.get("decision") or ""),
            "event_ids": [str(item) for item in receipt.get("event_ids", ())],
            "completion_claim": "GATE_DECISION_RECEIPT_IS_NOT_PROJECT_RESUME",
        }


class UnavailableUserHumanGateTransport:
    def list(self, **_kwargs: Any) -> Tuple[Mapping[str, Any], ...]: raise UserHumanGateRejected("E12_GATE_AUTHORITY_UNAVAILABLE")
    def detail(self, **_kwargs: Any) -> Mapping[str, Any]: raise UserHumanGateRejected("E12_GATE_AUTHORITY_UNAVAILABLE")
    def submit(self, **_kwargs: Any) -> Mapping[str, Any]: raise UserHumanGateRejected("E12_GATE_AUTHORITY_UNAVAILABLE")
