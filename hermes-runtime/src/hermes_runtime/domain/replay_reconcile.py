import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Tuple


class ReplaySessionState(str, Enum):
    REQUESTED = "REQUESTED"
    VALIDATED = "VALIDATED"
    RUNNING = "RUNNING"
    VERIFIED = "VERIFIED"
    ACTIVATED = "ACTIVATED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class FindingKind(str, Enum):
    CHECKPOINT_AHEAD = "CHECKPOINT_AHEAD"
    CHECKPOINT_CORRUPT = "CHECKPOINT_CORRUPT"
    EVENT_GAP = "EVENT_GAP"
    OUTBOX_MISSING = "OUTBOX_MISSING"
    OUTBOX_ORPHANED = "OUTBOX_ORPHANED"
    INBOX_EFFECT_MISSING = "INBOX_EFFECT_MISSING"
    EFFECT_WITHOUT_CHECKPOINT = "EFFECT_WITHOUT_CHECKPOINT"
    READ_MODEL_DRIFT = "READ_MODEL_DRIFT"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"
    DLQ_PENDING = "DLQ_PENDING"
    AUTHORITY_EVENT_MISMATCH = "AUTHORITY_EVENT_MISMATCH"


class RepairAction(str, Enum):
    REBUILD_READ_MODEL_GENERATION = "REBUILD_READ_MODEL_GENERATION"
    REPLAY_IDEMPOTENT_CONSUMER_RANGE = "REPLAY_IDEMPOTENT_CONSUMER_RANGE"
    ADVANCE_CHECKPOINT_IF_EFFECT_CONTIGUOUS = "ADVANCE_CHECKPOINT_IF_EFFECT_CONTIGUOUS"
    REGENERATE_MISSING_OUTBOX_VIA_AUTHORITY = "REGENERATE_MISSING_OUTBOX_VIA_AUTHORITY"
    REDRIVE_SUPPORTED_EVENT = "REDRIVE_SUPPORTED_EVENT"
    MARK_UNSUPPORTED_SCHEMA_BLOCKED = "MARK_UNSUPPORTED_SCHEMA_BLOCKED"
    SUPERSEDE_STALE_PLAN = "SUPERSEDE_STALE_PLAN"


TERMINAL_REPLAY_STATES = frozenset(
    {
        ReplaySessionState.ACTIVATED,
        ReplaySessionState.FAILED,
        ReplaySessionState.CANCELLED,
        ReplaySessionState.SUPERSEDED,
    }
)

ALLOWED_REPLAY_TRANSITIONS = {
    ReplaySessionState.REQUESTED: frozenset(
        {ReplaySessionState.VALIDATED, ReplaySessionState.CANCELLED, ReplaySessionState.FAILED}
    ),
    ReplaySessionState.VALIDATED: frozenset(
        {ReplaySessionState.RUNNING, ReplaySessionState.CANCELLED, ReplaySessionState.FAILED}
    ),
    ReplaySessionState.RUNNING: frozenset(
        {ReplaySessionState.VERIFIED, ReplaySessionState.FAILED, ReplaySessionState.CANCELLED}
    ),
    ReplaySessionState.VERIFIED: frozenset(
        {ReplaySessionState.ACTIVATED, ReplaySessionState.SUPERSEDED, ReplaySessionState.FAILED}
    ),
    ReplaySessionState.ACTIVATED: frozenset(),
    ReplaySessionState.FAILED: frozenset(),
    ReplaySessionState.CANCELLED: frozenset(),
    ReplaySessionState.SUPERSEDED: frozenset(),
}


@dataclass(frozen=True)
class CheckpointSnapshot:
    consumer_id: str
    stream_name: str
    partition_key: str
    generation_id: str
    last_sequence: int
    consumer_version: str
    schema_version: str
    projection_digest: str
    previous_checkpoint_id: Optional[str] = None


def canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def checkpoint_hash(snapshot: CheckpointSnapshot) -> str:
    return canonical_hash(
        {
            "consumer_id": snapshot.consumer_id,
            "stream_name": snapshot.stream_name,
            "partition_key": snapshot.partition_key,
            "generation_id": snapshot.generation_id,
            "last_sequence": snapshot.last_sequence,
            "consumer_version": snapshot.consumer_version,
            "schema_version": snapshot.schema_version,
            "projection_digest": snapshot.projection_digest,
            "previous_checkpoint_id": snapshot.previous_checkpoint_id,
        }
    )


def classify_sequence(checkpoint: int, observed: int) -> str:
    if observed == checkpoint + 1:
        return "CONTIGUOUS"
    if observed <= checkpoint:
        return "DUPLICATE_OR_LATE"
    return "EVENT_GAP_DETECTED"


def validate_schema_version(schema_version: str) -> str:
    major = str(schema_version).split(".", 1)[0]
    if major != "1":
        return "EVENT_SCHEMA_UNSUPPORTED"
    return "SUPPORTED"


def transition_replay_state(
    current: ReplaySessionState, target: ReplaySessionState
) -> ReplaySessionState:
    if target not in ALLOWED_REPLAY_TRANSITIONS[current]:
        raise ValueError("invalid replay transition {} -> {}".format(current.value, target.value))
    return target


def validate_repair_actions(actions: Sequence[str]) -> Tuple[RepairAction, ...]:
    allowed = []
    for action in actions:
        try:
            allowed.append(RepairAction(action))
        except ValueError:
            raise ValueError("repair action is not whitelisted: {}".format(action))
    return tuple(allowed)


def reconcile_plan_hash(
    finding_ids: Sequence[str],
    observed_versions: Mapping[str, Any],
    repair_actions: Sequence[str],
    dry_run: bool,
) -> str:
    validate_repair_actions(repair_actions)
    return canonical_hash(
        {
            "finding_ids": sorted(finding_ids),
            "observed_versions": dict(sorted(observed_versions.items())),
            "repair_actions": list(repair_actions),
            "dry_run": dry_run,
        }
    )
