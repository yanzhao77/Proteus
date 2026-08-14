from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol

from hermes_runtime.domain.models import Actor


@dataclass(frozen=True)
class StartQuarantineReview:
    command_id: str
    idempotency_key: str
    project_id: str
    quarantine_id: str
    expected_version: int
    actor: Actor
    authorization_ref: str
    reason: str
    retention_until: str
    causation_id: str = ""
    correlation_id: str = ""
    fault_point: str = ""


@dataclass(frozen=True)
class DiscardQuarantine:
    command_id: str
    idempotency_key: str
    project_id: str
    quarantine_id: str
    expected_version: int
    actor: Actor
    authorization_ref: str
    reason: str
    retention_until: str
    causation_id: str = ""
    correlation_id: str = ""
    fault_point: str = ""


@dataclass(frozen=True)
class RequestQuarantineAdoption:
    command_id: str
    idempotency_key: str
    project_id: str
    quarantine_id: str
    expected_version: int
    actor: Actor
    authorization_ref: str
    reason: str
    guarded_command_id: str
    guarded_idempotency_key: str
    semantic_command_type: str
    guard_refs: Mapping[str, Any]
    retention_until: str
    causation_id: str = ""
    correlation_id: str = ""
    fault_point: str = ""


@dataclass(frozen=True)
class MarkQuarantineAdopted:
    command_id: str
    idempotency_key: str
    project_id: str
    quarantine_id: str
    adoption_request_id: str
    expected_version: int
    actor: Actor
    authorization_ref: str
    reason: str
    causation_id: str = ""
    correlation_id: str = ""
    fault_point: str = ""


@dataclass(frozen=True)
class RequestQuarantineRedrive:
    command_id: str
    idempotency_key: str
    project_id: str
    quarantine_id: str
    expected_version: int
    actor: Actor
    authorization_ref: str
    reason: str
    redrive_command_id: str
    redrive_idempotency_key: str
    redrive_payload: Mapping[str, Any]
    retention_until: str
    causation_id: str = ""
    correlation_id: str = ""
    fault_point: str = ""


@dataclass(frozen=True)
class MarkQuarantineRedriven:
    command_id: str
    idempotency_key: str
    project_id: str
    quarantine_id: str
    redrive_request_id: str
    expected_version: int
    actor: Actor
    authorization_ref: str
    reason: str
    causation_id: str = ""
    correlation_id: str = ""
    fault_point: str = ""


@dataclass(frozen=True)
class ExpireQuarantine:
    command_id: str
    idempotency_key: str
    project_id: str
    quarantine_id: str
    expected_version: int
    actor: Actor
    reason: str
    causation_id: str = ""
    correlation_id: str = ""
    fault_point: str = ""


class QuarantineStore(Protocol):
    def start_review(self, command: StartQuarantineReview) -> Mapping[str, Any]:
        ...

    def discard(self, command: DiscardQuarantine) -> Mapping[str, Any]:
        ...

    def request_adoption(self, command: RequestQuarantineAdoption) -> Mapping[str, Any]:
        ...

    def mark_adopted(self, command: MarkQuarantineAdopted) -> Mapping[str, Any]:
        ...

    def request_redrive(self, command: RequestQuarantineRedrive) -> Mapping[str, Any]:
        ...

    def mark_redriven(self, command: MarkQuarantineRedriven) -> Mapping[str, Any]:
        ...

    def expire(self, command: ExpireQuarantine) -> Mapping[str, Any]:
        ...


class QuarantineAuthority:
    def __init__(self, store: QuarantineStore) -> None:
        self._store = store

    def start_review(self, command: StartQuarantineReview) -> Mapping[str, Any]:
        return self._store.start_review(command)

    def discard(self, command: DiscardQuarantine) -> Mapping[str, Any]:
        return self._store.discard(command)

    def request_adoption(self, command: RequestQuarantineAdoption) -> Mapping[str, Any]:
        return self._store.request_adoption(command)

    def mark_adopted(self, command: MarkQuarantineAdopted) -> Mapping[str, Any]:
        return self._store.mark_adopted(command)

    def request_redrive(self, command: RequestQuarantineRedrive) -> Mapping[str, Any]:
        return self._store.request_redrive(command)

    def mark_redriven(self, command: MarkQuarantineRedriven) -> Mapping[str, Any]:
        return self._store.mark_redriven(command)

    def expire(self, command: ExpireQuarantine) -> Mapping[str, Any]:
        return self._store.expire(command)
