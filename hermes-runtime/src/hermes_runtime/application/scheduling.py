from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol


@dataclass(frozen=True)
class RegisterScheduler:
    command_id: str
    idempotency_key: str
    project_id: str
    scheduler_id: str
    scheduler_session_id: str
    actor_id: str
    reason: str = "register scheduler"
    actor_type: str = "scheduler"


@dataclass(frozen=True)
class AcquireExecutionLease:
    command_id: str
    idempotency_key: str
    project_id: str
    scheduler_id: str
    scheduler_session_id: str
    profile_id: str = "p2-default"
    profile_version: int = 1
    acquisition_limit: int = 1
    reason: str = "acquire execution lease"
    actor_type: str = "scheduler"
    actor_id: str = "scheduler"


@dataclass(frozen=True)
class RenewExecutionLease:
    command_id: str
    idempotency_key: str
    project_id: str
    execution_request_id: str
    lease_id: str
    scheduler_id: str
    scheduler_session_id: str
    fencing_token: int
    expected_lease_version: int
    reason: str = "renew execution lease"
    actor_type: str = "scheduler"
    actor_id: str = "scheduler"


@dataclass(frozen=True)
class RelinquishExecutionLease:
    command_id: str
    idempotency_key: str
    project_id: str
    execution_request_id: str
    lease_id: str
    scheduler_id: str
    scheduler_session_id: str
    fencing_token: int
    expected_lease_version: int
    reason: str = "relinquish execution lease"
    actor_type: str = "scheduler"
    actor_id: str = "scheduler"


class SchedulerStore(Protocol):
    def register_scheduler(self, command: RegisterScheduler) -> Mapping[str, Any]:
        ...

    def acquire_lease(self, command: AcquireExecutionLease) -> Mapping[str, Any]:
        ...

    def renew_lease(self, command: RenewExecutionLease) -> Mapping[str, Any]:
        ...

    def relinquish_lease(self, command: RelinquishExecutionLease) -> Mapping[str, Any]:
        ...

    def validate_current_lease(
        self,
        *,
        execution_request_id: str,
        lease_id: str,
        scheduler_id: str,
        scheduler_session_id: str,
        fencing_token: int,
        observed_request_version: Optional[int] = None,
    ) -> Mapping[str, Any]:
        ...


class ExecutionScheduler:
    def __init__(self, store: SchedulerStore) -> None:
        self._store = store

    def register(self, command: RegisterScheduler) -> Mapping[str, Any]:
        return self._store.register_scheduler(command)

    def acquire(self, command: AcquireExecutionLease) -> Mapping[str, Any]:
        return self._store.acquire_lease(command)

    def renew(self, command: RenewExecutionLease) -> Mapping[str, Any]:
        return self._store.renew_lease(command)

    def relinquish(self, command: RelinquishExecutionLease) -> Mapping[str, Any]:
        return self._store.relinquish_lease(command)

    def validate_current_lease(self, **kwargs: Any) -> Mapping[str, Any]:
        return self._store.validate_current_lease(**kwargs)
