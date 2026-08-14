from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from hermes_runtime.domain.models import Actor


@dataclass(frozen=True)
class RequestReplay:
    command_id: str
    idempotency_key: str
    replay_session_id: str
    consumer_id: str
    stream_name: str
    partition_key: str
    source_generation_id: str
    target_generation_id: str
    start_sequence: int
    end_sequence: int
    consumer_version: str
    schema_version: str
    mode: str
    dry_run: bool
    expected_checkpoint_version: int
    actor: Actor
    reason: str
    authorization_ref: str


@dataclass(frozen=True)
class ExecuteReplay:
    command_id: str
    idempotency_key: str
    replay_session_id: str
    expected_replay_version: int
    fault_point: str = ""


@dataclass(frozen=True)
class ActivateReplay:
    command_id: str
    idempotency_key: str
    replay_session_id: str
    expected_replay_version: int
    authorization_ref: str
    fault_point: str = ""


@dataclass(frozen=True)
class ObserveReconcile:
    command_id: str
    idempotency_key: str
    scope_id: str
    actor: Actor
    reason: str
    authorization_ref: str
    consumer_id: str = ""
    partition_key: str = ""


@dataclass(frozen=True)
class CreateReconcilePlan:
    command_id: str
    idempotency_key: str
    plan_id: str
    finding_ids: Sequence[str]
    repair_actions: Sequence[str]
    dry_run: bool
    actor: Actor
    reason: str
    authorization_ref: str
    expires_at: str


@dataclass(frozen=True)
class ApplyReconcilePlan:
    command_id: str
    idempotency_key: str
    plan_id: str
    expected_plan_version: int
    actor: Actor
    reason: str
    authorization_ref: str
    fault_point: str = ""


class ReplayReconcileStore(Protocol):
    def request_replay(self, command: RequestReplay) -> Mapping[str, Any]:
        ...

    def execute_replay(self, command: ExecuteReplay) -> Mapping[str, Any]:
        ...

    def activate_replay(self, command: ActivateReplay) -> Mapping[str, Any]:
        ...

    def observe_reconcile(self, command: ObserveReconcile) -> Mapping[str, Any]:
        ...

    def create_reconcile_plan(self, command: CreateReconcilePlan) -> Mapping[str, Any]:
        ...

    def apply_reconcile_plan(self, command: ApplyReconcilePlan) -> Mapping[str, Any]:
        ...


class ReplayReconcileAuthority:
    def __init__(self, store: ReplayReconcileStore) -> None:
        self._store = store

    def request_replay(self, command: RequestReplay) -> Mapping[str, Any]:
        return self._store.request_replay(command)

    def execute_replay(self, command: ExecuteReplay) -> Mapping[str, Any]:
        return self._store.execute_replay(command)

    def activate_replay(self, command: ActivateReplay) -> Mapping[str, Any]:
        return self._store.activate_replay(command)

    def observe_reconcile(self, command: ObserveReconcile) -> Mapping[str, Any]:
        return self._store.observe_reconcile(command)

    def create_reconcile_plan(self, command: CreateReconcilePlan) -> Mapping[str, Any]:
        return self._store.create_reconcile_plan(command)

    def apply_reconcile_plan(self, command: ApplyReconcilePlan) -> Mapping[str, Any]:
        return self._store.apply_reconcile_plan(command)
