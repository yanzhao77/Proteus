import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

from hermes_runtime.domain.resource_accounting import (
    ResourceAccountingRejected,
    validate_amounts,
    validate_currency,
)


WORKER_EXECUTION_HASH_VERSION = "worker-execution-payload-hash/1.0"
MAX_INT64 = 9_223_372_036_854_775_807

WORKER_REJECTION_CODES = (
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
)


class WorkerExecutionRejected(ValueError):
    pass


class ExecutionOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED_TRANSIENT = "FAILED_TRANSIENT"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    CANCELLED = "CANCELLED"


class AgentRunLifecycle(str, Enum):
    ADMITTED = "ADMITTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class WorkerLeaseBinding:
    project_id: str
    execution_request_id: str
    execution_attempt: int
    run_id: str
    lease_id: str
    lease_version: int
    fencing_token: int
    scheduler_id: str
    scheduler_session_id: str
    worker_agent_identity: str
    context_identity: str
    observed_request_version: int


@dataclass(frozen=True)
class WorkerFrozenContext:
    worker_template_id: str
    worker_template_revision: int
    worker_template_content_hash: str
    context_bundle_id: str
    context_manifest_hash: str
    sandbox_profile_id: str
    sandbox_profile_hash: str
    reservation_id: str


@dataclass(frozen=True)
class ArtifactCandidateSubmission:
    candidate_id: str
    artifact_kind: str
    content_hash: str
    storage_ref: str
    size_bytes: int = 0
    media_type: str = ""
    schema_ref: str = ""


@dataclass(frozen=True)
class EvidenceCandidateSubmission:
    candidate_id: str
    evidence_type: str
    source_ref: str
    source_hash: str
    observed_at: str
    schema_ref: str = ""


@dataclass(frozen=True)
class UsageSampleSubmission:
    usage_id: str
    sample_id: str
    reservation_id: str
    amounts: Mapping[str, int]
    currency: str = ""
    interval_start: Optional[str] = None
    interval_end: Optional[str] = None


@dataclass(frozen=True)
class ExecutionResultSubmission:
    result_id: str
    outcome: ExecutionOutcome
    error_classification: str
    artifact_candidate_refs: Tuple[str, ...]
    evidence_candidate_refs: Tuple[str, ...]
    usage_sample_refs: Tuple[str, ...]
    started_at: str
    finished_at: str
    adapter_identity: str
    adapter_version: str
    external_side_effect_refs: Tuple[str, ...] = ()
    primary_artifact_candidate_id: Optional[str] = None
    completion_claim_id: Optional[str] = None


def normalize_binding(binding: WorkerLeaseBinding) -> Mapping[str, Any]:
    return {
        "project_id": _require_id(binding.project_id, "AGENT_RUN_SCOPE_MISMATCH"),
        "execution_request_id": _require_id(binding.execution_request_id, "AGENT_RUN_SCOPE_MISMATCH"),
        "execution_attempt": _bounded_positive(binding.execution_attempt, "EXECUTION_ATTEMPT_STALE"),
        "run_id": _require_id(binding.run_id, "AGENT_RUN_SCOPE_MISMATCH"),
        "lease_id": _require_id(binding.lease_id, "LEASE_NOT_CURRENT"),
        "lease_version": _bounded_positive(binding.lease_version, "LEASE_VERSION_CONFLICT"),
        "fencing_token": _bounded_positive(binding.fencing_token, "FENCING_TOKEN_STALE"),
        "scheduler_id": _require_id(binding.scheduler_id, "LEASE_OWNER_MISMATCH"),
        "scheduler_session_id": _require_id(binding.scheduler_session_id, "LEASE_OWNER_MISMATCH"),
        "worker_agent_identity": _require_id(binding.worker_agent_identity, "WORKER_IDENTITY_MISMATCH"),
        "context_identity": _require_id(binding.context_identity, "CONTEXT_IDENTITY_MISMATCH"),
        "observed_request_version": _bounded_positive(binding.observed_request_version, "EXPECTED_VERSION_CONFLICT"),
    }


