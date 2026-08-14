import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Tuple


class QuarantineState(str, Enum):
    QUARANTINED = "QUARANTINED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DISCARDED = "DISCARDED"
    ADOPTION_REQUESTED = "ADOPTION_REQUESTED"
    ADOPTED = "ADOPTED"
    REDRIVE_REQUESTED = "REDRIVE_REQUESTED"
    REDRIVEN = "REDRIVEN"
    EXPIRED = "EXPIRED"


class QuarantineOperation(str, Enum):
    START_REVIEW = "START_REVIEW"
    DISCARD = "DISCARD"
    REQUEST_ADOPTION = "REQUEST_ADOPTION"
    MARK_ADOPTED = "MARK_ADOPTED"
    REQUEST_REDRIVE = "REQUEST_REDRIVE"
    MARK_REDRIVEN = "MARK_REDRIVEN"
    EXPIRE = "EXPIRE"


TERMINAL_QUARANTINE_STATES = frozenset(
    {
        QuarantineState.DISCARDED,
        QuarantineState.ADOPTED,
        QuarantineState.REDRIVEN,
        QuarantineState.EXPIRED,
    }
)


ALLOWED_QUARANTINE_TRANSITIONS = {
    QuarantineState.QUARANTINED: frozenset(
        {QuarantineState.UNDER_REVIEW, QuarantineState.EXPIRED}
    ),
    QuarantineState.UNDER_REVIEW: frozenset(
        {
            QuarantineState.DISCARDED,
            QuarantineState.ADOPTION_REQUESTED,
            QuarantineState.REDRIVE_REQUESTED,
            QuarantineState.EXPIRED,
        }
    ),
    QuarantineState.ADOPTION_REQUESTED: frozenset(
        {QuarantineState.ADOPTED, QuarantineState.EXPIRED}
    ),
    QuarantineState.REDRIVE_REQUESTED: frozenset(
        {QuarantineState.REDRIVEN, QuarantineState.EXPIRED}
    ),
    QuarantineState.DISCARDED: frozenset(),
    QuarantineState.ADOPTED: frozenset(),
    QuarantineState.REDRIVEN: frozenset(),
    QuarantineState.EXPIRED: frozenset(),
}


OPERATION_TARGETS = {
    QuarantineOperation.START_REVIEW: QuarantineState.UNDER_REVIEW,
    QuarantineOperation.DISCARD: QuarantineState.DISCARDED,
    QuarantineOperation.REQUEST_ADOPTION: QuarantineState.ADOPTION_REQUESTED,
    QuarantineOperation.MARK_ADOPTED: QuarantineState.ADOPTED,
    QuarantineOperation.REQUEST_REDRIVE: QuarantineState.REDRIVE_REQUESTED,
    QuarantineOperation.MARK_REDRIVEN: QuarantineState.REDRIVEN,
    QuarantineOperation.EXPIRE: QuarantineState.EXPIRED,
}


FORBIDDEN_OPERATION_ACTORS = frozenset({"worker", "scheduler", "action_planner", "verifier"})


@dataclass(frozen=True)
class QuarantineReviewContext:
    quarantine_id: str
    state: QuarantineState
    version: int
    retention_expired: bool = False


def canonical_payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def transition_quarantine_state(
    context: QuarantineReviewContext, operation: QuarantineOperation
) -> QuarantineState:
    if context.state in TERMINAL_QUARANTINE_STATES:
        raise ValueError("QUARANTINE_ALREADY_RESOLVED")
    if context.retention_expired and operation is not QuarantineOperation.EXPIRE:
        raise ValueError("QUARANTINE_RETENTION_EXPIRED")
    target = OPERATION_TARGETS[operation]
    if target not in ALLOWED_QUARANTINE_TRANSITIONS[context.state]:
        raise ValueError(
            "invalid quarantine transition {} -> {}".format(context.state.value, target.value)
        )
    return target


def assert_reviewer_actor(actor_type: str) -> None:
    if actor_type in FORBIDDEN_OPERATION_ACTORS:
        raise ValueError("QUARANTINE_REVIEW_UNAUTHORIZED")
    if actor_type not in {"system_operator", "control_plane", "recovery_controller"}:
        raise ValueError("QUARANTINE_REVIEW_UNAUTHORIZED")


def validate_adoption_command(
    *,
    semantic_command_type: str,
    guarded_command_id: str,
    guarded_idempotency_key: str,
    task_directive: Optional[str] = None,
) -> None:
    if not semantic_command_type or "." not in semantic_command_type:
        raise ValueError("QUARANTINE_ADOPTION_GUARD_FAILED")
    if not guarded_command_id or not guarded_idempotency_key:
        raise ValueError("QUARANTINE_ADOPTION_GUARD_FAILED")
    if task_directive in {"PASS", "PASSED", "FAIL", "FAILED"}:
        raise ValueError("QUARANTINE_ADOPTION_GUARD_FAILED")


def validate_redrive_identity(
    *,
    original_command_id: Optional[str],
    original_idempotency_key: Optional[str],
    redrive_command_id: str,
    redrive_idempotency_key: str,
) -> None:
    if not redrive_command_id or not redrive_idempotency_key:
        raise ValueError("QUARANTINE_REDRIVE_CONFLICT")
    if original_command_id and redrive_command_id == original_command_id:
        raise ValueError("QUARANTINE_REDRIVE_CONFLICT")
    if original_idempotency_key and redrive_idempotency_key == original_idempotency_key:
        raise ValueError("QUARANTINE_REDRIVE_CONFLICT")


def immutable_origin_fields() -> Tuple[str, ...]:
    return (
        "safe_payload_envelope",
        "payload_hash",
        "submitted_lease_id",
        "submitted_fencing_token",
        "observed_current_lease_id",
        "observed_current_fencing_token",
        "run_id",
        "execution_request_id",
        "source_command_id",
    )
