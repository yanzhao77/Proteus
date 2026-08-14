from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from hermes_runtime.domain.docker_execution import DockerProcessState
from hermes_runtime.domain.models import Actor


@dataclass(frozen=True)
class RecordDockerProcess:
    command_id: str
    idempotency_key: str
    project_id: str
    execution_request_id: str
    run_id: str
    lease_id: str
    lease_version: int
    fencing_token: int
    container_name: str
    container_id: str
    plan_hash: str
    state: DockerProcessState
    actor: Actor
    reason: str
    trace_id: str
    correlation_id: str
    causation_id: str = ""
    fault_point: str = ""


@dataclass(frozen=True)
class RecordExternalSideEffectReceipt:
    command_id: str
    idempotency_key: str
    project_id: str
    execution_request_id: str
    run_id: str
    lease_id: str
    lease_version: int
    fencing_token: int
    side_effect_key: str
    action_class: str
    target_class: str
    reversible: bool
    human_gate_authorization_ref: str
    request_payload_hash: str
    external_receipt_ref: str
    external_receipt_hash: str
    observed_outcome: str
    actor: Actor
    trace_id: str
    correlation_id: str
    causation_id: str = ""
    fault_point: str = ""


class ProductionExecutionStore(Protocol):
    def record_process(self, command: RecordDockerProcess) -> Mapping[str, Any]:
        ...

    def record_side_effect_receipt(self, command: RecordExternalSideEffectReceipt) -> Mapping[str, Any]:
        ...


class ProductionExecutionAuthority:
    def __init__(self, store: ProductionExecutionStore) -> None:
        self._store = store

    def record_process(self, command: RecordDockerProcess) -> Mapping[str, Any]:
        return self._store.record_process(command)

    def record_side_effect_receipt(self, command: RecordExternalSideEffectReceipt) -> Mapping[str, Any]:
        return self._store.record_side_effect_receipt(command)