def normalize_frozen_context(context: WorkerFrozenContext) -> Mapping[str, Any]:
    return {
        "worker_template_id": _require_id(context.worker_template_id, "AGENT_RUN_SCOPE_MISMATCH"),
        "worker_template_revision": _bounded_positive(context.worker_template_revision, "AGENT_RUN_SCOPE_MISMATCH"),
        "worker_template_content_hash": _require_hash(
            context.worker_template_content_hash, "AGENT_RUN_SCOPE_MISMATCH"
        ),
        "context_bundle_id": _require_id(context.context_bundle_id, "AGENT_RUN_SCOPE_MISMATCH"),
        "context_manifest_hash": _require_hash(context.context_manifest_hash, "AGENT_RUN_SCOPE_MISMATCH"),
        "sandbox_profile_id": _require_id(context.sandbox_profile_id, "AGENT_RUN_SCOPE_MISMATCH"),
        "sandbox_profile_hash": _require_hash(context.sandbox_profile_hash, "AGENT_RUN_SCOPE_MISMATCH"),
        "reservation_id": _require_id(context.reservation_id, "RESOURCE_RESERVATION_NOT_ACTIVE"),
    }


def normalize_artifact_candidate(candidate: ArtifactCandidateSubmission) -> Mapping[str, Any]:
    storage_ref = _require_ref(candidate.storage_ref, "ARTIFACT_REF_UNSAFE")
    if re.match(r"(?i)^(file:|/|\\.\\.)", storage_ref):
        raise WorkerExecutionRejected("ARTIFACT_REF_UNSAFE")
    return {
        "candidate_id": _require_id(candidate.candidate_id, "AGENT_RUN_SCOPE_MISMATCH"),
        "artifact_kind": _require_atom(candidate.artifact_kind, "EXECUTION_RESULT_REF_SCOPE_MISMATCH"),
        "content_hash": _require_hash(candidate.content_hash, "EXECUTION_RESULT_REF_SCOPE_MISMATCH"),
        "storage_ref": storage_ref,
        "size_bytes": _bounded_nonnegative(candidate.size_bytes, "RESOURCE_AMOUNT_INVALID"),
        "media_type": str(candidate.media_type or ""),
        "schema_ref": str(candidate.schema_ref or ""),
    }


def normalize_evidence_candidate(candidate: EvidenceCandidateSubmission) -> Mapping[str, Any]:
    return {
        "candidate_id": _require_id(candidate.candidate_id, "AGENT_RUN_SCOPE_MISMATCH"),
        "evidence_type": _require_atom(candidate.evidence_type, "EXECUTION_RESULT_REF_SCOPE_MISMATCH"),
        "schema_ref": str(candidate.schema_ref or ""),
        "source_ref": _require_ref(candidate.source_ref, "EXECUTION_RESULT_REF_SCOPE_MISMATCH"),
        "source_hash": _require_hash(candidate.source_hash, "EXECUTION_RESULT_REF_SCOPE_MISMATCH"),
        "observed_at": _require_ref(candidate.observed_at, "EXECUTION_RESULT_TIME_INVALID"),
    }


def normalize_usage_sample(sample: UsageSampleSubmission) -> Mapping[str, Any]:
    try:
        validate_amounts(sample.amounts)
    except ResourceAccountingRejected as exc:
        raise WorkerExecutionRejected(str(exc)) from exc
    currency = sample.currency or ""
    try:
        validate_currency(sample.amounts, currency or None)
    except ResourceAccountingRejected as exc:
        raise WorkerExecutionRejected(str(exc)) from exc
    return {
        "usage_id": _require_id(sample.usage_id, "AGENT_RUN_SCOPE_MISMATCH"),
        "sample_id": _require_id(sample.sample_id, "IDEMPOTENCY_PAYLOAD_CONFLICT"),
        "reservation_id": _require_id(sample.reservation_id, "RESOURCE_RESERVATION_NOT_ACTIVE"),
        "amounts": {key: int(sample.amounts[key]) for key in sorted(sample.amounts)},
        "currency": currency,
        "interval_start": sample.interval_start,
        "interval_end": sample.interval_end,
    }


