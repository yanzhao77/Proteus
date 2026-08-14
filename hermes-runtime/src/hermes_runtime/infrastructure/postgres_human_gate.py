from enum import Enum
from typing import Any, Mapping, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.human_gates import (
    ApplyHumanGateDecision,
    CancelHumanGateRequest,
    EnterProjectWaitingForGate,
    ExpireHumanGateRequest,
    RequestHumanGate,
    SubmitHumanGateDecision,
    SupersedeHumanGateRequest,
)
from hermes_runtime.domain.human_gate import hash_payload
from hermes_runtime.infrastructure.postgres_recovery import PostgresRecoveryStore


class HumanGateFaultPoint(str, Enum):
    AFTER_REQUEST_BEFORE_EVENT = "after_request_before_event"
    AFTER_DECISION_BEFORE_EVENT = "after_decision_before_event"
    AFTER_WAITING_BEFORE_CONTEXT = "after_waiting_before_context"
    AFTER_CONTEXT_BEFORE_EVENT = "after_context_before_event"
    AFTER_APPLICATION_BEFORE_PROJECT = "after_application_before_project"
    AFTER_PROJECT_BEFORE_EVENT = "after_project_before_event"
    AFTER_EVENT_BEFORE_OUTBOX = "after_event_before_outbox"
    AFTER_OUTBOX_BEFORE_RECEIPT = "after_outbox_before_receipt"
    AFTER_EXPIRY_BEFORE_EVENT = "after_expiry_before_event"
    AFTER_SUPERSEDE_BEFORE_EVENT = "after_supersede_before_event"


