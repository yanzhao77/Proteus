import hashlib
import json
from enum import Enum
from typing import Any, Mapping, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.policies import EvaluatePolicy
from hermes_runtime.domain.policy import (
    POLICY_RULE_VERSION,
    PolicyInput,
    PolicyRejected,
    evaluate_policy,
)
from hermes_runtime.infrastructure.postgres import PostgresRuntimeStore


class PolicyFaultPoint(str, Enum):
    AFTER_CONTEXT_BEFORE_RESULT = "after_context_before_result"
    AFTER_RESULT_BEFORE_CHILD = "after_result_before_child"
    AFTER_CHILD_BEFORE_CURRENT = "after_child_before_current"
    AFTER_CURRENT_BEFORE_EVENT = "after_current_before_event"
    AFTER_EVENT_BEFORE_OUTBOX = "after_event_before_outbox"
    AFTER_OUTBOX_BEFORE_RECEIPT = "after_outbox_before_receipt"


class PostgresPolicyStore(PostgresRuntimeStore):
    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self._policy_fault: Optional[PolicyFaultPoint] = None

    def fail_policy_once(self, point: PolicyFaultPoint) -> None:
        self._policy_fault = point

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """TRUNCATE current_risk_assessments, risk_mitigations,
                   risk_factors, risk_assessments, current_policy_decisions,
                   policy_constraints, policy_decision_rules, policy_decisions,
                   policy_evaluation_contexts, current_planning_runs,
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

    def evaluate_policy(self, command: EvaluatePolicy) -> Mapping[str, Any]:
        request_hash = self._request_hash(command)
        try:
            with self._connect(row_factory=dict_row) as connection:
                existing = self._begin_command(connection, command, request_hash)
                if existing is not None:
                    return existing
                inputs = self._load_inputs(connection, command)
                decision = evaluate_policy(inputs)
                context = _evaluation_context_id(inputs, command.target_environment)
                resource_hash = _hash_json(inputs.estimated_resources)
                fault = self._policy_fault
                self._policy_fault = None
                payload = connection.execute(
                    """SELECT public.hermes_apply_policy_decision(
                       %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       %s,%s,%s,%s,%s,%s
                       ) AS result""",
                    (
                        decision.policy_decision_id, context["evaluation_context_id"],
                        inputs.project_id, inputs.planning_run_id,
                        inputs.planner_input_hash, inputs.action_id,
                        inputs.action_content_hash, inputs.situation_version,
                        decision.result.value, list(decision.matched_rule_ids),
                        list(decision.reason_codes), Jsonb(dict(decision.constraints)),
                        decision.policy_bundle_version, decision.policy_rule_version,
                        decision.policy_input_hash, context["context_hash"],
                        resource_hash, command.target_environment,
                        command.command_id, command.actor_type, command.actor_id,
                        fault.value if fault else None,
                    ),
                ).fetchone()["result"]
                response = {
                    "policy_decision_id": decision.policy_decision_id,
                    "result": decision.result.value,
                    "matched_rule_ids": list(decision.matched_rule_ids),
                    "reason_codes": list(decision.reason_codes),
                    "constraints": dict(decision.constraints),
                    "policy_input_hash": decision.policy_input_hash,
                    "event_id": payload.get("event_id"),
                    "deduplicated": payload.get("deduplicated", False),
                }
                receipt = {
                    "command_id": command.command_id,
                    "status": "APPLIED",
                    "result_code": "POLICY_EVALUATED",
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
        except PolicyRejected as exc:
            rejected = CommandRejected(str(exc))
            self._persist_rejection(command, request_hash, rejected.code, rejected.detail)
            raise rejected
        except CommandRejected as exc:
            self._persist_rejection(command, request_hash, exc.code, exc.detail)
            raise
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary
            if code.startswith("INJECTED_POLICY_CRASH_"):
                raise RuntimeError("injected policy crash: " + code)
            rejected = CommandRejected(code)
            self._persist_rejection(command, request_hash, rejected.code, rejected.detail)
            raise rejected

    def _begin_command(self, connection, command, request_hash):
        inserted = connection.execute(
            """INSERT INTO command_receipts(
               command_id, project_id, command_type, idempotency_key,
               request_hash, status, result)
               VALUES (%s,%s,'policy.evaluate',%s,%s,'PROCESSING','{}'::jsonb)
               ON CONFLICT DO NOTHING RETURNING command_id""",
            (command.command_id, command.project_id, command.idempotency_key, request_hash),
        ).fetchone()
        if inserted:
            return None
        row = connection.execute(
            """SELECT request_hash,status,result FROM command_receipts
               WHERE project_id=%s AND command_type='policy.evaluate'
                 AND idempotency_key=%s FOR UPDATE""",
            (command.project_id, command.idempotency_key),
        ).fetchone()
        if not row or row["request_hash"] != request_hash:
            raise CommandRejected("POLICY_IDEMPOTENCY_CONFLICT")
        if row["status"] == "APPLIED":
            return dict(row["result"]["response"])
        raise CommandRejected("COMMAND_IN_PROGRESS")

    def _load_inputs(self, connection, command) -> PolicyInput:
        row = _load_current_candidate(connection, command, "POLICY")
        params = dict(row["parameters"])
        target_env = params.get("target_environment") or command.target_environment
        return PolicyInput(
            row["project_id"], row["planning_run_id"], row["planner_input_hash"],
            row["action_id"], row["content_hash"], row["type"],
            tuple(row["target_refs"] or ()), tuple(row["required_capabilities"] or ()),
            params, dict(row["estimated_resources"]), row["planner_confidence_basis_points"],
            row["expected_progress_basis_points"], row["evidence_gain_basis_points"],
            row["situation_id"], row["situation_version"], row["analysis_context_hash"],
            row["diagnosis_id"], row["diagnosis_input_hash"], row["registry_version"],
            str(target_env or "unknown"), command.runtime_emergency_freeze,
            command.policy_bundle_version, POLICY_RULE_VERSION,
        )

    def _persist_rejection(self, command, request_hash, code, detail):
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO command_receipts(
                   command_id,project_id,command_type,idempotency_key,
                   request_hash,status,result,completed_at)
                   VALUES (%s,%s,'policy.evaluate',%s,%s,'REJECTED',%s,now())
                   ON CONFLICT DO NOTHING""",
                (command.command_id, command.project_id, command.idempotency_key,
                 request_hash, Jsonb({"result_code": code, "detail": detail})),
            )

    @staticmethod
    def _request_hash(command: EvaluatePolicy) -> str:
        return _hash_json({
            "command_type": "policy.evaluate",
            "project_id": command.project_id,
            "planning_run_id": command.planning_run_id,
            "action_id": command.action_id,
            "expected_situation_version": command.expected_situation_version,
            "expected_action_content_hash": command.expected_action_content_hash,
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
            "reason": command.reason,
            "policy_bundle_version": command.policy_bundle_version,
            "target_environment": command.target_environment,
            "runtime_emergency_freeze": command.runtime_emergency_freeze,
        })


