import hashlib
import json
from enum import Enum
from typing import Any, Mapping, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.risks import AssessRisk
from hermes_runtime.domain.risk import RISK_RULE_VERSION, RiskInput, RiskRejected, assess_risk
from hermes_runtime.infrastructure.postgres import PostgresRuntimeStore
from hermes_runtime.infrastructure.postgres_policy import _evaluation_context_id, _hash_json, _load_current_candidate


class RiskFaultPoint(str, Enum):
    AFTER_CONTEXT_BEFORE_RESULT = "after_context_before_result"
    AFTER_RESULT_BEFORE_CHILD = "after_result_before_child"
    AFTER_CHILD_BEFORE_CURRENT = "after_child_before_current"
    AFTER_CURRENT_BEFORE_EVENT = "after_current_before_event"
    AFTER_EVENT_BEFORE_OUTBOX = "after_event_before_outbox"
    AFTER_OUTBOX_BEFORE_RECEIPT = "after_outbox_before_receipt"


class PostgresRiskStore(PostgresRuntimeStore):
    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self._risk_fault: Optional[RiskFaultPoint] = None

    def fail_risk_once(self, point: RiskFaultPoint) -> None:
        self._risk_fault = point

    def assess_risk(self, command: AssessRisk) -> Mapping[str, Any]:
        request_hash = self._request_hash(command)
        try:
            with self._connect(row_factory=dict_row) as connection:
                existing = self._begin_command(connection, command, request_hash)
                if existing is not None:
                    return existing
                inputs = self._load_inputs(connection, command)
                assessment = assess_risk(inputs)
                context = _evaluation_context_id(inputs, command.target_environment)
                resource_hash = _hash_json(inputs.estimated_resources)
                fault = self._risk_fault
                self._risk_fault = None
                payload = connection.execute(
                    """SELECT public.hermes_apply_risk_assessment(
                       %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       %s,%s,%s,%s,%s,%s,%s,%s,%s
                       ) AS result""",
                    (
                        assessment.risk_assessment_id, context["evaluation_context_id"],
                        inputs.project_id, inputs.planning_run_id,
                        inputs.planner_input_hash, inputs.action_id,
                        inputs.action_content_hash, inputs.situation_version,
                        assessment.risk_score_basis_points, assessment.risk_level.value,
                        Jsonb(dict(assessment.factors)), list(assessment.reason_codes),
                        list(assessment.required_mitigations),
                        list(assessment.available_mitigations),
                        assessment.residual_risk_basis_points,
                        assessment.risk_model_version, assessment.risk_rule_version,
                        assessment.risk_input_hash, context["context_hash"],
                        resource_hash, command.target_environment, command.command_id,
                        command.actor_type, command.actor_id,
                        fault.value if fault else None,
                    ),
                ).fetchone()["result"]
                response = {
                    "risk_assessment_id": assessment.risk_assessment_id,
                    "risk_score_basis_points": assessment.risk_score_basis_points,
                    "risk_level": assessment.risk_level.value,
                    "factors": dict(assessment.factors),
                    "reason_codes": list(assessment.reason_codes),
                    "required_mitigations": list(assessment.required_mitigations),
                    "available_mitigations": list(assessment.available_mitigations),
                    "residual_risk_basis_points": assessment.residual_risk_basis_points,
                    "risk_input_hash": assessment.risk_input_hash,
                    "event_id": payload.get("event_id"),
                    "deduplicated": payload.get("deduplicated", False),
                }
                receipt = {
                    "command_id": command.command_id,
                    "status": "APPLIED",
                    "result_code": "RISK_ASSESSED",
                    "event_ids": [payload["event_id"]] if payload.get("event_id") else [],
                    "response": response,
                }
                connection.execute(
                    """UPDATE command_receipts SET status='APPLIED',
                       result=%s, completed_at=now()
                       WHERE command_id=%s AND status='PROCESSING'""",
                    (Jsonb(receipt), command.command_id),
                )
                return response
        except RiskRejected as exc:
            rejected = CommandRejected(str(exc))
            self._persist_rejection(command, request_hash, rejected.code, rejected.detail)
            raise rejected
        except CommandRejected as exc:
            self._persist_rejection(command, request_hash, exc.code, exc.detail)
            raise
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary
            if code.startswith("INJECTED_RISK_CRASH_"):
                raise RuntimeError("injected risk crash: " + code)
            rejected = CommandRejected(code)
            self._persist_rejection(command, request_hash, rejected.code, rejected.detail)
            raise rejected

    def _begin_command(self, connection, command, request_hash):
        inserted = connection.execute(
            """INSERT INTO command_receipts(
               command_id, project_id, command_type, idempotency_key,
               request_hash, status, result)
               VALUES (%s,%s,'risk.assess',%s,%s,'PROCESSING','{}'::jsonb)
               ON CONFLICT DO NOTHING RETURNING command_id""",
            (command.command_id, command.project_id, command.idempotency_key, request_hash),
        ).fetchone()
        if inserted:
            return None
        row = connection.execute(
            """SELECT request_hash,status,result FROM command_receipts
               WHERE project_id=%s AND command_type='risk.assess'
                 AND idempotency_key=%s FOR UPDATE""",
            (command.project_id, command.idempotency_key),
        ).fetchone()
        if not row or row["request_hash"] != request_hash:
            raise CommandRejected("RISK_IDEMPOTENCY_CONFLICT")
        if row["status"] == "APPLIED":
            return dict(row["result"]["response"])
        raise CommandRejected("COMMAND_IN_PROGRESS")

    def _load_inputs(self, connection, command):
        row = _load_current_candidate(connection, command, "RISK")
        params = dict(row["parameters"])
        target_env = params.get("target_environment") or command.target_environment
        return RiskInput(
            row["project_id"], row["planning_run_id"], row["planner_input_hash"],
            row["action_id"], row["content_hash"], row["type"],
            tuple(row["target_refs"] or ()), tuple(row["required_capabilities"] or ()),
            params, dict(row["estimated_resources"]), row["reversibility_basis_points"],
            row["situation_id"], row["situation_version"], row["analysis_context_hash"],
            row["diagnosis_id"], row["diagnosis_input_hash"], row["registry_version"],
            str(target_env or "unknown"), tuple(command.verified_mitigations),
            command.risk_model_version, RISK_RULE_VERSION,
        )

    def _persist_rejection(self, command, request_hash, code, detail):
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO command_receipts(
                   command_id,project_id,command_type,idempotency_key,
                   request_hash,status,result,completed_at)
                   VALUES (%s,%s,'risk.assess',%s,%s,'REJECTED',%s,now())
                   ON CONFLICT DO NOTHING""",
                (command.command_id, command.project_id, command.idempotency_key,
                 request_hash, Jsonb({"result_code": code, "detail": detail})),
            )

    @staticmethod
    def _request_hash(command: AssessRisk) -> str:
        return _hash_json({
            "command_type": "risk.assess",
            "project_id": command.project_id,
            "planning_run_id": command.planning_run_id,
            "action_id": command.action_id,
            "expected_situation_version": command.expected_situation_version,
            "expected_action_content_hash": command.expected_action_content_hash,
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
            "reason": command.reason,
            "risk_model_version": command.risk_model_version,
            "target_environment": command.target_environment,
            "verified_mitigations": list(command.verified_mitigations),
        })
