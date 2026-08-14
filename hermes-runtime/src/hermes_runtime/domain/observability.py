from dataclasses import dataclass
from typing import Any, Mapping, Tuple


class ObservabilityRejected(ValueError):
    pass


@dataclass(frozen=True)
class MissingLink:
    ref_type: str
    ref_id: str
    reason: str


@dataclass(frozen=True)
class ObservabilityRecord:
    trace_id: str
    span_id: str
    parent_span_id: str
    name: str
    timestamp: str
    attributes: Mapping[str, Any]
    events: Tuple[Mapping[str, Any], ...] = ()
    metrics: Mapping[str, float] = None
    source_refs: Tuple[Mapping[str, str], ...] = ()
    missing_links: Tuple[MissingLink, ...] = ()


SECRET_ATTRIBUTE_KEYS = {"secret", "secret_value", "password", "token", "api_key"}
AUTHORITY_ATTRIBUTE_KEYS = {
    "policy_allow",
    "gate_approved",
    "budget_available",
    "task_passed",
    "project_resumed",
    "authorization_fact",
}


def validate_observability_record(record: ObservabilityRecord) -> None:
    if not record.trace_id or not record.span_id or not record.name:
        raise ObservabilityRejected("OBSERVABILITY_IDENTITY_REQUIRED")
    unsafe_authority = _find_keys(record.attributes, AUTHORITY_ATTRIBUTE_KEYS)
    for event in record.events:
        unsafe_authority.update(_find_keys(event, AUTHORITY_ATTRIBUTE_KEYS))
    if unsafe_authority:
        raise ObservabilityRejected("OBSERVABILITY_CANNOT_AUTHORIZE")


def redact_observability_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        result = {}
        for key, nested in value.items():
            lowered = str(key).lower()
            if lowered in SECRET_ATTRIBUTE_KEYS:
                result[key] = "[REDACTED]"
            elif lowered in {"chain_of_thought", "raw_prompt", "raw_stdout", "raw_stderr"}:
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_observability_payload(nested)
        return result
    if isinstance(value, tuple):
        return tuple(redact_observability_payload(item) for item in value)
    if isinstance(value, list):
        return [redact_observability_payload(item) for item in value]
    return value


def missing_link(ref_type: str, ref_id: str, reason: str) -> MissingLink:
    if not reason:
        raise ObservabilityRejected("OBSERVABILITY_MISSING_REASON_REQUIRED")
    return MissingLink(ref_type=ref_type, ref_id=ref_id, reason=reason)


def to_export_envelope(record: ObservabilityRecord) -> Mapping[str, Any]:
    validate_observability_record(record)
    return {
        "schema": "otel-compatible-local/1.0",
        "trace_id": record.trace_id,
        "span_id": record.span_id,
        "parent_span_id": record.parent_span_id,
        "name": record.name,
        "timestamp": record.timestamp,
        "attributes": redact_observability_payload(record.attributes),
        "events": tuple(redact_observability_payload(event) for event in record.events),
        "metrics": dict(record.metrics or {}),
        "source_refs": tuple(dict(ref) for ref in record.source_refs),
        "missing_links": tuple(link.__dict__ for link in record.missing_links),
    }


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
