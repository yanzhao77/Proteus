import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Tuple


RECOVERY_HASH_VERSION = "recovery-payload-hash/1.0"
RECOVERY_POLICY_VERSION = "recovery-policy/1.0"


class RecoveryRejected(ValueError):
    pass


class FailureType(str, Enum):
    TEST_ASSERTION_FAILURE = "test_assertion_failure"
    BUILD_FAILURE = "build_failure"
    ADAPTER_TRANSIENT = "adapter_transient"
    WORKER_TIMEOUT = "worker_timeout"
    POLICY_DENIED = "policy_denied"
    BUDGET_EXHAUSTED = "budget_exhausted"
    SANDBOX_VIOLATION = "sandbox_violation"
    UNKNOWN_EXECUTION_FAILURE = "unknown_execution_failure"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RecoveryLevel(str, Enum):
    L0_RETRY = "L0_RETRY"
    L1_REPAIR = "L1_REPAIR"
    L2_SWITCH_STRATEGY = "L2_SWITCH_STRATEGY"
    L3_SWITCH_WORKER = "L3_SWITCH_WORKER"
    L4_COLLABORATION = "L4_COLLABORATION"
    L5_REPLAN = "L5_REPLAN"
    L6_HUMAN_GATE = "L6_HUMAN_GATE"


class RecoveryAction(str, Enum):
    RETRY = "retry"
    REPAIR = "repair"
    SWITCH_STRATEGY = "switch_strategy"
    SWITCH_WORKER = "switch_worker"
    COLLABORATION = "collaboration"
    REPLAN = "replan"
    HUMAN_GATE = "human_gate"


@dataclass(frozen=True)
class ExecutionFailure:
    result_id: str
    outcome: str
    error_classification: str
    adapter_identity: str
    task_id: str
    artifact_candidate_refs: Tuple[str, ...] = ()
    evidence_candidate_refs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class StructuredFeedback:
    failure_type: FailureType
    severity: Severity
    finding_codes: Tuple[str, ...]
    recommended_actions: Tuple[RecoveryAction, ...]
    recovery_level: RecoveryLevel
    root_cause: Optional[str] = None


@dataclass(frozen=True)
class RecoveryPolicy:
    max_attempts: int
    policy_version: str = RECOVERY_POLICY_VERSION


def classify_execution_failure(failure: ExecutionFailure) -> StructuredFeedback:
    if failure.outcome == "SUCCEEDED":
        raise RecoveryRejected("RECOVERY_FEEDBACK_SOURCE_NOT_FAILED")
    raw = (failure.error_classification or "").strip().lower()
    normalized = raw.replace("-", "_").replace(" ", "_")
    mapping = {
        "test_assertion_failure": FailureType.TEST_ASSERTION_FAILURE,
        "assertion_failure": FailureType.TEST_ASSERTION_FAILURE,
        "build_failure": FailureType.BUILD_FAILURE,
        "compile_error": FailureType.BUILD_FAILURE,
        "adapter_transient": FailureType.ADAPTER_TRANSIENT,
        "tool_transient": FailureType.ADAPTER_TRANSIENT,
        "timeout": FailureType.WORKER_TIMEOUT,
        "worker_timeout": FailureType.WORKER_TIMEOUT,
        "policy_denied": FailureType.POLICY_DENIED,
        "budget_exhausted": FailureType.BUDGET_EXHAUSTED,
        "sandbox_violation": FailureType.SANDBOX_VIOLATION,
    }
    failure_type = mapping.get(normalized, FailureType.UNKNOWN_EXECUTION_FAILURE)
    if failure_type is FailureType.ADAPTER_TRANSIENT:
        return StructuredFeedback(
            failure_type,
            Severity.MEDIUM,
            ("ADAPTER_TRANSIENT",),
            (RecoveryAction.RETRY, RecoveryAction.SWITCH_WORKER),
            RecoveryLevel.L0_RETRY,
        )
    if failure_type is FailureType.WORKER_TIMEOUT:
        return StructuredFeedback(
            failure_type,
            Severity.MEDIUM,
            ("WORKER_TIMEOUT",),
            (RecoveryAction.RETRY, RecoveryAction.SWITCH_WORKER),
            RecoveryLevel.L0_RETRY,
        )
    if failure_type in {FailureType.TEST_ASSERTION_FAILURE, FailureType.BUILD_FAILURE}:
        return StructuredFeedback(
            failure_type,
            Severity.HIGH,
            (failure_type.value.upper(),),
            (RecoveryAction.REPAIR, RecoveryAction.RETRY),
            RecoveryLevel.L1_REPAIR,
            failure_type.value,
        )
    if failure_type is FailureType.POLICY_DENIED:
        return StructuredFeedback(
            failure_type,
            Severity.HIGH,
            ("POLICY_DENIED",),
            (RecoveryAction.SWITCH_STRATEGY, RecoveryAction.HUMAN_GATE),
            RecoveryLevel.L2_SWITCH_STRATEGY,
        )
    if failure_type is FailureType.BUDGET_EXHAUSTED:
        return StructuredFeedback(
            failure_type,
            Severity.HIGH,
            ("BUDGET_EXHAUSTED",),
            (RecoveryAction.SWITCH_STRATEGY, RecoveryAction.HUMAN_GATE),
            RecoveryLevel.L2_SWITCH_STRATEGY,
        )
    if failure_type is FailureType.SANDBOX_VIOLATION:
        return StructuredFeedback(
            failure_type,
            Severity.CRITICAL,
            ("SANDBOX_VIOLATION",),
            (RecoveryAction.HUMAN_GATE,),
            RecoveryLevel.L6_HUMAN_GATE,
        )
    return StructuredFeedback(
        failure_type,
        Severity.MEDIUM,
        ("UNKNOWN_EXECUTION_FAILURE",),
        (RecoveryAction.REPLAN, RecoveryAction.HUMAN_GATE),
        RecoveryLevel.L5_REPLAN,
    )


def choose_recovery_action(
    feedback: StructuredFeedback, attempts_used: int, policy: RecoveryPolicy
) -> Tuple[RecoveryAction, RecoveryLevel, str]:
    if policy.policy_version != RECOVERY_POLICY_VERSION:
        raise RecoveryRejected("RECOVERY_POLICY_VERSION_UNSUPPORTED")
    if policy.max_attempts < 1:
        raise RecoveryRejected("RECOVERY_POLICY_INVALID")
    if attempts_used >= policy.max_attempts:
        return RecoveryAction.HUMAN_GATE, RecoveryLevel.L6_HUMAN_GATE, "RECOVERY_EXHAUSTED"
    action = feedback.recommended_actions[0] if feedback.recommended_actions else RecoveryAction.REPLAN
    level = feedback.recovery_level
    return action, level, "RECOVERY_ATTEMPT_PLANNED"


def hash_payload(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload["payload_hash_version"] = RECOVERY_HASH_VERSION
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
