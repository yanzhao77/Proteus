import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional, Tuple


RULE_SET_VERSION = "situation-rules/1.0"
CANONICALIZATION_VERSION = "situation-fingerprint/1.0"


class SituationRejected(ValueError):
    pass


class SituationType(str, Enum):
    VERIFICATION_FAILED = "verification_failed"
    WORK_AVAILABLE = "work_available"
    BUDGET_PRESSURE = "budget_pressure"
    POLICY_BLOCKED = "policy_blocked"
    STATE_CONFLICT = "state_conflict"
    RESOURCE_MISSING = "resource_missing"
    AGENT_STALLED = "agent_stalled"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class TriggerFact:
    project_id: str
    event_type: str
    schema_version: str
    task_id: Optional[str]
    payload: Mapping[str, object]


@dataclass(frozen=True)
class SituationClassification:
    situation_type: SituationType
    failure_type: Optional[str]
    severity: Severity
    confidence_basis_points: int
    affected_components: Tuple[str, ...]
    artifact_refs: Tuple[str, ...]
    context_refs: Tuple[str, ...]
    constraints: Tuple[str, ...]


TRIGGER_EVENT_CATALOG = {
    "verification.recorded",
    "task.readiness_recomputed",
    "budget.reserved",
    "budget.settled",
    "budget.released",
    "feedback.created",
    "policy.evaluated",
    "project.state_transition.rejected",
    "command.version_conflict",
    "work_graph.version_conflict",
    "resource.missing",
    "agent.stalled",
}


def classify_trigger(fact: TriggerFact) -> Optional[SituationClassification]:
    if fact.event_type not in TRIGGER_EVENT_CATALOG:
        return None
    _validate_schema(fact.schema_version)
    payload = fact.payload
    if fact.event_type == "verification.recorded":
        if payload.get("verdict") != "FAIL":
            return None
        failure = str(payload.get("failure_type") or "unknown_verification_failure")
        return SituationClassification(
            SituationType.VERIFICATION_FAILED,
            failure,
            _severity(payload.get("severity"), Severity.HIGH),
            10000 if failure != "unknown_verification_failure" else 8000,
            _strings(payload.get("affected_components")),
            _strings(payload.get("artifact_refs") or payload.get("artifact_id")),
            _strings(payload.get("evidence_refs") or payload.get("verification_id")),
            _strings(payload.get("constraints")),
        )
    if fact.event_type == "task.readiness_recomputed":
        changes = payload.get("ready_state_changes") or payload.get("readiness_changes")
        ready_tasks = _ready_task_ids(changes)
        if fact.task_id is not None:
            ready_tasks = tuple(item for item in ready_tasks if item == fact.task_id)
        if not ready_tasks:
            return None
        return SituationClassification(
            SituationType.WORK_AVAILABLE, None, Severity.LOW, 10000,
            _strings(payload.get("affected_components"))
            or tuple("task:" + item for item in ready_tasks), (),
            tuple("task:" + item for item in ready_tasks), (),
        )
    if fact.event_type.startswith("budget."):
        threshold = payload.get("threshold_status")
        if threshold not in {"WARN", "GATE", "HARD_STOP"}:
            return None
        return SituationClassification(
            SituationType.BUDGET_PRESSURE, "budget_" + str(threshold).lower(),
            {"WARN": Severity.MEDIUM, "GATE": Severity.HIGH,
             "HARD_STOP": Severity.CRITICAL}[str(threshold)],
            10000, ("resource_account:" + str(payload.get("account_id")),),
            (), ("resource_account_version:" + str(payload.get("entity_version")),),
            ("budget_" + str(threshold).lower(),),
        )
    if fact.event_type == "feedback.created":
        failure = str(payload.get("failure_type") or "unknown_feedback_failure")
        return SituationClassification(
            SituationType.VERIFICATION_FAILED, failure,
            _severity(payload.get("severity"), Severity.MEDIUM), 9000,
            _strings(payload.get("affected_components")),
            _strings(payload.get("affected_artifact_refs")),
            _strings(payload.get("evidence_refs") or payload.get("verification_id")),
            _strings(payload.get("constraints")),
        )
    if fact.event_type in {
        "command.version_conflict", "work_graph.version_conflict",
        "project.state_transition.rejected",
    }:
        if payload.get("reason_code") not in {
            "VERSION_CONFLICT", "GRAPH_VERSION_CONFLICT",
            "PROJECT_AUTHORITY_PRECONDITION_FAILED",
        }:
            raise SituationRejected("SITUATION_CLASSIFICATION_UNSUPPORTED")
        return SituationClassification(
            SituationType.STATE_CONFLICT, str(payload["reason_code"]),
            Severity.MEDIUM, 10000,
            _strings(payload.get("affected_components") or payload.get("entity_ref")),
            (), _strings(payload.get("context_refs")), ("reload_required",),
        )
    raise SituationRejected("SITUATION_CLASSIFICATION_UNSUPPORTED")


def canonical_fingerprint(
    project_id: str,
    classification: SituationClassification,
    task_id: Optional[str],
) -> str:
    if not project_id or not classification.situation_type:
        raise SituationRejected("SITUATION_FINGERPRINT_INVALID")
    canonical = {
        "canonicalization_version": CANONICALIZATION_VERSION,
        "project_id": project_id,
        "type": classification.situation_type.value,
        "task_id": task_id,
        "affected_components": list(classification.affected_components),
        "causal_failure": classification.failure_type,
    }
    return "sha256:" + _hash(canonical)


def context_hash(context: Mapping[str, object]) -> str:
    return "sha256:" + _hash(context)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _validate_schema(version: str) -> None:
    try:
        major = int(version.split(".", 1)[0])
    except (AttributeError, ValueError):
        raise SituationRejected("SITUATION_TRIGGER_SCHEMA_INVALID")
    if major != 1:
        raise SituationRejected("SITUATION_TRIGGER_SCHEMA_INVALID")


def _strings(value: object) -> Tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, (list, tuple, set)) else (value,)
    return tuple(sorted({str(item).strip() for item in values if str(item).strip()}))


def _severity(value: object, default: Severity) -> Severity:
    if value is None:
        return default
    try:
        return Severity(str(value))
    except ValueError:
        raise SituationRejected("SITUATION_CLASSIFICATION_UNSUPPORTED")


def _contains_ready(changes: object, task_id: str) -> bool:
    return task_id in _ready_task_ids(changes)


def _ready_task_ids(changes: object) -> Tuple[str, ...]:
    if not isinstance(changes, (list, tuple)):
        return ()
    return tuple(sorted({
        str(item.get("task_id"))
        for item in changes
        if isinstance(item, Mapping)
        and item.get("task_id") is not None
        and str(item.get("to_state") or item.get("state")) == "READY"
    }))
