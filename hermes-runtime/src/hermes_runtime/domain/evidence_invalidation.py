import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence, Tuple


class EvidenceValidityState(str, Enum):
    VALID = "VALID"
    INVALIDATED = "INVALIDATED"


class EvidenceDependencyAction(str, Enum):
    REVERIFICATION_REQUIRED = "REVERIFICATION_REQUIRED"
    DECISION_STALE = "DECISION_STALE"
    GATE_EVIDENCE_INVALID = "GATE_EVIDENCE_INVALID"


@dataclass(frozen=True)
class EvidenceInvalidationContext:
    evidence_id: str
    state: EvidenceValidityState
    version: int


def canonical_payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def invalidate_evidence_state(
    context: EvidenceInvalidationContext, expected_version: int
) -> EvidenceInvalidationContext:
    if context.version != expected_version:
        raise ValueError("EXPECTED_VERSION_CONFLICT")
    if context.state is EvidenceValidityState.INVALIDATED:
        raise ValueError("EVIDENCE_ALREADY_INVALIDATED")
    return EvidenceInvalidationContext(
        evidence_id=context.evidence_id,
        state=EvidenceValidityState.INVALIDATED,
        version=context.version + 1,
    )


def invalidated_evidence_blocks_use(evidence_refs: Sequence[str], invalidated_refs: Sequence[str]) -> bool:
    invalid = set(invalidated_refs)
    return any(ref in invalid for ref in evidence_refs)


def propagation_action_for_scope(scope: str, affected_refs: Mapping[str, Any]) -> EvidenceDependencyAction:
    if scope in {"UNKNOWN", "unknown", "undetermined"}:
        return EvidenceDependencyAction.REVERIFICATION_REQUIRED
    if affected_refs.get("gate_decision_ids") or affected_refs.get("resume_context_ids"):
        return EvidenceDependencyAction.GATE_EVIDENCE_INVALID
    return EvidenceDependencyAction.REVERIFICATION_REQUIRED


def assert_no_history_rewrite(table_name: str, mutation: str) -> None:
    if table_name in {"evidence", "verification_results"} and mutation in {"UPDATE", "DELETE"}:
        raise ValueError("EVIDENCE_HISTORY_IS_APPEND_ONLY")


def task_state_after_invalidation(current_task_state: str) -> str:
    if current_task_state == "PASSED":
        return "REVERIFICATION_REQUIRED"
    return "EVIDENCE_DEPENDENCY_STALE"