def _load_current_candidate(connection, command, prefix):
    row = connection.execute(
        """SELECT ca.*, pr.input_hash AS planner_input_hash
           FROM candidate_actions ca
           JOIN planning_runs pr ON pr.planning_run_id=ca.planning_run_id
           JOIN current_planning_runs cpr ON cpr.planning_run_id=pr.planning_run_id
          WHERE ca.action_id=%s AND ca.planning_run_id=%s AND ca.project_id=%s""",
        (command.action_id, command.planning_run_id, command.project_id),
    ).fetchone()
    if not row:
        raise CommandRejected(prefix + "_ACTION_NOT_FOUND")
    if row["content_hash"] != command.expected_action_content_hash:
        raise CommandRejected(prefix + "_ACTION_HASH_MISMATCH")
    if int(row["situation_version"]) != command.expected_situation_version:
        raise CommandRejected(prefix + "_CONTEXT_STALE")
    return row


def _evaluation_context_id(inputs, target_environment):
    context_hash = "sha256:" + _hash_raw({
        "version": "evaluation-context/1.0",
        "planning_run_id": inputs.planning_run_id,
        "action_id": inputs.action_id,
        "action_content_hash": inputs.action_content_hash,
        "situation_version": inputs.situation_version,
        "analysis_context_hash": inputs.analysis_context_hash,
        "diagnosis_input_hash": inputs.diagnosis_input_hash,
        "target_environment": target_environment,
        "candidate_registry_version": inputs.candidate_registry_version,
    })
    return {
        "evaluation_context_id": "evalctx-" + _hash_raw({"context_hash": context_hash})[:32],
        "context_hash": context_hash,
    }


def _hash_json(value) -> str:
    return "sha256:" + _hash_raw(value)


def _hash_raw(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True).encode("utf-8")
    ).hexdigest()