class PostgresHumanGateStore(PostgresRecoveryStore):
    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self._human_gate_fault: Optional[HumanGateFaultPoint] = None

    def fail_human_gate_once(self, point: str) -> None:
        self._human_gate_fault = HumanGateFaultPoint(point)

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """TRUNCATE human_gate_decision_applications,
                   project_waiting_records, project_resume_contexts,
                   human_gate_decisions, human_gate_requests,
                   human_gate_authorization_assertions
                   RESTART IDENTITY CASCADE"""
            )
        super().reset_for_test()

    def seed_human_authorization(
        self,
        assertion_id: str,
        subject: str,
        project_id: str,
        gate_request_id: str,
        action_scope: str,
        role: str = "approver",
        task_id: str = "",
        issuer: str = "test-only",
        assertion_hash: str = "sha256:test-assertion",
        valid_seconds: int = 3600,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO public.human_gate_authorization_assertions(
                    assertion_id, issuer, subject, role, project_id, task_id,
                    gate_request_id, action_scope, valid_from, valid_until,
                    assertion_hash, verification_ref, admitted_by
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,clock_timestamp() - interval '1 second',
                          clock_timestamp() + (%s::text || ' seconds')::interval,
                          %s,%s,'test_identity_verifier')
                """,
                (
                    assertion_id,
                    issuer,
                    subject,
                    role,
                    project_id,
                    task_id or None,
                    gate_request_id,
                    action_scope,
                    int(valid_seconds),
                    assertion_hash,
                    "test-verification:" + assertion_id,
                ),
            )

    def request_gate(self, command: RequestHumanGate) -> Mapping[str, Any]:
        payload = {
            "command": "human_gate.request",
            "project_id": command.project_id,
            "gate_request_id": command.gate_request_id,
            "task_id": command.task_id,
            "action_scope": command.action_scope,
            "request_type": command.request_type,
            "requester": {
                "type": command.requester.actor_type.value,
                "id": command.requester.actor_id,
            },
            "expected_project_version": command.expected_project_version,
            "resume_context": dict(command.resume_context),
            "policy_decision_id": command.policy_decision_id,
            "risk_assessment_id": command.risk_assessment_id,
            "supporting_evidence_refs": list(command.supporting_evidence_refs),
            "requested_constraints": dict(command.requested_constraints or {}),
            "approval_policy": command.approval_policy,
            "required_approver_count": int(command.required_approver_count),
            "authorization_requirements": dict(command.authorization_requirements or {}),
            "expires_at": command.expires_at,
            "expected_graph_version": command.expected_graph_version,
            "attempt_ledger": list(command.attempt_ledger),
            "remaining_options": list(command.remaining_options),
            "recommended_option": command.recommended_option,
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
            "reason": command.reason,
        }
        return self._call_human_gate(
            """SELECT public.hermes_request_human_gate(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id,
                command.gate_request_id,
                command.task_id or None,
                command.action_scope,
                command.request_type,
                command.requester.actor_type.value,
                command.requester.actor_id,
                int(command.expected_project_version),
                Jsonb(dict(command.resume_context)),
                command.policy_decision_id or None,
                command.risk_assessment_id or None,
                Jsonb(list(command.supporting_evidence_refs)),
                Jsonb(dict(command.requested_constraints or {})),
                command.approval_policy,
                int(command.required_approver_count),
                Jsonb(dict(command.authorization_requirements or {})),
                command.expires_at or None,
                command.expected_graph_version,
                Jsonb(list(command.attempt_ledger)),
                Jsonb(list(command.remaining_options)),
                command.recommended_option or None,
                command.command_id,
                command.idempotency_key,
                hash_payload(payload),
                command.actor_type,
                command.actor_id,
                command.reason,
                self._take_human_gate_fault(),
            ),
        )

    def enter_project_waiting(self, command: EnterProjectWaitingForGate) -> Mapping[str, Any]:
        payload = {
            "command": "project.enter_waiting",
            "project_id": command.project_id,
            "waiting_record_id": command.waiting_record_id,
            "gate_request_id": command.gate_request_id,
            "resume_context_id": command.resume_context_id,
            "expected_project_version": command.expected_project_version,
            "blocking_reason": command.blocking_reason,
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
            "reason": command.reason,
        }
        return self._call_human_gate(
            """SELECT public.hermes_enter_project_waiting_for_gate(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id,
                command.waiting_record_id,
                command.gate_request_id,
                command.resume_context_id,
                int(command.expected_project_version),
                command.blocking_reason,
                command.command_id,
                command.idempotency_key,
                hash_payload(payload),
                command.actor_type,
                command.actor_id,
                command.reason,
                self._take_human_gate_fault(),
            ),
        )

    def submit_decision(self, command: SubmitHumanGateDecision) -> Mapping[str, Any]:
        payload = {
            "command": "human_gate.decide",
            "project_id": command.project_id,
            "gate_decision_id": command.gate_decision_id,
            "gate_request_id": command.gate_request_id,
            "decision": command.decision,
            "approver": {
                "type": command.approver.actor_type.value,
                "id": command.approver.actor_id,
            },
            "authorization_ref": command.authorization_ref,
            "assertion_id": command.assertion_id,
            "assertion_hash": command.assertion_hash,
            "evidence_refs": list(command.evidence_refs),
            "constraints": dict(command.constraints or {}),
            "expires_at": command.expires_at,
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
            "reason": command.reason,
        }
        return self._call_human_gate(
            """SELECT public.hermes_submit_human_gate_decision(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
               %s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id,
                command.gate_decision_id,
                command.gate_request_id,
                command.decision,
                command.approver.actor_type.value,
                command.approver.actor_id,
                command.authorization_ref,
                command.assertion_id,
                command.assertion_hash,
                Jsonb(list(command.evidence_refs)),
                Jsonb(dict(command.constraints or {})),
                command.expires_at or None,
                command.command_id,
                command.idempotency_key,
                hash_payload(payload),
                command.actor_type,
                command.actor_id,
                command.reason,
                self._take_human_gate_fault(),
            ),
        )

    def apply_decision(self, command: ApplyHumanGateDecision) -> Mapping[str, Any]:
        payload = {
            "command": "human_gate.apply_decision",
            "project_id": command.project_id,
            "gate_request_id": command.gate_request_id,
            "gate_decision_id": command.gate_decision_id,
            "waiting_record_id": command.waiting_record_id,
            "expected_project_version": command.expected_project_version,
            "expected_waiting_version": command.expected_waiting_version,
            "expected_gate_version": command.expected_gate_version,
            "expected_decision_version": command.expected_decision_version,
            "resume_context_hash": command.resume_context_hash,
            "target_state": command.target_state,
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
            "reason": command.reason,
        }
        return self._call_human_gate(
            """SELECT public.hermes_apply_human_gate_decision(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
               %s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id,
                command.gate_request_id,
                command.gate_decision_id,
                command.waiting_record_id,
                int(command.expected_project_version),
                int(command.expected_waiting_version),
                int(command.expected_gate_version),
                int(command.expected_decision_version),
                command.resume_context_hash,
                command.target_state or None,
                command.command_id,
                command.idempotency_key,
                hash_payload(payload),
                command.actor_type,
                command.actor_id,
                command.reason,
                self._take_human_gate_fault(),
            ),
        )

    def expire_request(self, command: ExpireHumanGateRequest) -> Mapping[str, Any]:
        return self._simple_gate_call(command, "public.hermes_expire_human_gate_request")

    def cancel_request(self, command: CancelHumanGateRequest) -> Mapping[str, Any]:
        payload_extra = {"authorization_ref": command.authorization_ref}
        return self._simple_gate_call(command, "public.hermes_cancel_human_gate_request", payload_extra)

    def supersede_request(self, command: SupersedeHumanGateRequest) -> Mapping[str, Any]:
        payload = {
            "command": "human_gate.supersede",
            "project_id": command.project_id,
            "old_gate_request_id": command.old_gate_request_id,
            "new_gate_request_id": command.new_gate_request_id,
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
            "reason": command.reason,
        }
        return self._call_human_gate(
            """SELECT public.hermes_supersede_human_gate_request(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id,
                command.old_gate_request_id,
                command.new_gate_request_id,
                command.command_id,
                command.idempotency_key,
                hash_payload(payload),
                command.actor_type,
                command.actor_id,
                command.reason,
                self._take_human_gate_fault(),
            ),
        )

    def _simple_gate_call(self, command, function_name: str, extra: Optional[Mapping[str, Any]] = None):
        payload = {
            "command": function_name.split(".")[-1],
            "project_id": command.project_id,
            "gate_request_id": command.gate_request_id,
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
            "reason": command.reason,
        }
        if extra:
            payload.update(extra)
        sql = "SELECT {}(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) AS result".format(function_name)
        args = (
            command.project_id,
            command.gate_request_id,
            getattr(command, "authorization_ref", None),
            command.command_id,
            command.idempotency_key,
            hash_payload(payload),
            command.actor_type,
            command.actor_id,
            command.reason,
            self._take_human_gate_fault(),
        )
        # cancel has authorization_ref, expire ignores NULL with the same wrapper signature.
        return self._call_human_gate(sql, args)

    def _call_human_gate(self, sql: str, args: tuple) -> Mapping[str, Any]:
        try:
            with self._connect(row_factory=dict_row) as connection:
                row = connection.execute(sql, args).fetchone()
                return dict(row["result"])
        except psycopg.Error as exc:
            raise CommandRejected(_reason_from_error(exc)) from exc

    def _take_human_gate_fault(self) -> Optional[str]:
        fault = self._human_gate_fault
        self._human_gate_fault = None
        return fault.value if fault else None