def normalize_execution_result(result: ExecutionResultSubmission) -> Mapping[str, Any]:
    outcome = result.outcome if isinstance(result.outcome, ExecutionOutcome) else ExecutionOutcome(result.outcome)
    payload = {
        "result_id": _require_id(result.result_id, "AGENT_RUN_SCOPE_MISMATCH"),
        "outcome": outcome.value,
        "error_classification": str(result.error_classification or ""),
        "artifact_candidate_refs": sorted(_require_id(item, "EXECUTION_RESULT_REF_SCOPE_MISMATCH")
                                          for item in result.artifact_candidate_refs),
        "evidence_candidate_refs": sorted(_require_id(item, "EXECUTION_RESULT_REF_SCOPE_MISMATCH")
                                          for item in result.evidence_candidate_refs),
        "usage_sample_refs": sorted(_require_id(item, "EXECUTION_RESULT_REF_SCOPE_MISMATCH")
                                    for item in result.usage_sample_refs),
        "started_at": _require_ref(result.started_at, "EXECUTION_RESULT_TIME_INVALID"),
        "finished_at": _require_ref(result.finished_at, "EXECUTION_RESULT_TIME_INVALID"),
        "adapter_identity": _require_id(result.adapter_identity, "AGENT_RUN_SCOPE_MISMATCH"),
        "adapter_version": _require_ref(result.adapter_version, "AGENT_RUN_SCOPE_MISMATCH"),
        "external_side_effect_refs": sorted(str(item) for item in result.external_side_effect_refs),
        "primary_artifact_candidate_id": result.primary_artifact_candidate_id,
        "completion_claim_id": result.completion_claim_id,
    }
    if outcome is ExecutionOutcome.SUCCEEDED and (
        not result.primary_artifact_candidate_id or not result.completion_claim_id
    ):
        raise WorkerExecutionRejected("COMPLETION_CLAIM_ARTIFACT_REQUIRED")
    if outcome is not ExecutionOutcome.SUCCEEDED and result.completion_claim_id:
        raise WorkerExecutionRejected("COMPLETION_CLAIM_NOT_ELIGIBLE")
    return payload


def reject_forbidden_worker_verdict(payload: Mapping[str, Any]) -> None:
    forbidden = {"verdict", "task_status", "mark_passed", "mark_failed", "new_state"}
    if _contains_any_key(payload, forbidden):
        raise WorkerExecutionRejected("WORKER_VERDICT_FORBIDDEN")


def hash_payload(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload["payload_hash_version"] = WORKER_EXECUTION_HASH_VERSION
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _contains_any_key(value: Any, forbidden: set) -> bool:
    if isinstance(value, Mapping):
        return any(key in forbidden or _contains_any_key(child, forbidden)
                   for key, child in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_any_key(item, forbidden) for item in value)
    return False


def _bounded_positive(value: int, reason: str) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError):
        raise WorkerExecutionRejected(reason)
    if integer < 1 or integer > MAX_INT64:
        raise WorkerExecutionRejected(reason)
    return integer


def _bounded_nonnegative(value: int, reason: str) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError):
        raise WorkerExecutionRejected(reason)
    if integer < 0 or integer > MAX_INT64:
        raise WorkerExecutionRejected(reason)
    return integer


def _require_id(value: str, reason: str) -> str:
    text = str(value or "").strip()
    if not text or "*" in text or len(text) > 200:
        raise WorkerExecutionRejected(reason)
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9:/._-]{0,199}$", text):
        raise WorkerExecutionRejected(reason)
    return text


def _require_atom(value: str, reason: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 120:
        raise WorkerExecutionRejected(reason)
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9:._/-]{0,119}$", text):
        raise WorkerExecutionRejected(reason)
    return text


def _require_ref(value: str, reason: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 512:
        raise WorkerExecutionRejected(reason)
    return text


def _require_hash(value: str, reason: str) -> str:
    text = str(value or "").strip()
    if not text.startswith("sha256:") or len(text) <= len("sha256:"):
        raise WorkerExecutionRejected(reason)
    return text


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
