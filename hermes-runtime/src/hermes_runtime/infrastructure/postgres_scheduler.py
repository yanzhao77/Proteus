from enum import Enum
from typing import Any, Mapping, Optional

import psycopg
from psycopg.rows import dict_row

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.scheduling import (
    AcquireExecutionLease,
    RegisterScheduler,
    RelinquishExecutionLease,
    RenewExecutionLease,
)
from hermes_runtime.domain.scheduler import hash_command_payload
from hermes_runtime.infrastructure.postgres import PostgresRuntimeStore


class SchedulerFaultPoint(str, Enum):
    AFTER_RECEIPT_PLACEHOLDER = "after_receipt_placeholder"
    AFTER_AUTHORITY_VALIDATION = "after_authority_validation"
    AFTER_QUEUE_CANDIDATE_LOCKED = "after_queue_candidate_locked"
    AFTER_LOCK_SCOPES_PREPARED = "after_lock_scopes_prepared"
    AFTER_LOCKS_WRITTEN = "after_locks_written"
    AFTER_FENCING_TOKEN_ALLOCATED = "after_fencing_token_allocated"
    AFTER_LEASE_WRITTEN = "after_lease_written"
    AFTER_REQUEST_LEASED = "after_request_leased"
    AFTER_QUEUE_CLAIMED = "after_queue_claimed"
    AFTER_EVENT_BEFORE_OUTBOX = "after_event_before_outbox"
    AFTER_OUTBOX_BEFORE_RECEIPT = "after_outbox_before_receipt"
    AFTER_RECEIPT_BEFORE_COMMIT = "after_receipt_before_commit"
    AFTER_EXPIRY_BEFORE_NEW_LEASE = "after_expiry_before_new_lease"
    AFTER_RENEW_VALIDATED = "after_renew_validated"
    AFTER_RENEW_EXPIRY_UPDATE = "after_renew_expiry_update"
    AFTER_RELINQUISH_VALIDATED = "after_relinquish_validated"
    AFTER_RELINQUISH_BEFORE_REQUEUE = "after_relinquish_before_requeue"


