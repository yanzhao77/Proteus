from enum import Enum
from typing import Any, Mapping, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.quarantine import (
    DiscardQuarantine,
    ExpireQuarantine,
    MarkQuarantineAdopted,
    MarkQuarantineRedriven,
    RequestQuarantineAdoption,
    RequestQuarantineRedrive,
    StartQuarantineReview,
)
from hermes_runtime.domain.quarantine import canonical_payload_hash
from hermes_runtime.infrastructure.postgres_worker_execution import PostgresWorkerExecutionStore


class QuarantineFaultPoint(str, Enum):
    AFTER_OPERATION_BEFORE_EVENT = "after_operation_before_event"
    AFTER_EVENT_BEFORE_STATE = "after_event_before_state"


class PostgresQuarantineStore(PostgresWorkerExecutionStore):
    P3_QUARANTINE_TABLES = (
        "quarantine_adoption_requests",
        "quarantine_redrive_requests",
        "quarantine_operations",
        "quarantine_current_states",
    )

    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self._quarantine_fault: Optional[QuarantineFaultPoint] = None

    def fail_quarantine_once(self, point: str) -> None:
        self._quarantine_fault = QuarantineFaultPoint(point)

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "TRUNCATE {} RESTART IDENTITY CASCADE".format(
                    ", ".join(self.P3_QUARANTINE_TABLES)
                )
            )
        super().reset_for_test()

    def start_review(self, command: StartQuarantineReview) -> Mapping[str, Any]:
        payload = self._base_payload("START_REVIEW", command)
        return self._call(
            """SELECT public.hermes_start_quarantine_review(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id,
                command.quarantine_id,
                command.expected_version,
                command.actor.actor_type.value,
                command.actor.actor_id,
                command.authorization_ref,
                command.reason,
                command.retention_until,
                command.command_id,
                command.idempotency_key,
                canonical_payload_hash(payload),
                command.causation_id or None,
                command.correlation_id or command.command_id,
                self._take_quarantine_fault(),
            ),
        )

    def discard(self, command: DiscardQuarantine) -> Mapping[str, Any]:
        payload = self._base_payload("DISCARD", command)
        return self._call(
            """SELECT public.hermes_discard_quarantine(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id,
                command.quarantine_id,
                command.expected_version,
                command.actor.actor_type.value,
                command.actor.actor_id,
                command.authorization_ref,
                command.reason,
                command.retention_until,
                command.command_id,
                command.idempotency_key,
                canonical_payload_hash(payload),
                command.causation_id or None,
                command.correlation_id or command.command_id,
                self._take_quarantine_fault(),
            ),
        )

    def request_adoption(self, command: RequestQuarantineAdoption) -> Mapping[str, Any]:
        payload = self._base_payload(
            "REQUEST_ADOPTION",
            command,
            {
                "guarded_command_id": command.guarded_command_id,
                "guarded_idempotency_key": command.guarded_idempotency_key,
                "semantic_command_type": command.semantic_command_type,
                "guard_refs": dict(command.guard_refs),
            },
        )
        return self._call(
            """SELECT public.hermes_request_quarantine_adoption(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id,
                command.quarantine_id,
                command.expected_version,
                command.actor.actor_type.value,
                command.actor.actor_id,
                command.authorization_ref,
                command.reason,
                command.guarded_command_id,
                command.guarded_idempotency_key,
                command.semantic_command_type,
                Jsonb(dict(command.guard_refs)),
                command.retention_until,
                command.command_id,
                command.idempotency_key,
                canonical_payload_hash(payload),
                command.causation_id or None,
                command.correlation_id or command.command_id,
                self._take_quarantine_fault(),
            ),
        )

    def mark_adopted(self, command: MarkQuarantineAdopted) -> Mapping[str, Any]:
        return self._mark(
            "public.hermes_mark_quarantine_adopted",
            "MARK_ADOPTED",
            command,
            command.adoption_request_id,
        )

    def request_redrive(self, command: RequestQuarantineRedrive) -> Mapping[str, Any]:
        payload = self._base_payload(
            "REQUEST_REDRIVE",
            command,
            {
                "redrive_command_id": command.redrive_command_id,
                "redrive_idempotency_key": command.redrive_idempotency_key,
                "redrive_payload": dict(command.redrive_payload),
            },
        )
        return self._call(
            """SELECT public.hermes_request_quarantine_redrive(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id,
                command.quarantine_id,
                command.expected_version,
                command.actor.actor_type.value,
                command.actor.actor_id,
                command.authorization_ref,
                command.reason,
                command.redrive_command_id,
                command.redrive_idempotency_key,
                Jsonb(dict(command.redrive_payload)),
                command.retention_until,
                command.command_id,
                command.idempotency_key,
                canonical_payload_hash(payload),
                command.causation_id or None,
                command.correlation_id or command.command_id,
                self._take_quarantine_fault(),
            ),
        )

    def mark_redriven(self, command: MarkQuarantineRedriven) -> Mapping[str, Any]:
        return self._mark(
            "public.hermes_mark_quarantine_redriven",
            "MARK_REDRIVEN",
            command,
            command.redrive_request_id,
        )

    def expire(self, command: ExpireQuarantine) -> Mapping[str, Any]:
        payload = self._base_payload("EXPIRE", command)
        return self._call(
            """SELECT public.hermes_expire_quarantine(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id,
                command.quarantine_id,
                command.expected_version,
                command.actor.actor_type.value,
                command.actor.actor_id,
                command.reason,
                command.command_id,
                command.idempotency_key,
                canonical_payload_hash(payload),
                command.causation_id or None,
                command.correlation_id or command.command_id,
                self._take_quarantine_fault(),
            ),
        )

    def _mark(self, function_name: str, operation: str, command, request_id: str) -> Mapping[str, Any]:
        payload = self._base_payload(operation, command, {"request_id": request_id})
        return self._call(
            """SELECT {}(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""".format(function_name),
            (
                command.project_id,
                command.quarantine_id,
                request_id,
                command.expected_version,
                command.actor.actor_type.value,
                command.actor.actor_id,
                command.authorization_ref,
                command.reason,
                command.command_id,
                command.idempotency_key,
                canonical_payload_hash(payload),
                command.causation_id or None,
                command.correlation_id or command.command_id,
                self._take_quarantine_fault(),
            ),
        )

    def _base_payload(self, operation: str, command, extra: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        payload = {
            "command": "quarantine." + operation.lower(),
            "project_id": command.project_id,
            "quarantine_id": command.quarantine_id,
            "expected_version": command.expected_version,
            "actor_type": command.actor.actor_type.value,
            "actor_id": command.actor.actor_id,
            "reason": command.reason,
            "authorization_ref": getattr(command, "authorization_ref", ""),
        }
        if extra:
            payload.update(extra)
        return payload

    def _call(self, sql: str, args: tuple) -> Mapping[str, Any]:
        try:
            with self._connect(row_factory=dict_row) as connection:
                row = connection.execute(sql, args).fetchone()
                return dict(row["result"])
        except psycopg.Error as exc:
            raise CommandRejected(_reason_from_error(exc)) from exc

    def _take_quarantine_fault(self) -> Optional[str]:
        fault = self._quarantine_fault
        self._quarantine_fault = None
        return fault.value if fault else None


def _reason_from_error(exc: psycopg.Error) -> str:
    return exc.diag.message_primary or exc.__class__.__name__
