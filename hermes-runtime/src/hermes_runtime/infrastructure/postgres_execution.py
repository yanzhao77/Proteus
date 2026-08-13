import json
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.executions import PrepareExecutionRequest
from hermes_runtime.domain.execution import (
    ExecutionAdmissionSnapshot,
    ExecutionRejected,
    PreparedExecutionRequest,
    VersionedRef,
    prepare_execution_request_snapshot,
)
from hermes_runtime.infrastructure.postgres import PostgresRuntimeStore


class ExecutionFaultPoint(str, Enum):
    AFTER_RECEIPT_PLACEHOLDER = "after_receipt_placeholder"
    AFTER_AUTHORITY_VALIDATION = "after_authority_validation"
    AFTER_RESERVATION_BINDING = "after_reservation_binding"
    AFTER_REQUEST_WRITE = "after_request_write"
    AFTER_QUEUE_ITEM = "after_queue_item"
    AFTER_EVENT_BEFORE_OUTBOX = "after_event_before_outbox"
    AFTER_OUTBOX_BEFORE_RECEIPT = "after_outbox_before_receipt"
    AFTER_RECEIPT_BEFORE_COMMIT = "after_receipt_before_commit"


class PostgresExecutionStore(PostgresRuntimeStore):
    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self._fault: Optional[ExecutionFaultPoint] = None

    def fail_execution_once(self, point: ExecutionFaultPoint) -> None:
        self._fault = point

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """TRUNCATE execution_preparation_rejections,
                   execution_queue_items, execution_reservation_bindings,
                   execution_requests, sandbox_profiles, context_bundle_items,
                   context_bundles, capability_match_records,
                   worker_template_availability, worker_template_capabilities,
                   worker_template_revisions, capability_schemas,
                   decision_reservation_mappings, selected_action_refs,
                   action_score_dimensions, action_scores,
                   decision_candidate_dispositions, decision_records,
                   selection_heads, current_risk_assessments, risk_mitigations,
                   risk_factors, risk_assessments, current_policy_decisions,
                   policy_constraints, policy_decision_rules, policy_decisions,
                   policy_evaluation_contexts, current_planning_runs,
                   candidate_action_resource_estimates,
                   candidate_action_expected_outputs, candidate_action_preconditions,
                   candidate_action_capabilities, candidate_action_targets,
                   candidate_actions, planning_runs, current_diagnoses,
                   diagnosis_evidence_requests, diagnosis_hypotheses,
                   diagnosis_evidence, diagnosis_findings, diagnoses,
                   situation_versions, situations, analysis_contexts,
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
                   resource_balances, resource_accounts, project_budget_facts,
                   project_policy_decision_facts, project_evidence_facts,
                   project_gate_decision_facts, project_transition_records,
                   feedback_records, task_dependencies, work_graph_edges,
                   project_graph_versions, verification_check_results,
                   verification_evidence, verification_results, evidence,
                   completion_claims, artifacts, verification_plan_checks,
                   verification_plans, agent_runs, verifier_identities,
                   tasks, projects RESTART IDENTITY CASCADE"""
            )

    def prepare_execution_request(self, command: PrepareExecutionRequest) -> Mapping[str, Any]:
        try:
            prepared = _prepared_from_command(command)
            request_hash = prepared.payload_hash
            fault = self._fault
            self._fault = None
            with self._connect(row_factory=dict_row) as connection:
                existing = self._begin_command(connection, command, request_hash)
                if existing is not None:
                    return existing
                result = connection.execute(
                    """SELECT public.hermes_prepare_execution_request(
                       %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                       ) AS result""",
                    (
                        prepared.execution_request_id,
                        prepared.queue_item_id,
                        Jsonb(prepared.request_snapshot),
                        command.project_id,
                        command.task_id,
                        command.expected_project_version,
                        command.expected_task_version,
                        command.command_id,
                        command.idempotency_key,
                        request_hash,
                        command.actor_type,
                        command.actor_id,
                        command.reason,
                        fault.value if fault else None,
                    ),
                ).fetchone()["result"]
                return dict(result)
        except ExecutionRejected as exc:
            request_hash = _fallback_request_hash(command)
            self._persist_rejection(command, request_hash, str(exc), "")
            raise CommandRejected(str(exc))
        except CommandRejected as exc:
            self._persist_rejection(command, request_hash, exc.code, exc.detail)
            raise
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary
            if code.startswith("INJECTED_EXECUTION_CRASH_"):
                raise RuntimeError("injected execution crash: " + code)
            rejected = CommandRejected(code)
            self._persist_rejection(command, request_hash, rejected.code, rejected.detail)
            raise rejected
        except psycopg.errors.UniqueViolation as exc:
            self._persist_rejection(
                command,
                request_hash,
                "EXEC_ADMISSION_RESERVATION_ALREADY_BOUND",
                str(exc).splitlines()[0],
            )
            raise CommandRejected("EXEC_ADMISSION_RESERVATION_ALREADY_BOUND")

    def list_pending_queue(self, project_id: str, limit: int = 50) -> Tuple[Mapping[str, Any], ...]:
        bounded = max(0, min(int(limit), 500))
        with self._connect(row_factory=dict_row) as connection:
            rows = connection.execute(
                """SELECT q.queue_item_id, q.execution_request_id, q.project_id,
                          q.task_id, q.priority, q.available_at, q.enqueued_at,
                          q.stable_order_key, q.request_version, q.payload_hash,
                          q.queue_state, q.event_id
                     FROM public.execution_queue_items q
                     JOIN public.execution_requests r
                       ON r.execution_request_id = q.execution_request_id
                    WHERE q.project_id=%s AND q.queue_state='PENDING'
                      AND r.request_state='QUEUED'
                    ORDER BY q.priority DESC, q.available_at ASC,
                             q.enqueued_at ASC, q.stable_order_key ASC
                    LIMIT %s""",
                (project_id, bounded),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def _begin_command(self, connection, command: PrepareExecutionRequest, request_hash: str):
        inserted = connection.execute(
            """INSERT INTO command_receipts(
               command_id, project_id, command_type, idempotency_key,
               request_hash, status, result)
               VALUES (%s,%s,'execution.prepare_request',%s,%s,'PROCESSING','{}'::jsonb)
               ON CONFLICT DO NOTHING RETURNING command_id""",
            (command.command_id, command.project_id, command.idempotency_key, request_hash),
        ).fetchone()
        if inserted:
            return None
        row = connection.execute(
            """SELECT request_hash,status,result FROM command_receipts
               WHERE project_id=%s AND command_type='execution.prepare_request'
                 AND idempotency_key=%s FOR UPDATE""",
            (command.project_id, command.idempotency_key),
        ).fetchone()
        if not row or row["request_hash"] != request_hash:
            raise CommandRejected("EXEC_ADMISSION_IDEMPOTENCY_CONFLICT")
        if row["status"] == "APPLIED":
            response = row["result"].get("response", row["result"])
            response = dict(response)
            response["deduplicated"] = True
            return response
        if row["status"] == "REJECTED":
            code = row["result"].get("result_code", "EXEC_ADMISSION_INCOMPLETE")
            raise CommandRejected(code)
        raise CommandRejected("COMMAND_IN_PROGRESS")

    def _persist_rejection(
        self,
        command: PrepareExecutionRequest,
        request_hash: str,
        code: str,
        detail: str,
    ) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO command_receipts(
                       command_id, project_id, command_type, idempotency_key,
                       request_hash, status, result)
                       VALUES (%s,%s,'execution.prepare_request',%s,%s,
                               'PROCESSING','{}'::jsonb)
                       ON CONFLICT DO NOTHING""",
                    (
                        command.command_id,
                        command.project_id,
                        command.idempotency_key,
                        request_hash,
                    ),
                )
                connection.execute(
                    """SELECT public.hermes_execution_reject_command(
                       %s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        command.project_id,
                        command.command_id,
                        command.idempotency_key,
                        request_hash,
                        code,
                        _safe_detail(detail),
                        command.actor_type,
                        command.actor_id,
                    ),
                )
        except Exception:
            pass