class PostgresSchedulerStore(PostgresRuntimeStore):
    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self._fault: Optional[SchedulerFaultPoint] = None

    def fail_scheduler_once(self, point: SchedulerFaultPoint) -> None:
        self._fault = point

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """TRUNCATE execution_scheduler_rejections,
                   execution_lock_ownerships, execution_lease_state_history,
                   execution_leases, execution_fencing_counters,
                   execution_queue_current_states, execution_request_current_states,
                   scheduler_instances,
                   execution_preparation_rejections,
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

    def register_scheduler(self, command: RegisterScheduler) -> Mapping[str, Any]:
        payload_hash = hash_command_payload(command.__dict__)
        try:
            with self._connect(row_factory=dict_row) as connection:
                row = connection.execute(
                    """SELECT public.hermes_scheduler_register(
                       %s,%s,%s,%s,%s,%s,%s,%s,%s
                       ) AS result""",
                    (
                        command.project_id,
                        command.scheduler_id,
                        command.scheduler_session_id,
                        command.command_id,
                        command.idempotency_key,
                        payload_hash,
                        command.actor_type,
                        command.actor_id,
                        command.reason,
                    ),
                ).fetchone()
                return dict(row["result"])
        except psycopg.Error as exc:
            raise CommandRejected(_reason_from_error(exc)) from exc

    def acquire_lease(self, command: AcquireExecutionLease) -> Mapping[str, Any]:
        payload_hash = hash_command_payload(command.__dict__)
        fault = self._fault
        self._fault = None
        try:
            with self._connect(row_factory=dict_row) as connection:
                row = connection.execute(
                    """SELECT public.hermes_scheduler_acquire_lease(
                       %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                       ) AS result""",
                    (
                        command.project_id,
                        command.scheduler_id,
                        command.scheduler_session_id,
                        command.profile_id,
                        command.profile_version,
                        command.command_id,
                        command.idempotency_key,
                        payload_hash,
                        command.actor_type,
                        command.actor_id,
                        command.reason,
                        fault.value if fault else None,
                    ),
                ).fetchone()
                result = dict(row["result"])
                _raise_if_rejected(result)
                return result
        except psycopg.Error as exc:
            raise CommandRejected(_reason_from_error(exc)) from exc

    def renew_lease(self, command: RenewExecutionLease) -> Mapping[str, Any]:
        payload_hash = hash_command_payload(command.__dict__)
        fault = self._fault
        self._fault = None
        try:
            with self._connect(row_factory=dict_row) as connection:
                row = connection.execute(
                    """SELECT public.hermes_scheduler_renew_lease(
                       %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                       ) AS result""",
                    (
                        command.project_id,
                        command.execution_request_id,
                        command.lease_id,
                        command.scheduler_id,
                        command.scheduler_session_id,
                        command.fencing_token,
                        command.expected_lease_version,
                        command.command_id,
                        command.idempotency_key,
                        payload_hash,
                        command.actor_type,
                        command.actor_id,
                        command.reason,
                        fault.value if fault else None,
                    ),
                ).fetchone()
                result = dict(row["result"])
                _raise_if_rejected(result)
                return result
        except psycopg.Error as exc:
            raise CommandRejected(_reason_from_error(exc)) from exc

    def relinquish_lease(self, command: RelinquishExecutionLease) -> Mapping[str, Any]:
        payload_hash = hash_command_payload(command.__dict__)
        fault = self._fault
        self._fault = None
        try:
            with self._connect(row_factory=dict_row) as connection:
                row = connection.execute(
                    """SELECT public.hermes_scheduler_relinquish_lease(
                       %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                       ) AS result""",
                    (
                        command.project_id,
                        command.execution_request_id,
                        command.lease_id,
                        command.scheduler_id,
                        command.scheduler_session_id,
                        command.fencing_token,
                        command.expected_lease_version,
                        command.command_id,
                        command.idempotency_key,
                        payload_hash,
                        command.actor_type,
                        command.actor_id,
                        command.reason,
                        fault.value if fault else None,
                    ),
                ).fetchone()
                result = dict(row["result"])
                _raise_if_rejected(result)
                return result
        except psycopg.Error as exc:
            raise CommandRejected(_reason_from_error(exc)) from exc

    def validate_current_lease(
        self,
        *,
        execution_request_id: str,
        lease_id: str,
        scheduler_id: str,
        scheduler_session_id: str,
        fencing_token: int,
        observed_request_version: Optional[int] = None,
    ) -> Mapping[str, Any]:
        with self._connect(row_factory=dict_row) as connection:
            row = connection.execute(
                """SELECT public.hermes_validate_current_lease(
                   %s,%s,%s,%s,%s,%s
                   ) AS result""",
                (
                    execution_request_id,
                    lease_id,
                    scheduler_id,
                    scheduler_session_id,
                    fencing_token,
                    observed_request_version,
                ),
            ).fetchone()
            return dict(row["result"])


def _raise_if_rejected(result: Mapping[str, Any]) -> None:
    if result.get("rejected"):
        raise CommandRejected(str(result.get("result_code", "COMMAND_REJECTED")))


def _reason_from_error(exc: psycopg.Error) -> str:
    text = str(exc)
    for reason in (
        "SCHEDULER_IDEMPOTENCY_CONFLICT",
        "NO_ELIGIBLE_EXECUTION",
        "SCHEDULER_NOT_ADMITTED",
        "LEASE_PROFILE_INVALID",
        "LEASE_NOT_FOUND",
        "LEASE_NOT_ACTIVE",
        "LEASE_EXPIRED",
        "LEASE_OWNER_MISMATCH",
        "FENCING_TOKEN_STALE",
        "LEASE_VERSION_CONFLICT",
        "LEASE_RENEWAL_LIMIT_EXCEEDED",
        "LEASE_LOCK_OWNERSHIP_LOST",
        "EXEC_LEASE_CONTENTION",
        "EXECUTION_LOCK_CONFLICT",
        "FENCING_TOKEN_OVERFLOW",
        "SECRET_VALUE_FORBIDDEN",
    ):
        if reason in text:
            return reason
    return text.splitlines()[0] if text else exc.__class__.__name__
