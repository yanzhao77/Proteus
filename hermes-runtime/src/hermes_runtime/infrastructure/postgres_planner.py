import hashlib
import json
from enum import Enum
from typing import Any, Mapping, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.planning import PlanCandidates
from hermes_runtime.domain.planner import (
    REGISTRY_VERSION,
    RESOURCE_ESTIMATOR_VERSION,
    EvidenceRequestRef,
    HypothesisRef,
    PlannerRejected,
    PlanningInput,
    generate_planning_run,
)
from hermes_runtime.infrastructure.postgres import PostgresRuntimeStore


class PlannerFaultPoint(str, Enum):
    AFTER_PLANNING_RUN_BEFORE_CANDIDATE = "after_planning_run_before_candidate"
    AFTER_CANDIDATE_BEFORE_CHILD = "after_candidate_before_child"
    AFTER_CHILD_BEFORE_CURRENT = "after_child_before_current"
    AFTER_CURRENT_BEFORE_EVENT = "after_current_before_event"
    AFTER_EVENT_BEFORE_OUTBOX = "after_event_before_outbox"
    AFTER_OUTBOX_BEFORE_RECEIPT = "after_outbox_before_receipt"


class PostgresPlannerStore(PostgresRuntimeStore):
    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self._planner_fault: Optional[PlannerFaultPoint] = None

    def fail_planner_once(self, point: PlannerFaultPoint) -> None:
        self._planner_fault = point

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """TRUNCATE current_planning_runs,
                   candidate_action_resource_estimates,
                   candidate_action_expected_outputs,
                   candidate_action_preconditions,
                   candidate_action_capabilities,
                   candidate_action_targets, candidate_actions, planning_runs,
                   current_diagnoses, diagnosis_evidence_requests,
                   diagnosis_hypotheses, diagnosis_evidence, diagnosis_findings,
                   diagnoses, situation_versions, situations, analysis_contexts,
                   delivery_operational_alerts, delivery_metric_counters,
                   local_transport_publications, consumer_quarantine,
                   consumer_pending_gaps, outbox_redrive_records,
                   outbox_delivery_dlq, outbox_delivery_attempts,
                   consumer_checkpoints, consumer_effects, consumer_inbox,
                   audit_records, outbox_messages, event_log,
                   event_partition_sequences, command_receipts,
                   resource_reconcile_records, resource_settlement_usage,
                   resource_settlements, resource_usage_amounts,
                   resource_usage_records, resource_reservation_amounts,
                   resource_reservations, resource_preparations,
                   resource_balances, resource_accounts,
                   project_budget_facts, project_policy_decision_facts,
                   project_evidence_facts, project_gate_decision_facts,
                   project_transition_records, feedback_records,
                   task_dependencies, work_graph_edges, project_graph_versions,
                   verification_check_results, verification_evidence,
                   verification_results, evidence, completion_claims, artifacts,
                   verification_plan_checks, verification_plans, agent_runs,
                   verifier_identities, tasks, projects
                   RESTART IDENTITY CASCADE"""
            )

    def plan_candidates(self, command: PlanCandidates) -> Mapping[str, Any]:
        request_hash = self._request_hash(command)
        try:
            with self._connect(row_factory=dict_row) as connection:
                existing = self._begin_command(connection, command, request_hash)
                if existing is not None:
                    return existing
                inputs = self._load_inputs(connection, command)
                result = generate_planning_run(inputs)
                fault = self._planner_fault
                self._planner_fault = None
                payload = self._apply(
                    connection, command, inputs, result,
                    fault.value if fault else None,
                )
                response = self._response(result, payload)
                receipt = {
                    "command_id": command.command_id,
                    "status": "APPLIED",
                    "result_code": "CANDIDATE_ACTIONS_PLANNED",
                    "target_version": command.expected_situation_version,
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
        except PlannerRejected as exc:
            rejected = CommandRejected(str(exc))
            self._persist_rejection(command, request_hash, rejected.code, rejected.detail)
            raise rejected
        except CommandRejected as exc:
            self._persist_rejection(command, request_hash, exc.code, exc.detail)
            raise
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary
            if code.startswith("INJECTED_PLANNER_CRASH_"):
                raise RuntimeError("injected planner crash: " + code)
            rejected = CommandRejected(code)
            self._persist_rejection(command, request_hash, rejected.code, rejected.detail)
            raise rejected

    def _begin_command(self, connection, command, request_hash):
        inserted = connection.execute(
            """INSERT INTO command_receipts(
               command_id, project_id, command_type, idempotency_key,
               request_hash, status, result)
               VALUES (%s,%s,'planner.plan_candidates',%s,%s,'PROCESSING','{}'::jsonb)
               ON CONFLICT DO NOTHING RETURNING command_id""",
            (command.command_id, command.project_id, command.idempotency_key,
             request_hash),
        ).fetchone()
        if inserted:
            return None
        row = connection.execute(
            """SELECT request_hash,status,result FROM command_receipts
               WHERE project_id=%s AND command_type='planner.plan_candidates'
                 AND idempotency_key=%s FOR UPDATE""",
            (command.project_id, command.idempotency_key),
        ).fetchone()
        if not row or row["request_hash"] != request_hash:
            raise CommandRejected("PLANNER_IDEMPOTENCY_CONFLICT")
        if row["status"] == "APPLIED":
            return dict(row["result"]["response"])
        if row["status"] == "REJECTED":
            result = row["result"]
            raise CommandRejected(result["result_code"], result.get("detail", ""))
        raise CommandRejected("COMMAND_IN_PROGRESS")

    def _load_inputs(self, connection, command):
        if command.registry_version != REGISTRY_VERSION:
            raise CommandRejected("PLANNER_REGISTRY_VERSION_UNSUPPORTED")
        situation = connection.execute(
            """SELECT * FROM situations WHERE situation_id=%s AND project_id=%s""",
            (command.situation_id, command.project_id),
        ).fetchone()
        if not situation:
            raise CommandRejected("PLANNER_SITUATION_NOT_FOUND")
        if situation["status"] != "OPEN":
            raise CommandRejected("PLANNER_SITUATION_NOT_OPEN")
        if int(situation["version"]) != command.expected_situation_version:
            raise CommandRejected("PLANNER_SITUATION_VERSION_CONFLICT")
        if situation["analysis_context_id"] != command.analysis_context_id:
            raise CommandRejected("PLANNER_CONTEXT_NOT_FOUND")
        context = connection.execute(
            """SELECT * FROM analysis_contexts
               WHERE analysis_context_id=%s AND project_id=%s""",
            (command.analysis_context_id, command.project_id),
        ).fetchone()
        if not context:
            raise CommandRejected("PLANNER_CONTEXT_NOT_FOUND")
        if context["context_hash"] != command.analysis_context_hash:
            raise CommandRejected("PLANNER_CONTEXT_HASH_MISMATCH")

        diagnosis = None
        hypotheses = ()
        requests = ()
        if situation["type"] == "verification_failed":
            diagnosis = self._load_current_diagnosis(connection, command, situation)
            hypotheses = self._load_hypotheses(connection, diagnosis["diagnosis_id"])
            requests = self._load_requests(connection, diagnosis["diagnosis_id"])
        elif command.expected_diagnosis_id is not None:
            raise CommandRejected("PLANNER_DIAGNOSIS_NOT_ALLOWED")

        task_state = None
        if situation["task_id"]:
            row = connection.execute(
                """SELECT state FROM tasks
                   WHERE task_id=%s AND project_id=%s""",
                (situation["task_id"], command.project_id),
            ).fetchone()
            if row:
                task_state = row["state"]
        budget_status = self._budget_status(situation)
        return PlanningInput(
            command.project_id,
            command.situation_id,
            command.expected_situation_version,
            situation["type"],
            command.analysis_context_id,
            command.analysis_context_hash,
            situation["task_id"],
            task_state,
            context["work_graph_version_ref"],
            budget_status,
            diagnosis["diagnosis_id"] if diagnosis else None,
            diagnosis["input_hash"] if diagnosis else None,
            diagnosis["root_cause_status"] if diagnosis else None,
            diagnosis["root_cause"] if diagnosis else None,
            hypotheses,
            requests,
            command.registry_version,
            command.planner_rule_version,
            RESOURCE_ESTIMATOR_VERSION,
        )

    def _load_current_diagnosis(self, connection, command, situation):
        if not command.expected_diagnosis_id or not command.expected_diagnosis_input_hash:
            raise CommandRejected("PLANNER_DIAGNOSIS_REQUIRED")
        row = connection.execute(
            """SELECT d.* FROM current_diagnoses cd
               JOIN diagnoses d ON d.diagnosis_id=cd.diagnosis_id
               WHERE cd.situation_id=%s""",
            (command.situation_id,),
        ).fetchone()
        if not row or row["diagnosis_id"] != command.expected_diagnosis_id:
            raise CommandRejected("PLANNER_DIAGNOSIS_NOT_CURRENT")
        if (int(row["situation_version"]) != command.expected_situation_version
                or row["analysis_context_hash"] != command.analysis_context_hash):
            raise CommandRejected("PLANNER_DIAGNOSIS_NOT_CURRENT")
        if row["input_hash"] != command.expected_diagnosis_input_hash:
            raise CommandRejected("PLANNER_DIAGNOSIS_INPUT_MISMATCH")
        if row["situation_id"] != situation["situation_id"]:
            raise CommandRejected("PLANNER_DIAGNOSIS_NOT_CURRENT")
        return row

    def _load_hypotheses(self, connection, diagnosis_id):
        rows = connection.execute(
            """SELECT description_code, confidence_basis_points,
                      test_action_hint, ordinal
               FROM diagnosis_hypotheses WHERE diagnosis_id=%s
               ORDER BY ordinal, description_code""",
            (diagnosis_id,),
        ).fetchall()
        return tuple(HypothesisRef(
            row["description_code"], row["confidence_basis_points"],
            row["test_action_hint"], row["ordinal"],
        ) for row in rows)

    def _load_requests(self, connection, diagnosis_id):
        rows = connection.execute(
            """SELECT request_code,evidence_kind,target_ref,reason_code,priority
               FROM diagnosis_evidence_requests WHERE diagnosis_id=%s
               ORDER BY priority, request_code, target_ref""",
            (diagnosis_id,),
        ).fetchall()
        return tuple(EvidenceRequestRef(
            row["request_code"], row["evidence_kind"], row["target_ref"],
            row["reason_code"], row["priority"],
        ) for row in rows)

    @staticmethod
    def _budget_status(situation):
        failure = str(situation["failure_type"] or "").lower()
        constraints = {str(item).lower() for item in (situation["constraints"] or ())}
        for status in ("HARD_STOP", "GATE", "WARN"):
            key = status.lower()
            if failure.endswith(key) or "budget_" + key in constraints:
                return status
        return None

    def _apply(self, connection, command, inputs, result, fault):
        row = connection.execute(
            """SELECT public.hermes_apply_planning_run(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                result.planning_run_id,
                inputs.project_id,
                inputs.situation_id,
                inputs.situation_version,
                inputs.analysis_context_id,
                inputs.analysis_context_hash,
                inputs.diagnosis_id,
                inputs.diagnosis_input_hash,
                inputs.registry_version,
                inputs.planner_rule_version,
                inputs.resource_estimator_version,
                result.input_hash,
                len(result.candidate_actions),
                result.single_candidate_reason_code,
                Jsonb(self._candidate_payload(result.candidate_actions)),
                command.command_id,
                command.actor_type,
                command.actor_id,
                fault,
            ),
        ).fetchone()
        return dict(row["result"])

    def _response(self, result, payload):
        return {
            "planning_run_id": result.planning_run_id,
            "input_hash": result.input_hash,
            "candidate_count": len(result.candidate_actions),
            "single_candidate_reason_code": result.single_candidate_reason_code,
            "candidate_action_ids": [item.action_id for item in result.candidate_actions],
            "event_id": payload.get("event_id"),
            "deduplicated": payload.get("deduplicated", False),
        }

    @staticmethod
    def _candidate_payload(actions):
        return [
            {
                "action_id": item.action_id,
                "type": item.action_type.value,
                "reason_code": item.reason_code,
                "target_refs": list(item.target_refs),
                "required_capabilities": list(item.required_capabilities),
                "parameters": dict(item.parameters),
                "expected_outputs": list(item.expected_outputs),
                "preconditions": list(item.preconditions),
                "estimated_resources": {
                    "amounts": dict(item.estimated_resources.amounts),
                    "currency": item.estimated_resources.currency,
                    "estimator_version": item.estimated_resources.estimator_version,
                },
                "planner_confidence_basis_points": item.planner_confidence_basis_points,
                "expected_progress_basis_points": item.expected_progress_basis_points,
                "evidence_gain_basis_points": item.evidence_gain_basis_points,
                "reversibility_basis_points": item.reversibility_basis_points,
                "ordinal": item.ordinal,
                "content_hash": item.content_hash,
            }
            for item in actions
        ]

    def _persist_rejection(self, command, request_hash: str, code: str, detail: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO command_receipts(
                   command_id,project_id,command_type,idempotency_key,
                   request_hash,status,result,completed_at)
                   VALUES (%s,%s,'planner.plan_candidates',%s,%s,'REJECTED',%s,now())
                   ON CONFLICT DO NOTHING""",
                (command.command_id, command.project_id, command.idempotency_key,
                 request_hash, Jsonb({"result_code": code, "detail": detail})),
            )
            try:
                connection.execute(
                    """INSERT INTO audit_records(
                       audit_id, project_id, source_command_id, actor_type, actor_id,
                       action, outcome, reason_code, detail)
                       VALUES (%s,%s,%s,%s,%s,'planner.plan_candidates',
                               'REJECTED',%s,%s)
                       ON CONFLICT (source_command_id, reason_code) DO NOTHING""",
                    ("audit-" + _hash_value({
                        "command_id": command.command_id, "code": code
                    })[:32], command.project_id, command.command_id,
                     command.actor_type, command.actor_id, code, detail),
                )
            except psycopg.errors.InsufficientPrivilege:
                pass

    @staticmethod
    def _request_hash(command: PlanCandidates) -> str:
        return _hash_value({
            "command_type": "planner.plan_candidates",
            "project_id": command.project_id,
            "situation_id": command.situation_id,
            "expected_situation_version": command.expected_situation_version,
            "analysis_context_id": command.analysis_context_id,
            "analysis_context_hash": command.analysis_context_hash,
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
            "reason": command.reason,
            "expected_diagnosis_id": command.expected_diagnosis_id,
            "expected_diagnosis_input_hash": command.expected_diagnosis_input_hash,
            "registry_version": command.registry_version,
            "planner_rule_version": command.planner_rule_version,
        })


def _hash_value(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True).encode("utf-8")
    ).hexdigest()
