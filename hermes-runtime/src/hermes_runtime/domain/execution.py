import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Tuple


EXECUTION_PREPARATION_SCHEMA_VERSION = "execution-preparation/1.0"
EXECUTION_REQUEST_SCHEMA_VERSION = "execution-request/1.0"
EXECUTION_QUEUE_SCHEMA_VERSION = "execution-queue/1.0"
LOCK_SCOPE_NORMALIZER_VERSION = "lock-scope-normalizer/1.0"
REQUEST_PAYLOAD_HASH_VERSION = "execution-request-payload-hash/1.0"

MIN_QUEUE_PRIORITY = -1000
MAX_QUEUE_PRIORITY = 1000

WORKER_EXECUTABLE_ACTION_TYPES = (
    "diagnose", "run_deeper_test", "deeper_test", "repair", "retry",
)
CONTROL_PLANE_ACTION_TYPES = (
    "pause", "resume", "cancel", "transition_project", "recompute_readiness",
)
HUMAN_GATE_ACTION_TYPES = (
    "human_gate", "request_human", "request_resource", "request_approval",
)
RECOVERY_ACTION_TYPES = (
    "recover", "reconcile", "release_orphan", "settlement_repair",
)

LOCK_KIND_ORDER = {
    "repository": 0,
    "workspace": 1,
    "branch_ref": 2,
    "artifact_namespace": 3,
    "external_environment": 4,
    "deployment_target": 5,
}

REJECTION_CODES = (
    "EXEC_ADMISSION_ACTION_ROUTE_UNSUPPORTED",
    "EXEC_ADMISSION_INCOMPLETE",
    "EXEC_ADMISSION_TASK_NOT_READY",
    "EXEC_ADMISSION_PROJECT_STATE_BLOCKED",
    "EXEC_ADMISSION_TASK_STATE_BLOCKED",
    "EXEC_ADMISSION_HUMAN_GATE_BLOCKED",
    "EXEC_ADMISSION_ARTIFACT_MISMATCH",
    "EXEC_ADMISSION_VERIFICATION_PLAN_MISSING",
    "EXEC_ADMISSION_POLICY_NOT_ALLOW",
    "EXEC_ADMISSION_RISK_UNSATISFIED",
    "EXEC_ADMISSION_RESERVATION_INVALID",
    "EXEC_ADMISSION_RESERVATION_ALREADY_BOUND",
    "EXEC_ADMISSION_WORKER_TEMPLATE_UNAVAILABLE",
    "EXEC_ADMISSION_CONTEXT_FREEZE_FAILED",
    "EXEC_ADMISSION_SANDBOX_COMPILE_FAILED",
    "EXEC_ADMISSION_LOCK_CONFLICT",
    "EXEC_ADMISSION_VERSION_CONFLICT",
    "EXEC_ADMISSION_IDEMPOTENCY_CONFLICT",
)


class ExecutionRejected(ValueError):
    pass


class ExecutionRequestState(str, Enum):
    QUEUED = "QUEUED"


class QueueItemState(str, Enum):
    PENDING = "PENDING"


class ActionRoute(str, Enum):
    WORKER = "WORKER"
    CONTROL_PLANE = "CONTROL_PLANE"
    HUMAN_GATE = "HUMAN_GATE"
    RECOVERY = "RECOVERY"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class VersionedRef:
    ref_id: str
    version: int
    content_hash: str


@dataclass(frozen=True)
class ArtifactInputRef:
    artifact_id: str
    task_id: str
    content_hash: str
    media_type: str = ""


@dataclass(frozen=True)
class LockIntent:
    scope: str
    critical: bool = True


@dataclass(frozen=True)
class ExecutionAdmissionSnapshot:
    project_id: str
    task_id: str
    project_version: int
    task_version: int
    decision: VersionedRef
    action: VersionedRef
    action_type: str
    action_requirements_hash: str
    policy: VersionedRef
    risk: VersionedRef
    mandatory_mitigations_hash: str
    resource_reservation: VersionedRef
    capability_match: VersionedRef
    worker_template_id: str
    worker_template_revision: int
    worker_template_content_hash: str
    worker_template_availability_version: int
    context_bundle_id: str
    context_manifest_hash: str
    sandbox_profile_id: str
    sandbox_profile_hash: str
    sandbox_compiler_version: str
    sandbox_compiler_target: str
    verification_plan: VersionedRef
    input_artifacts: Tuple[ArtifactInputRef, ...]
    lock_intents: Tuple[LockIntent, ...]
    priority: int
    attempt_baseline: int = 0


