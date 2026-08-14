from enum import Enum
from typing import Any, Mapping, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.evidence_invalidation import InvalidateEvidence
from hermes_runtime.domain.evidence_invalidation import canonical_payload_hash
from hermes_runtime.infrastructure.postgres_human_gate import PostgresHumanGateStore


class EvidenceInvalidationFaultPoint(str, Enum):
    AFTER_INVALIDATION_BEFORE_EVENT = "after_invalidation_before_event"
    AFTER_EVENT_BEFORE_STATE = "after_event_before_state"


class PostgresEvidenceInvalidationStore(PostgresHumanGateStore):
    P3_EVIDENCE_TABLES = (
        "reverification_requirements",
        "evidence_dependency_stale_records",
        "evidence_invalidation_records",
        "evidence_current_states",
    )

    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self._evidence_fault: Optional[EvidenceInvalidationFaultPoint] = None

    def fail_evidence_invalidation_once(self, point: str) -> None:
        self._evidence_fault = EvidenceInvalidationFaultPoint(point)

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "TRUNCATE {} RESTART IDENTITY CASCADE".format(
                    ", ".join(self.P3_EVIDENCE_TABLES)
                )
            )
        super().reset_for_test()

    def invalidate(self, command: InvalidateEvidence) -> Mapping[str, Any]:
        payload = {
            "command": "evidence.invalidate",
            "project_id": command.project_id,
            "evidence_id": command.evidence_id,
            "expected_version": command.expected_version,
            "actor_type": command.actor.actor_type.value,
            "actor_id": command.actor.actor_id,
            "producer": command.producer,
            "reason_code": command.reason_code,
            "reason": command.reason,
            "scope": command.scope,
            "affected_refs": dict(command.affected_refs),
            "dependency_refs": list(command.dependency_refs),
            "authorization_ref": command.authorization_ref,
        }
        return self._call(
            """SELECT public.hermes_invalidate_evidence(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                command.project_id,
                command.evidence_id,
                command.expected_version,
                command.actor.actor_type.value,
                command.actor.actor_id,
                command.producer,
                command.reason_code,
                command.reason,
                command.scope,
                Jsonb(dict(command.affected_refs)),
                Jsonb(list(command.dependency_refs)),
                command.authorization_ref,
                command.command_id,
                command.idempotency_key,
                canonical_payload_hash(payload),
                command.causation_id or None,
                command.correlation_id or command.command_id,
                self._take_evidence_fault(),
            ),
        )

    def _call(self, sql: str, args: tuple) -> Mapping[str, Any]:
        try:
            with self._connect(row_factory=dict_row) as connection:
                row = connection.execute(sql, args).fetchone()
                return dict(row["result"])
        except psycopg.Error as exc:
            raise CommandRejected(_reason_from_error(exc)) from exc

    def _take_evidence_fault(self) -> Optional[str]:
        fault = self._evidence_fault
        self._evidence_fault = None
        return fault.value if fault else None


def _reason_from_error(exc: psycopg.Error) -> str:
    return exc.diag.message_primary or exc.__class__.__name__