def _prepared_from_command(command: PrepareExecutionRequest) -> PreparedExecutionRequest:
    snapshot = ExecutionAdmissionSnapshot(
        project_id=command.project_id,
        task_id=command.task_id,
        project_version=command.expected_project_version,
        task_version=command.expected_task_version,
        decision=VersionedRef(command.decision_id, command.decision_version, command.decision_hash),
        action=VersionedRef(command.action_id, command.action_version, command.action_content_hash),
        action_type=command.action_type,
        action_requirements_hash=command.action_requirements_hash,
        policy=VersionedRef(command.policy_decision_id, command.policy_version, command.policy_hash),
        risk=VersionedRef(command.risk_assessment_id, command.risk_version, command.risk_hash),
        mandatory_mitigations_hash=command.mandatory_mitigations_hash,
        resource_reservation=VersionedRef(
            command.reservation_id,
            command.reservation_version,
            command.reservation_hash,
        ),
        capability_match=VersionedRef(
            command.capability_match_id,
            command.capability_match_version,
            command.capability_requirements_hash,
        ),
        worker_template_id=command.worker_template_id,
        worker_template_revision=command.worker_template_revision,
        worker_template_content_hash=command.worker_template_content_hash,
        worker_template_availability_version=command.worker_template_availability_version,
        context_bundle_id=command.context_bundle_id,
        context_manifest_hash=command.context_manifest_hash,
        sandbox_profile_id=command.sandbox_profile_id,
        sandbox_profile_hash=command.sandbox_profile_hash,
        sandbox_compiler_version=command.sandbox_compiler_version,
        sandbox_compiler_target=command.sandbox_compiler_target,
        verification_plan=VersionedRef(
            command.verification_plan_id,
            command.verification_plan_version,
            command.verification_plan_hash,
        ),
        input_artifacts=command.input_artifacts,
        lock_intents=command.lock_intents,
        priority=command.priority,
    )
    return prepare_execution_request_snapshot(snapshot, idempotency_key=command.idempotency_key)


def _fallback_request_hash(command: PrepareExecutionRequest) -> str:
    text = json.dumps(
        {
            "command_id": command.command_id,
            "idempotency_key": command.idempotency_key,
            "project_id": command.project_id,
            "task_id": command.task_id,
            "action_id": command.action_id,
            "action_type": command.action_type,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    import hashlib
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_detail(value: str) -> str:
    text = str(value or "")
    for needle in ("password=", "private key", "sk-"):
        if needle in text.lower():
            return ""
    try:
        json.dumps(text)
    except TypeError:
        return ""
    return text[:256]
