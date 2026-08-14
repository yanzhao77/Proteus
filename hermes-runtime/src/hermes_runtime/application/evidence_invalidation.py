from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from hermes_runtime.domain.models import Actor


@dataclass(frozen=True)
class InvalidateEvidence:
    command_id: str
    idempotency_key: str
    project_id: str
    evidence_id: str
    expected_version: int
    actor: Actor
    producer: str
    reason_code: str
    reason: str
    scope: str
    affected_refs: Mapping[str, Any]
    dependency_refs: Sequence[str]
    authorization_ref: str
    causation_id: str = ""
    correlation_id: str = ""
    fault_point: str = ""


class EvidenceInvalidationStore(Protocol):
    def invalidate(self, command: InvalidateEvidence) -> Mapping[str, Any]:
        ...


class EvidenceInvalidationAuthority:
    def __init__(self, store: EvidenceInvalidationStore) -> None:
        self._store = store

    def invalidate(self, command: InvalidateEvidence) -> Mapping[str, Any]:
        return self._store.invalidate(command)
