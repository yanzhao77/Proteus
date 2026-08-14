from enum import Enum
from typing import Any, Mapping, Optional

import psycopg
from psycopg.rows import dict_row

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.recovery import (
    CompleteRecoveryAttempt,
    EmitExecutionFeedback,
    PlanRecoveryAttempt,
)
from hermes_runtime.domain.recovery import hash_payload
from hermes_runtime.infrastructure.postgres_worker_execution import PostgresWorkerExecutionStore


class RecoveryFaultPoint(str, Enum):
    AFTER_EVENT_BEFORE_OUTBOX = "after_event_before_outbox"
    AFTER_FEEDBACK_EVENT = "after_feedback_event"
    AFTER_FEEDBACK_RECORD = "after_feedback_record"
    AFTER_RECEIPT_BEFORE_COMMIT = "after_receipt_before_commit"


class PostgresRecoveryStore(PostgresWorkerExecutionStore):
    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self._recovery_fault: Optional[RecoveryFaultPoint] = None

    def fail_recovery_once(self, point: str) -> None:
        self._recovery_fault = RecoveryFaultPoint(point)

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """TRUNCATE recovery_collaboration_requests, recovery_attempts,
                   recovery_cycles, execution_feedback_records
                   RESTART IDENTITY CASCADE"""
            )
        super().reset_for_test()

    def emit_execution_feedback(self, command: EmitExecutionFeedback) -> Mapping[str, Any]:
        payload = {
            "command": "recovery.emit_feedback",
            "project_id": command.project_id,
            "result_id": command.result_id,
            "feedback_id": command.feedback_id,
            "repair_task_id": command.repair_task_id,
            "max_attempts": int(command.max_attempts),
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
            "reason": command.reason,
        }
        payload_hash = hash_payload(payload)
        return self._call_recovery(
            """SELECT public.hermes_emit_execution_feedback(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id, command.result_id, command.feedback_id,
                command.repair_task_id, int(command.max_attempts),
                command.command_id, command.idempotency_key, payload_hash,
                command.actor_type, command.actor_id, command.reason,
                self._take_recovery_fault(),
            ),
        )

    def plan_recovery_attempt(self, command: PlanRecoveryAttempt) -> Mapping[str, Any]:
        payload = {
            "command": "recovery.plan_attempt",
            "project_id": command.project_id,
            "cycle_id": command.cycle_id,
            "attempt_id": command.attempt_id,
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
            "reason": command.reason,
        }
        payload_hash = hash_payload(payload)
        return self._call_recovery(
            """SELECT public.hermes_plan_recovery_attempt(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id, command.cycle_id, command.attempt_id,
                command.command_id, command.idempotency_key, payload_hash,
                command.actor_type, command.actor_id, command.reason,
                self._take_recovery_fault(),
            ),
        )

    def complete_recovery_attempt(self, command: CompleteRecoveryAttempt) -> Mapping[str, Any]:
        payload = {
            "command": "recovery.complete_attempt",
            "project_id": command.project_id,
            "attempt_id": command.attempt_id,
            "outcome": command.outcome,
            "linked_execution_request_id": command.linked_execution_request_id,
            "linked_result_id": command.linked_result_id,
            "linked_verification_id": command.linked_verification_id,
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
            "reason": command.reason,
        }
        payload_hash = hash_payload(payload)
        return self._call_recovery(
            """SELECT public.hermes_complete_recovery_attempt(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id, command.attempt_id, command.outcome,
                command.linked_execution_request_id, command.linked_result_id,
                command.linked_verification_id, command.command_id,
                command.idempotency_key, payload_hash, command.actor_type,
                command.actor_id, command.reason, self._take_recovery_fault(),
            ),
        )

    def _call_recovery(self, sql: str, args: tuple) -> Mapping[str, Any]:
        try:
            with self._connect(row_factory=dict_row) as connection:
                row = connection.execute(sql, args).fetchone()
                return dict(row["result"])
        except psycopg.Error as exc:
            raise CommandRejected(_reason_from_error(exc)) from exc

    def _take_recovery_fault(self) -> Optional[str]:
        fault = self._recovery_fault
        self._recovery_fault = None
        return fault.value if fault else None


def _reason_from_error(exc: psycopg.Error) -> str:
    text = str(exc)
    for reason in (
        "RECOVERY_AUTHORITY_REQUIRED",
        "RECOVERY_POLICY_INVALID",
        "RECOVERY_POLICY_VERSION_UNSUPPORTED",
        "RECOVERY_IDEMPOTENCY_CONFLICT",
        "RECOVERY_FEEDBACK_SOURCE_NOT_FAILED",
        "RECOVERY_CYCLE_NOT_FOUND",
        "RECOVERY_CYCLE_NOT_OPEN",
        "RECOVERY_ATTEMPT_NOT_FOUND",
        "RECOVERY_ATTEMPT_ALREADY_TERMINAL",
        "RECOVERY_ATTEMPT_OUTCOME_INVALID",
        "SECRET_VALUE_FORBIDDEN",
    ):
        if reason in text:
            return reason
    if "INJECTED_RECOVERY_CRASH_" in text:
        return text.splitlines()[0]
    return text.splitlines()[0] if text else exc.__class__.__name__
