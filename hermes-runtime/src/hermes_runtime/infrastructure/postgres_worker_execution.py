from enum import Enum
from typing import Any, Mapping, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from hermes_runtime.application.errors import CommandRejected
from hermes_runtime.application.workers import (
    RecordArtifactCandidate,
    RecordEvidenceCandidate,
    RecordUsageSample,
    StartWorkerRun,
    SubmitExecutionResult,
)
from hermes_runtime.domain.worker_execution import (
    WorkerExecutionRejected,
    hash_payload,
    normalize_artifact_candidate,
    normalize_binding,
    normalize_evidence_candidate,
    normalize_execution_result,
    normalize_frozen_context,
    normalize_usage_sample,
    reject_forbidden_worker_verdict,
)
from hermes_runtime.infrastructure.postgres_scheduler import PostgresSchedulerStore


class WorkerExecutionFaultPoint(str, Enum):
    AFTER_RECEIPT_PLACEHOLDER = "after_receipt_placeholder"
    AFTER_AUTHORITY_VALIDATION = "after_authority_validation"
    AFTER_AGENT_RUN_CREATED = "after_agent_run_created"
    AFTER_REQUEST_RUNNING = "after_request_running"
    AFTER_CANDIDATE_WRITE = "after_candidate_write"
    AFTER_USAGE_ADMISSION = "after_usage_admission"
    AFTER_RESULT_VALIDATED = "after_result_validated"
    AFTER_RESULT_WRITE = "after_result_write"
    AFTER_COMPLETION_CLAIM = "after_completion_claim"
    AFTER_SETTLEMENT = "after_settlement"
    AFTER_RUN_TERMINAL = "after_run_terminal"
    AFTER_REQUEST_TERMINAL = "after_request_terminal"
    AFTER_LEASE_RELEASE = "after_lease_release"
    AFTER_EVENT_BEFORE_OUTBOX = "after_event_before_outbox"
    AFTER_QUARANTINE_WRITE = "after_quarantine_write"
    AFTER_RECEIPT_BEFORE_COMMIT = "after_receipt_before_commit"


