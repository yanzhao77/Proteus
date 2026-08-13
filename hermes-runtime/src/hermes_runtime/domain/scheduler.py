import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Tuple

from hermes_runtime.domain.execution import LOCK_KIND_ORDER, LockIntent, normalize_lock_intents


LEASE_PROFILE_SCHEMA_VERSION = "lease-profile/1.0"
SCHEDULER_COMMAND_HASH_VERSION = "scheduler-command-payload-hash/1.0"

MIN_LEASE_DURATION_MS = 100
MAX_LEASE_DURATION_MS = 3_600_000
MAX_FENCING_TOKEN = 9_223_372_036_854_775_807

LEASE_REASON_CODES = (
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
    "SCHEDULER_IDEMPOTENCY_CONFLICT",
    "FENCING_TOKEN_OVERFLOW",
)


class SchedulerRejected(ValueError):
    pass


class LeaseState(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    RELINQUISHED = "RELINQUISHED"
    SUPERSEDED = "SUPERSEDED"


class RequestLeaseState(str, Enum):
    QUEUED = "QUEUED"
    LEASED = "LEASED"


class QueueClaimState(str, Enum):
    PENDING = "PENDING"
    LEASED = "LEASED"


@dataclass(frozen=True)
class LeaseProfile:
    profile_id: str
    profile_version: int
    initial_ttl_ms: int
    renew_interval_ms: int
    max_extension_ms: int
    max_lifetime_ms: int
    takeover_after_expiry_ms: int
    requeue_backoff_ms: int
    max_acquisition_batch: int = 1
    schema_version: str = LEASE_PROFILE_SCHEMA_VERSION


@dataclass(frozen=True)
class SchedulerIdentity:
    scheduler_id: str
    scheduler_session_id: str
    actor_type: str = "scheduler"
    actor_id: str = "scheduler"


def validate_lease_profile(profile: LeaseProfile) -> Mapping[str, Any]:
    profile_id = _require_id(profile.profile_id, "LEASE_PROFILE_INVALID")
    if profile.profile_version < 1:
        raise SchedulerRejected("LEASE_PROFILE_INVALID")
    durations = {
        "initial_ttl_ms": profile.initial_ttl_ms,
        "renew_interval_ms": profile.renew_interval_ms,
        "max_extension_ms": profile.max_extension_ms,
        "max_lifetime_ms": profile.max_lifetime_ms,
        "takeover_after_expiry_ms": profile.takeover_after_expiry_ms,
        "requeue_backoff_ms": profile.requeue_backoff_ms,
    }
    for name, value in durations.items():
        integer = _bounded_int(value, "LEASE_PROFILE_INVALID")
        if name not in {"requeue_backoff_ms", "takeover_after_expiry_ms"} and integer < MIN_LEASE_DURATION_MS:
            raise SchedulerRejected("LEASE_PROFILE_INVALID")
        if integer > MAX_LEASE_DURATION_MS:
            raise SchedulerRejected("LEASE_PROFILE_INVALID")
    if profile.max_lifetime_ms < profile.initial_ttl_ms:
        raise SchedulerRejected("LEASE_PROFILE_INVALID")
    if profile.renew_interval_ms > profile.initial_ttl_ms:
        raise SchedulerRejected("LEASE_PROFILE_INVALID")
    if profile.max_extension_ms > profile.initial_ttl_ms:
        raise SchedulerRejected("LEASE_PROFILE_INVALID")
    if profile.max_acquisition_batch != 1:
        raise SchedulerRejected("LEASE_PROFILE_INVALID")
    return _canonical({
        "schema_version": profile.schema_version,
        "profile_id": profile_id,
        "profile_version": int(profile.profile_version),
        "initial_ttl_ms": int(profile.initial_ttl_ms),
        "renew_interval_ms": int(profile.renew_interval_ms),
        "max_extension_ms": int(profile.max_extension_ms),
        "max_lifetime_ms": int(profile.max_lifetime_ms),
        "takeover_after_expiry_ms": int(profile.takeover_after_expiry_ms),
        "requeue_backoff_ms": int(profile.requeue_backoff_ms),
        "max_acquisition_batch": int(profile.max_acquisition_batch),
    })


def validate_scheduler_identity(identity: SchedulerIdentity) -> Mapping[str, str]:
    scheduler_id = _require_id(identity.scheduler_id, "SCHEDULER_NOT_ADMITTED")
    session_id = _require_id(identity.scheduler_session_id, "SCHEDULER_NOT_ADMITTED")
    actor_type = _norm_atom(identity.actor_type)
    actor_id = _require_id(identity.actor_id, "SCHEDULER_NOT_ADMITTED")
    if actor_type != "scheduler":
        raise SchedulerRejected("SCHEDULER_NOT_ADMITTED")
    return {
        "scheduler_id": scheduler_id,
        "scheduler_session_id": session_id,
        "actor_type": actor_type,
        "actor_id": actor_id,
    }


def stable_queue_sort_key(item: Mapping[str, Any]) -> Tuple[int, str, str, str]:
    priority = int(item.get("priority", 0))
    return (
        -priority,
        str(item.get("available_at", "")),
        str(item.get("enqueued_at", "")),
        str(item.get("queue_item_id") or item.get("stable_order_key") or ""),
    )


def token_is_stale(submitted_token: int, current_token: int) -> bool:
    submitted = _bounded_int(submitted_token, "FENCING_TOKEN_STALE")
    current = _bounded_int(current_token, "FENCING_TOKEN_STALE")
    return submitted < current


def next_fencing_token(current_token: int) -> int:
    current = _bounded_int(current_token, "FENCING_TOKEN_OVERFLOW")
    if current >= MAX_FENCING_TOKEN:
        raise SchedulerRejected("FENCING_TOKEN_OVERFLOW")
    return current + 1


def canonical_lock_scopes(lock_intents: Tuple[LockIntent, ...]) -> Tuple[str, ...]:
    return tuple(intent.scope for intent in normalize_lock_intents(lock_intents))


def lock_scope_sort_key(scope: str) -> Tuple[int, str]:
    kind = scope.split(":", 1)[0]
    if kind not in LOCK_KIND_ORDER:
        raise SchedulerRejected("EXECUTION_LOCK_CONFLICT")
    return (LOCK_KIND_ORDER[kind], scope)


def hash_command_payload(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload["payload_hash_version"] = SCHEDULER_COMMAND_HASH_VERSION
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _bounded_int(value: int, reason: str) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError):
        raise SchedulerRejected(reason)
    if integer < 0 or integer > MAX_FENCING_TOKEN:
        raise SchedulerRejected(reason)
    return integer


def _require_id(value: str, reason: str) -> str:
    text = str(value or "").strip()
    if not text or "*" in text or len(text) > 200:
        raise SchedulerRejected(reason)
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9:/._-]{0,199}$", text):
        raise SchedulerRejected(reason)
    return text


def _norm_atom(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if not text:
        raise SchedulerRejected("SCHEDULER_NOT_ADMITTED")
    return text


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