@dataclass(frozen=True)
class PreparedExecutionRequest:
    execution_request_id: str
    queue_item_id: str
    payload_hash: str
    request_snapshot: Mapping[str, Any]


def route_action_type(action_type: str, *, disabled: bool = False) -> ActionRoute:
    normalized = _norm_atom(action_type)
    if disabled:
        return ActionRoute.UNSUPPORTED
    if normalized in WORKER_EXECUTABLE_ACTION_TYPES:
        return ActionRoute.WORKER
    if normalized in CONTROL_PLANE_ACTION_TYPES:
        return ActionRoute.CONTROL_PLANE
    if normalized in HUMAN_GATE_ACTION_TYPES:
        return ActionRoute.HUMAN_GATE
    if normalized in RECOVERY_ACTION_TYPES:
        return ActionRoute.RECOVERY
    return ActionRoute.UNSUPPORTED


def require_worker_executable(action_type: str, *, disabled: bool = False) -> None:
    if route_action_type(action_type, disabled=disabled) is not ActionRoute.WORKER:
        raise ExecutionRejected("EXEC_ADMISSION_ACTION_ROUTE_UNSUPPORTED")


def normalize_priority(value: int) -> int:
    try:
        priority = int(value)
    except (TypeError, ValueError):
        raise ExecutionRejected("EXEC_ADMISSION_INCOMPLETE")
    if priority < MIN_QUEUE_PRIORITY or priority > MAX_QUEUE_PRIORITY:
        raise ExecutionRejected("EXEC_ADMISSION_INCOMPLETE")
    return priority


def normalize_lock_intents(values: Tuple[LockIntent, ...]) -> Tuple[LockIntent, ...]:
    seen = {}
    for item in values:
        canonical = normalize_lock_scope(item.scope)
        seen[canonical] = LockIntent(canonical, bool(item.critical))
    return tuple(
        seen[key] for key in sorted(
            seen,
            key=lambda value: (LOCK_KIND_ORDER[value.split(":", 1)[0]], value),
        )
    )