class PostgresWorkerExecutionStore(PostgresSchedulerStore):
    def __init__(self, dsn: str) -> None:
        super().__init__(dsn)
        self._worker_fault: Optional[WorkerExecutionFaultPoint] = None

    def fail_worker_once(self, point: str) -> None:
        self._worker_fault = WorkerExecutionFaultPoint(point)

    def reset_for_test(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """TRUNCATE execution_result_settlement_links,
                   execution_result_claim_links, execution_quarantine_records,
                   execution_results, execution_usage_admissions,
                   execution_evidence_candidates, execution_artifact_candidates,
                   execution_worker_assignments RESTART IDENTITY CASCADE"""
            )
        super().reset_for_test()

    def start_run(self, command: StartWorkerRun) -> Mapping[str, Any]:
        binding = normalize_binding(command.binding)
        frozen = normalize_frozen_context(command.frozen_context)
        payload = {
            "command": "execution.start_run",
            "binding": binding,
            "frozen_context": frozen,
            "actor_type": command.actor_type,
            "actor_id": command.actor_id,
            "reason": command.reason,
        }
        payload_hash = hash_payload(payload)
        fault = self._take_fault()
        try:
            with self._connect(row_factory=dict_row) as connection:
                row = connection.execute(
                    """SELECT public.hermes_start_worker_run(
                       %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       %s,%s,%s,%s,%s,%s,%s,%s,%s
                       ) AS result""",
                    (
                        binding["project_id"],
                        binding["execution_request_id"],
                        binding["execution_attempt"],
                        binding["run_id"],
                        binding["lease_id"],
                        binding["lease_version"],
                        binding["fencing_token"],
                        binding["scheduler_id"],
                        binding["scheduler_session_id"],
                        binding["worker_agent_identity"],
                        binding["context_identity"],
                        frozen["worker_template_id"],
                        frozen["worker_template_revision"],
                        frozen["worker_template_content_hash"],
                        frozen["context_bundle_id"],
                        frozen["context_manifest_hash"],
                        frozen["sandbox_profile_id"],
                        frozen["sandbox_profile_hash"],
                        frozen["reservation_id"],
                        binding["observed_request_version"],
                        command.command_id,
                        command.idempotency_key,
                        payload_hash,
                        command.actor_type,
                        command.actor_id,
                        command.reason,
                        fault,
                    ),
                ).fetchone()
                return dict(row["result"])
        except WorkerExecutionRejected as exc:
            raise CommandRejected(str(exc)) from exc
        except psycopg.Error as exc:
            raise CommandRejected(_reason_from_error(exc)) from exc

    def record_artifact_candidate(self, command: RecordArtifactCandidate) -> Mapping[str, Any]:
        binding = normalize_binding(command.binding)
        candidate = normalize_artifact_candidate(command.candidate)
        payload = {
            "command": "execution.record_artifact_candidate",
            "binding": binding,
            "candidate": candidate,
        }
        payload_hash = hash_payload(payload)
        return self._call_admission(
            """SELECT public.hermes_record_execution_artifact_candidate(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                binding["project_id"], binding["execution_request_id"],
                binding["execution_attempt"], binding["run_id"], binding["lease_id"],
                binding["lease_version"], binding["fencing_token"],
                binding["worker_agent_identity"], binding["context_identity"],
                binding["observed_request_version"], candidate["candidate_id"],
                candidate["artifact_kind"], candidate["content_hash"],
                candidate["storage_ref"], candidate["size_bytes"],
                candidate["media_type"], candidate["schema_ref"], Jsonb(payload),
                command.command_id, command.idempotency_key, payload_hash,
                command.actor_type, command.actor_id, self._take_fault(),
            ),
        )

    def record_evidence_candidate(self, command: RecordEvidenceCandidate) -> Mapping[str, Any]:
        binding = normalize_binding(command.binding)
        candidate = normalize_evidence_candidate(command.candidate)
        payload = {
            "command": "execution.record_evidence_candidate",
            "binding": binding,
            "candidate": candidate,
        }
        payload_hash = hash_payload(payload)
        return self._call_admission(
            """SELECT public.hermes_record_execution_evidence_candidate(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::timestamptz,
               %s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                binding["project_id"], binding["execution_request_id"],
                binding["execution_attempt"], binding["run_id"], binding["lease_id"],
                binding["lease_version"], binding["fencing_token"],
                binding["worker_agent_identity"], binding["context_identity"],
                binding["observed_request_version"], candidate["candidate_id"],
                candidate["evidence_type"], candidate["schema_ref"],
                candidate["source_ref"], candidate["source_hash"],
                candidate["observed_at"], Jsonb(payload), command.command_id,
                command.idempotency_key, payload_hash, command.actor_type,
                command.actor_id, self._take_fault(),
            ),
        )

    def record_usage_sample(self, command: RecordUsageSample) -> Mapping[str, Any]:
        binding = normalize_binding(command.binding)
        sample = normalize_usage_sample(command.sample)
        payload = {
            "command": "execution.record_usage_sample",
            "binding": binding,
            "sample": sample,
        }
        payload_hash = hash_payload(payload)
        return self._call_admission(
            """SELECT public.hermes_record_execution_usage_sample(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
               %s::timestamptz,%s::timestamptz,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                binding["project_id"], binding["execution_request_id"],
                binding["execution_attempt"], binding["run_id"], binding["lease_id"],
                binding["lease_version"], binding["fencing_token"],
                binding["worker_agent_identity"], binding["context_identity"],
                binding["observed_request_version"], sample["usage_id"],
                sample["sample_id"], sample["reservation_id"], sample["currency"] or None,
                Jsonb(sample["amounts"]), sample["interval_start"], sample["interval_end"],
                Jsonb(payload), command.command_id, command.idempotency_key,
                payload_hash, command.actor_type, command.actor_id, self._take_fault(),
            ),
        )

    def submit_result(self, command: SubmitExecutionResult) -> Mapping[str, Any]:
        binding = normalize_binding(command.binding)
        result = normalize_execution_result(command.result)
        payload = {
            "command": "execution.submit_result",
            "binding": binding,
            "result": result,
            "expected_account_version": int(command.expected_account_version),
        }
        reject_forbidden_worker_verdict(payload)
        payload_hash = hash_payload(payload)
        return self._call_admission(
            """SELECT public.hermes_submit_execution_result(
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
               %s::timestamptz,%s::timestamptz,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
               ) AS result""",
            (
                binding["project_id"], binding["execution_request_id"],
                binding["execution_attempt"], binding["run_id"], binding["lease_id"],
                binding["lease_version"], binding["fencing_token"],
                binding["worker_agent_identity"], binding["context_identity"],
                binding["observed_request_version"], result["result_id"],
                result["outcome"], result["error_classification"],
                Jsonb(result["artifact_candidate_refs"]),
                Jsonb(result["evidence_candidate_refs"]),
                Jsonb(result["usage_sample_refs"]), result["started_at"],
                result["finished_at"], result["adapter_identity"],
                result["adapter_version"], Jsonb(result["external_side_effect_refs"]),
                result["primary_artifact_candidate_id"],
                result["completion_claim_id"],
                int(command.expected_account_version), Jsonb(payload),
                command.command_id, command.idempotency_key, payload_hash,
                command.actor_type, command.actor_id, self._take_fault(),
            ),
        )

    def _call_admission(self, sql: str, args: tuple) -> Mapping[str, Any]:
        try:
            with self._connect(row_factory=dict_row) as connection:
                row = connection.execute(sql, args).fetchone()
                result = dict(row["result"])
        except WorkerExecutionRejected as exc:
            raise CommandRejected(str(exc)) from exc
        except psycopg.Error as exc:
            raise CommandRejected(_reason_from_error(exc)) from exc
        if result.get("quarantined"):
            raise CommandRejected(str(result.get("result_code")), str(result))
        return result

    def _take_fault(self) -> Optional[str]:
        fault = self._worker_fault
        self._worker_fault = None
        return fault.value if fault else None


def _reason_from_error(exc: psycopg.Error) -> str:
    text = str(exc)
    for reason in (
        "EXECUTION_REQUEST_NOT_RUNNING",
        "EXECUTION_REQUEST_NOT_LEASED",
        "AGENT_RUN_NOT_FOUND",
        "AGENT_RUN_NOT_ACTIVE",
        "AGENT_RUN_SCOPE_MISMATCH",
        "AGENT_RUN_ALREADY_ACTIVE",
        "WORKER_IDENTITY_MISMATCH",
        "CONTEXT_IDENTITY_MISMATCH",
        "LEASE_NOT_CURRENT",
        "LEASE_EXPIRED",
        "LEASE_OWNER_MISMATCH",
        "LEASE_VERSION_CONFLICT",
        "FENCING_TOKEN_STALE",
        "EXECUTION_ATTEMPT_STALE",
        "EXECUTION_LOCK_OWNERSHIP_LOST",
        "EXPECTED_VERSION_CONFLICT",
        "IDEMPOTENCY_PAYLOAD_CONFLICT",
        "WORKER_VERDICT_FORBIDDEN",
        "EXECUTION_RESULT_OUTCOME_INVALID",
        "EXECUTION_RESULT_TIME_INVALID",
        "EXECUTION_RESULT_REF_SCOPE_MISMATCH",
        "EXECUTION_RESULT_ALREADY_RECORDED",
        "COMPLETION_CLAIM_ARTIFACT_REQUIRED",
        "COMPLETION_CLAIM_NOT_ELIGIBLE",
        "ARTIFACT_REF_UNSAFE",
        "SECRET_VALUE_FORBIDDEN",
        "RESOURCE_AMOUNT_INVALID",
        "RESOURCE_DIMENSION_UNKNOWN",
        "RESOURCE_CURRENCY_MISMATCH",
        "RESOURCE_RESERVATION_NOT_ACTIVE",
        "RESOURCE_ACCOUNT_VERSION_CONFLICT",
        "RESOURCE_SETTLEMENT_USAGE_CONFLICT",
        "RESOURCE_SETTLEMENT_ALREADY_APPLIED",
    ):
        if reason in text:
            return reason
    if "injected worker execution crash:" in text:
        return text.splitlines()[0]
    return text.splitlines()[0] if text else exc.__class__.__name__