def _reason_from_error(exc: psycopg.Error) -> str:
    text = str(exc)
    for reason in (
        "GATE_REQUEST_NOT_FOUND",
        "GATE_REQUEST_STALE",
        "GATE_REQUEST_EXPIRED",
        "GATE_DECISION_EXPIRED",
        "GATE_DECISION_SUPERSEDED",
        "GATE_APPROVER_UNAUTHORIZED",
        "GATE_SELF_APPROVAL_FORBIDDEN",
        "GATE_SCOPE_MISMATCH",
        "GATE_EVIDENCE_INVALID",
        "GATE_DECISION_NOT_APPROVED",
        "GATE_AGGREGATION_INCOMPLETE",
        "GATE_RESUME_CONTEXT_MISMATCH",
        "GATE_RESUME_GUARD_FAILED",
        "PROJECT_ALREADY_WAITING",
        "PROJECT_NOT_WAITING",
        "PROJECT_TERMINAL",
        "EXPECTED_VERSION_CONFLICT",
        "IDEMPOTENCY_PAYLOAD_CONFLICT",
        "CONTROL_PLANE_AUTHORITY_REQUIRED",
        "SECRET_VALUE_FORBIDDEN",
    ):
        if reason in text:
            return reason
    if "INJECTED_HUMAN_GATE_CRASH_" in text:
        return text.splitlines()[0]
    return text.splitlines()[0] if text else exc.__class__.__name__
