import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from hermes_runtime.domain.models import Actor


PRODUCT_API_HASH_VERSION = "product-api-request-hash/1.0"

FORBIDDEN_AUTHORITY_FIELDS = {
    "new_state",
    "state",
    "task_status",
    "project_state",
    "mark_passed",
    "mark_failed",
    "set_task_passed",
    "set_task_failed",
    "update_task_status",
    "sql",
    "event",
    "event_type",
    "arbitrary_command",
}

FORBIDDEN_RESPONSE_FIELDS = {
    "new_state",
    "mark_passed",
    "mark_failed",
    "set_task_passed",
    "set_task_failed",
    "update_task_status",
    "sql",
    "arbitrary_command",
}

FORBIDDEN_PATH_FRAGMENTS = {
    "/patch",
    "/sql",
    "/events",
    "/event-log",
    "/generic-command",
    "/state",
}


class ProductApiRejected(ValueError):
    pass


@dataclass(frozen=True)
class ProductApiRequest:
    method: str
    path: str
    headers: Mapping[str, str]
    body: Mapping[str, Any]
    actor: Actor


@dataclass(frozen=True)
class ProductApiResponse:
    status_code: int
    body: Mapping[str, Any]


def canonical_payload_hash(payload: Mapping[str, Any]) -> str:
    material = dict(payload)
    material["payload_hash_version"] = PRODUCT_API_HASH_VERSION
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def require_authority_command_metadata(body: Mapping[str, Any]) -> None:
    for field in ("command_id", "expected_version", "actor", "reason"):
        value = body.get(field)
        if value is None or value == "":
            raise ProductApiRejected("API_COMMAND_METADATA_MISSING")
    idempotency_key = body.get("idempotency_key") or body.get("Idempotency-Key")
    if not idempotency_key:
        raise ProductApiRejected("API_IDEMPOTENCY_KEY_MISSING")
    if not isinstance(body.get("expected_version"), int):
        raise ProductApiRejected("API_EXPECTED_VERSION_INVALID")
    if not str(body.get("reason", "")).strip():
        raise ProductApiRejected("API_REASON_REQUIRED")


def reject_forbidden_authority_shape(request: ProductApiRequest) -> None:
    method = request.method.upper()
    path = request.path.lower()
    if method in {"PATCH", "PUT", "DELETE"}:
        raise ProductApiRejected("API_GENERIC_MUTATION_FORBIDDEN")
    if method != "GET" and path.endswith("/status"):
        raise ProductApiRejected("API_AUTHORITY_PATH_FORBIDDEN")
    if any(fragment in path for fragment in FORBIDDEN_PATH_FRAGMENTS):
        raise ProductApiRejected("API_AUTHORITY_PATH_FORBIDDEN")
    forbidden = _find_forbidden_fields(request.body)
    if forbidden:
        raise ProductApiRejected("API_AUTHORITY_FIELD_FORBIDDEN:{}".format(",".join(sorted(forbidden))))


def ensure_safe_response(payload: Mapping[str, Any]) -> None:
    forbidden = _find_keys(payload, FORBIDDEN_RESPONSE_FIELDS)
    secret_refs = _find_secret_values(payload)
    if forbidden:
        raise ProductApiRejected("API_UNSAFE_RESPONSE_FIELD:{}".format(",".join(sorted(forbidden))))
    if secret_refs:
        raise ProductApiRejected("API_SECRET_VALUE_FORBIDDEN")


def _find_forbidden_fields(value: Any) -> set:
    found = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).lower() in FORBIDDEN_AUTHORITY_FIELDS:
                found.add(str(key))
            found.update(_find_forbidden_fields(nested))
    elif isinstance(value, (tuple, list)):
        for item in value:
            found.update(_find_forbidden_fields(item))
    return found


def _find_secret_values(value: Any) -> set:
    found = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).lower()
            if lowered in {"secret", "secret_value", "password", "token", "api_key"} and nested:
                found.add(str(key))
            found.update(_find_secret_values(nested))
    elif isinstance(value, (tuple, list)):
        for item in value:
            found.update(_find_secret_values(item))
    return found


def _find_keys(value: Any, keys: set) -> set:
    found = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).lower() in keys:
                found.add(str(key))
            found.update(_find_keys(nested, keys))
    elif isinstance(value, (tuple, list)):
        for item in value:
            found.update(_find_keys(item, keys))
    return found