def normalize_lock_scope(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text or "*" in text or ":" not in text:
        raise ExecutionRejected("EXEC_ADMISSION_LOCK_CONFLICT")
    kind, stable_id = text.split(":", 1)
    if kind not in LOCK_KIND_ORDER:
        raise ExecutionRejected("EXEC_ADMISSION_LOCK_CONFLICT")
    if not stable_id or stable_id in {"*", "all"}:
        raise ExecutionRejected("EXEC_ADMISSION_LOCK_CONFLICT")
    if not re.match(r"^[a-z0-9][a-z0-9:/._-]{0,191}$", stable_id):
        raise ExecutionRejected("EXEC_ADMISSION_LOCK_CONFLICT")
    return kind + ":" + stable_id


def normalize_admission_snapshot(snapshot: ExecutionAdmissionSnapshot) -> Mapping[str, Any]:
    require_worker_executable(snapshot.action_type)
    if snapshot.project_version < 0 or snapshot.task_version < 0:
        raise ExecutionRejected("EXEC_ADMISSION_VERSION_CONFLICT")
    priority = normalize_priority(snapshot.priority)
    lock_intents = normalize_lock_intents(snapshot.lock_intents)
    artifacts = tuple(sorted(
        (_normalize_artifact_ref(item) for item in snapshot.input_artifacts),
        key=lambda item: (item.task_id, item.artifact_id, item.content_hash),
    ))
    payload = {
        "schema_version": EXECUTION_REQUEST_SCHEMA_VERSION,
        "project_id": _require_id(snapshot.project_id, "EXEC_ADMISSION_INCOMPLETE"),
        "task_id": _require_id(snapshot.task_id, "EXEC_ADMISSION_INCOMPLETE"),
        "project_version": int(snapshot.project_version),
        "task_version": int(snapshot.task_version),
        "decision": _versioned_ref(snapshot.decision),
        "action": _versioned_ref(snapshot.action),
        "action_type": _norm_atom(snapshot.action_type),
        "action_requirements_hash": _require_hash(snapshot.action_requirements_hash),
        "policy": _versioned_ref(snapshot.policy),
        "risk": _versioned_ref(snapshot.risk),
        "mandatory_mitigations_hash": _require_hash(snapshot.mandatory_mitigations_hash),
        "resource_reservation": _versioned_ref(snapshot.resource_reservation),
        "capability_match": _versioned_ref(snapshot.capability_match),
        "capability_requirements_hash": _require_hash(snapshot.capability_match.content_hash),
        "worker_template": {
            "template_id": _require_id(snapshot.worker_template_id, "EXEC_ADMISSION_INCOMPLETE"),
            "revision": int(snapshot.worker_template_revision),
            "content_hash": _require_hash(snapshot.worker_template_content_hash),
            "availability_version": int(snapshot.worker_template_availability_version),
        },
        "context_bundle": {
            "bundle_id": _require_id(snapshot.context_bundle_id, "EXEC_ADMISSION_INCOMPLETE"),
            "manifest_hash": _require_hash(snapshot.context_manifest_hash),
        },
        "sandbox_profile": {
            "profile_id": _require_id(snapshot.sandbox_profile_id, "EXEC_ADMISSION_INCOMPLETE"),
            "profile_hash": _require_hash(snapshot.sandbox_profile_hash),
            "compiler_version": _require_id(snapshot.sandbox_compiler_version, "EXEC_ADMISSION_INCOMPLETE"),
            "target": _require_id(snapshot.sandbox_compiler_target, "EXEC_ADMISSION_INCOMPLETE"),
        },
        "verification_plan": _versioned_ref(snapshot.verification_plan),
        "input_artifacts": [
            {
                "artifact_id": item.artifact_id,
                "task_id": item.task_id,
                "content_hash": item.content_hash,
                "media_type": item.media_type,
            }
            for item in artifacts
        ],
        "lock_intents": [
            {"scope": item.scope, "critical": item.critical}
            for item in lock_intents
        ],
        "lock_scope_hash": hash_json([item.scope for item in lock_intents]),
        "priority": priority,
        "attempt_baseline": int(snapshot.attempt_baseline),
        "payload_hash_version": REQUEST_PAYLOAD_HASH_VERSION,
    }
    if payload["attempt_baseline"] != 0:
        raise ExecutionRejected("EXEC_ADMISSION_INCOMPLETE")
    return _canonical(payload)


def prepare_execution_request_snapshot(
    snapshot: ExecutionAdmissionSnapshot,
    *,
    idempotency_key: str,
) -> PreparedExecutionRequest:
    normalized = normalize_admission_snapshot(snapshot)
    payload_hash = hash_json({
        "idempotency_key": _require_id(idempotency_key, "EXEC_ADMISSION_INCOMPLETE"),
        "snapshot": normalized,
    })
    execution_request_id = "exec-" + raw_hash({
        "project_id": normalized["project_id"],
        "decision_id": normalized["decision"]["ref_id"],
        "action_id": normalized["action"]["ref_id"],
        "payload_hash": payload_hash,
    })[:32]
    queue_item_id = "queue-" + raw_hash({
        "execution_request_id": execution_request_id,
        "payload_hash": payload_hash,
    })[:32]
    return PreparedExecutionRequest(
        execution_request_id=execution_request_id,
        queue_item_id=queue_item_id,
        payload_hash=payload_hash,
        request_snapshot=normalized,
    )


def hash_json(value: Any) -> str:
    return "sha256:" + raw_hash(value)


def raw_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _versioned_ref(ref: VersionedRef) -> Mapping[str, Any]:
    if ref.version < 1:
        raise ExecutionRejected("EXEC_ADMISSION_VERSION_CONFLICT")
    return {
        "ref_id": _require_id(ref.ref_id, "EXEC_ADMISSION_INCOMPLETE"),
        "version": int(ref.version),
        "content_hash": _require_hash(ref.content_hash),
    }


def _normalize_artifact_ref(ref: ArtifactInputRef) -> ArtifactInputRef:
    return ArtifactInputRef(
        artifact_id=_require_id(ref.artifact_id, "EXEC_ADMISSION_INCOMPLETE"),
        task_id=_require_id(ref.task_id, "EXEC_ADMISSION_INCOMPLETE"),
        content_hash=_require_hash(ref.content_hash),
        media_type=str(ref.media_type or ""),
    )


def _require_id(value: str, reason: str) -> str:
    text = str(value or "").strip()
    if not text or "*" in text:
        raise ExecutionRejected(reason)
    return text


def _require_hash(value: str) -> str:
    text = str(value or "").strip()
    if not text.startswith("sha256:"):
        raise ExecutionRejected("EXEC_ADMISSION_INCOMPLETE")
    return text


def _norm_atom(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if not text:
        raise ExecutionRejected("EXEC_ADMISSION_INCOMPLETE")
    return text


def _canonical(value: Any) -> Any:
    return json.loads(_canonical_bytes(value).decode("utf-8"))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
