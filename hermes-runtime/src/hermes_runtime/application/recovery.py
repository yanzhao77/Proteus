from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class EmitExecutionFeedback:
    command_id: str
    idempotency_key: str
    project_id: str
    result_id: str
    feedback_id: str
    repair_task_id: str
    max_attempts: int = 3
    actor_type: str = "recovery_controller"
    actor_id: str = "recovery-controller"
    reason: str = "emit execution failure feedback"


@dataclass(frozen=True)
class PlanRecoveryAttempt:
    command_id: str
    idempotency_key: str
    project_id: str
    cycle_id: str
    attempt_id: str
    actor_type: str = "recovery_controller"
    actor_id: str = "recovery-controller"
    reason: str = "plan bounded autonomous recovery attempt"


@dataclass(frozen=True)
class CompleteRecoveryAttempt:
    command_id: str
    idempotency_key: str
    project_id: str
    attempt_id: str
    outcome: str
    linked_execution_request_id: str = ""
    linked_result_id: str = ""
    linked_verification_id: str = ""
    actor_type: str = "recovery_controller"
    actor_id: str = "recovery-controller"
    reason: str = "complete recovery attempt ledger"


class RecoveryStore(Protocol):
    def emit_execution_feedback(self, command: EmitExecutionFeedback) -> Mapping[str, Any]:
        ...

    def plan_recovery_attempt(self, command: PlanRecoveryAttempt) -> Mapping[str, Any]:
        ...

    def complete_recovery_attempt(self, command: CompleteRecoveryAttempt) -> Mapping[str, Any]:
        ...


class RecoveryController:
    def __init__(self, store: RecoveryStore) -> None:
        self._store = store

    def emit_execution_feedback(self, command: EmitExecutionFeedback) -> Mapping[str, Any]:
        return self._store.emit_execution_feedback(command)

    def plan_recovery_attempt(self, command: PlanRecoveryAttempt) -> Mapping[str, Any]:
        return self._store.plan_recovery_attempt(command)

    def complete_recovery_attempt(self, command: CompleteRecoveryAttempt) -> Mapping[str, Any]:
        return self._store.complete_recovery_attempt(command)
